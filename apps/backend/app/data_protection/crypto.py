"""Envelope encryption, DSAR, legal hold, and master-key rotation."""

from __future__ import annotations

import base64
import json
import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Final, cast

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.data_protection.db.models import (
    DataProtectionDataKeyRow,
    DataProtectionErasureRequestRow,
    DataProtectionLegalHoldRow,
    TenantDataRetentionPolicyRow,
)

_DATA_KEY_BYTES: Final[int] = 32
_NONCE_BYTES: Final[int] = 12
_TENANT_SCOPE_ID: Final[str] = "__tenant__"
_JSON_MARKER: Final[str] = "__op_dp__"
_JSON_MARKER_VERSION: Final[str] = "v1"
_TEXT_PREFIX: Final[str] = "opdp:v1:"
_BYTES_PREFIX: Final[bytes] = b"OPDP1:"
_WRAPPED_KEY_PREFIX: Final[bytes] = b"OPDK1:"
_SENSITIVE_JSON_KEYS: Final[frozenset[str]] = frozenset(
    {
        "body",
        "canonical_payload",
        "content",
        "customer_message",
        "customer_reply",
        "draft_body",
        "message",
        "notes",
        "phase_a_response",
        "proposed_customer_reply",
        "reply",
        "safe_excerpt",
        "source_text",
        "summary",
        "synthesis_text",
        "text",
        "transcript",
        "transcript_text",
    }
)


class DataProtectionError(RuntimeError):
    """Raised when protected data cannot be encrypted or decrypted safely."""


class LegalHoldBlockedError(DataProtectionError):
    """Raised when legal hold blocks purge or DSAR erasure."""


class LegalHoldNotFoundError(DataProtectionError):
    """Raised when a legal hold is absent or already inactive."""


class ErasureRequestNotFoundError(DataProtectionError):
    """Raised when an erasure request is absent or tenant-invisible."""


class ErasureRequestLifecycleError(DataProtectionError):
    """Raised when an erasure request transition is not legal."""


class ErasureRequestSeparationError(DataProtectionError):
    """Raised when one principal attempts propose and approve duties."""


class ErasureRequestStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"


@dataclass(frozen=True, slots=True)
class _DataKey:
    data_key_id: uuid.UUID
    tenant_id: str
    scope: str
    scope_id: str
    key: bytes


@dataclass(frozen=True, slots=True)
class DataProtectionErasureRequestRecord:
    request_id: uuid.UUID
    tenant_id: str
    subject_id: str
    reason: str
    status: ErasureRequestStatus
    proposed_by: str
    proposed_at: datetime
    approved_by: str | None = None
    approved_at: datetime | None = None
    executed_at: datetime | None = None
    blocked_reason: str | None = None


@dataclass(frozen=True, slots=True)
class DataProtectionLegalHoldRecord:
    hold_id: uuid.UUID
    tenant_id: str
    scope: str
    scope_id: str
    reason: str
    created_by: str
    created_at: datetime
    lifted_at: datetime | None = None
    lifted_by: str | None = None


class MasterKeyRing:
    """Versioned platform master-key ring used to wrap random data keys."""

    __slots__ = ("_active_version", "_keys")

    def __init__(self, *, keys: Mapping[str, str | bytes], active_version: str) -> None:
        if not active_version.strip():
            raise DataProtectionError("active master key version is required")
        decoded: dict[str, bytes] = {}
        for version, raw_key in keys.items():
            normalized_version = version.strip()
            if not normalized_version:
                raise DataProtectionError("master key version must be non-empty")
            decoded[normalized_version] = _decode_key(raw_key)
        if active_version not in decoded:
            raise DataProtectionError("active master key version is not in the ring")
        self._active_version = active_version
        self._keys = decoded

    @classmethod
    def from_settings(cls, settings: Settings) -> "MasterKeyRing":
        raw_ring = getattr(settings, "DATA_PROTECTION_MASTER_KEYS", "")
        active = getattr(settings, "DATA_PROTECTION_ACTIVE_MASTER_KEY_VERSION", "")
        if raw_ring.strip():
            keys: dict[str, str] = {}
            for chunk in raw_ring.split(","):
                version, sep, material = chunk.partition(":")
                if not sep:
                    raise DataProtectionError(
                        "DATA_PROTECTION_MASTER_KEYS entries must be version:key"
                    )
                keys[version.strip()] = material.strip()
            active_version = active.strip() or next(iter(keys))
            return cls(keys=keys, active_version=active_version)
        key = settings.TENANT_CREDENTIAL_MASTER_KEY
        return cls(keys={"v1": key}, active_version="v1")

    @property
    def active_version(self) -> str:
        return self._active_version

    def wrap_key(
        self,
        *,
        data_key: bytes,
        tenant_id: str,
        scope: str,
        scope_id: str,
        data_key_id: uuid.UUID,
        version: str | None = None,
    ) -> tuple[str, bytes]:
        master_version = version or self._active_version
        master = self._master(master_version)
        nonce = os.urandom(_NONCE_BYTES)
        aad = _data_key_aad(
            tenant_id=tenant_id,
            scope=scope,
            scope_id=scope_id,
            data_key_id=data_key_id,
            master_key_version=master_version,
        )
        ciphertext = AESGCM(master).encrypt(nonce, data_key, aad)
        body = {
            "n": _b64e(nonce),
            "ct": _b64e(ciphertext),
        }
        return master_version, _WRAPPED_KEY_PREFIX + _json_bytes(body)

    def unwrap_key(self, row: DataProtectionDataKeyRow) -> bytes:
        if not row.encrypted_key.startswith(_WRAPPED_KEY_PREFIX):
            raise DataProtectionError("data key row has an unsupported envelope")
        try:
            body = json.loads(row.encrypted_key[len(_WRAPPED_KEY_PREFIX) :])
            nonce = _b64d(str(body["n"]))
            ciphertext = _b64d(str(body["ct"]))
        except Exception as exc:
            raise DataProtectionError("data key row envelope is invalid") from exc
        master = self._master(row.master_key_version)
        aad = _data_key_aad(
            tenant_id=row.tenant_id,
            scope=row.scope,
            scope_id=row.scope_id,
            data_key_id=row.data_key_id,
            master_key_version=row.master_key_version,
        )
        try:
            return AESGCM(master).decrypt(nonce, ciphertext, aad)
        except InvalidTag as exc:
            raise DataProtectionError("data key could not be authenticated") from exc

    def _master(self, version: str) -> bytes:
        try:
            return self._keys[version]
        except KeyError as exc:
            raise DataProtectionError(f"master key version {version!r} is unavailable") from exc


class DataProtectionService:
    """Persistence-bound envelope encryption runtime."""

    __slots__ = ("_ring", "_session")

    def __init__(self, session: AsyncSession, *, master_key_ring: MasterKeyRing) -> None:
        self._session = session
        self._ring = master_key_ring

    @classmethod
    def from_settings(cls, session: AsyncSession, settings: Settings) -> "DataProtectionService":
        return cls(session, master_key_ring=MasterKeyRing.from_settings(settings))

    async def encrypt_json_values(
        self,
        value: Mapping[str, Any],
        *,
        tenant_id: str,
        subject_id: str | None,
        field: str,
        tenant_scoped: bool = False,
    ) -> dict[str, Any]:
        data_key = await self._require_key(
            tenant_id=tenant_id,
            subject_id=subject_id,
            tenant_scoped=tenant_scoped,
        )
        return await self._encrypt_json_mapping(
            dict(value),
            data_key=data_key,
            field=field,
        )

    async def decrypt_json_values(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], await self._decrypt_json_value(dict(value)))

    async def encrypt_text(
        self,
        value: str,
        *,
        tenant_id: str,
        subject_id: str | None,
        field: str,
        tenant_scoped: bool = False,
    ) -> str:
        if _is_text_marker(value):
            return value
        data_key = await self._require_key(
            tenant_id=tenant_id,
            subject_id=subject_id,
            tenant_scoped=tenant_scoped,
        )
        marker = self._encrypt_marker(value.encode("utf-8"), data_key=data_key, field=field)
        return _TEXT_PREFIX + _b64e(_json_bytes(marker))

    async def decrypt_text(self, value: str) -> str:
        if not _is_text_marker(value):
            return value
        try:
            marker = json.loads(_b64d(value[len(_TEXT_PREFIX) :]))
        except Exception as exc:
            raise DataProtectionError("encrypted text marker is invalid") from exc
        plaintext = await self._decrypt_marker(cast(Mapping[str, Any], marker))
        return plaintext.decode("utf-8")

    async def encrypt_bytes(
        self,
        value: bytes,
        *,
        tenant_id: str,
        subject_id: str | None,
        field: str,
        tenant_scoped: bool = False,
    ) -> bytes:
        if value.startswith(_BYTES_PREFIX):
            return value
        data_key = await self._require_key(
            tenant_id=tenant_id,
            subject_id=subject_id,
            tenant_scoped=tenant_scoped,
        )
        marker = self._encrypt_marker(value, data_key=data_key, field=field)
        return _BYTES_PREFIX + _json_bytes(marker)

    async def decrypt_bytes(self, value: bytes) -> bytes:
        if not value.startswith(_BYTES_PREFIX):
            return value
        try:
            marker = json.loads(value[len(_BYTES_PREFIX) :])
        except Exception as exc:
            raise DataProtectionError("encrypted bytes marker is invalid") from exc
        return await self._decrypt_marker(cast(Mapping[str, Any], marker))

    async def has_active_legal_hold(
        self,
        *,
        tenant_id: str,
        subject_id: str | None = None,
        session_id: str | None = None,
    ) -> bool:
        clauses = [
            (DataProtectionLegalHoldRow.scope == "tenant")
            & (DataProtectionLegalHoldRow.scope_id == _TENANT_SCOPE_ID)
        ]
        if subject_id:
            clauses.append(
                (DataProtectionLegalHoldRow.scope == "subject")
                & (DataProtectionLegalHoldRow.scope_id == subject_id)
            )
        if session_id:
            clauses.append(
                (DataProtectionLegalHoldRow.scope == "session")
                & (DataProtectionLegalHoldRow.scope_id == session_id)
            )
        stmt = select(DataProtectionLegalHoldRow.hold_id).where(
            DataProtectionLegalHoldRow.tenant_id == tenant_id,
            DataProtectionLegalHoldRow.lifted_at.is_(None),
            or_(*clauses),
        )
        return (await self._session.execute(stmt)).first() is not None

    async def create_legal_hold(
        self,
        *,
        tenant_id: str,
        scope: str,
        scope_id: str | None,
        reason: str,
        created_by: str,
    ) -> uuid.UUID:
        normalized_scope_id = _scope_id(scope, scope_id)
        hold_id = uuid.uuid4()  # EPHEMERAL: random legal-hold record id
        await self._ensure_tenant(tenant_id)
        self._session.add(
            DataProtectionLegalHoldRow(
                hold_id=hold_id,
                tenant_id=tenant_id,
                scope=scope,
                scope_id=normalized_scope_id,
                reason=reason,
                created_by=created_by,
            )
        )
        await self._session.flush()
        return hold_id

    async def list_legal_holds(
        self,
        *,
        tenant_id: str,
    ) -> tuple[DataProtectionLegalHoldRecord, ...]:
        stmt = (
            select(DataProtectionLegalHoldRow)
            .where(
                DataProtectionLegalHoldRow.tenant_id == tenant_id,
                DataProtectionLegalHoldRow.lifted_at.is_(None),
            )
            .order_by(
                DataProtectionLegalHoldRow.created_at.desc(),
                DataProtectionLegalHoldRow.hold_id.desc(),
            )
        )
        rows = (await self._session.execute(stmt)).scalars()
        return tuple(_legal_hold_record(row) for row in rows)

    async def get_legal_hold(
        self,
        *,
        tenant_id: str,
        hold_id: uuid.UUID | str,
    ) -> DataProtectionLegalHoldRecord | None:
        stmt = select(DataProtectionLegalHoldRow).where(
            DataProtectionLegalHoldRow.hold_id == _uuid(hold_id, field="hold_id"),
            DataProtectionLegalHoldRow.tenant_id == tenant_id,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _legal_hold_record(row)

    async def release_legal_hold(
        self,
        *,
        tenant_id: str,
        hold_id: uuid.UUID | str,
        lifted_by: str,
    ) -> DataProtectionLegalHoldRecord:
        normalized_hold_id = _uuid(hold_id, field="hold_id")
        stmt = select(DataProtectionLegalHoldRow).where(
            DataProtectionLegalHoldRow.hold_id == normalized_hold_id,
            DataProtectionLegalHoldRow.tenant_id == tenant_id,
            DataProtectionLegalHoldRow.lifted_at.is_(None),
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise LegalHoldNotFoundError("active legal hold not found")
        row.lifted_at = datetime.now(timezone.utc)
        row.lifted_by = _nonempty(lifted_by, field="lifted_by")
        await self._session.flush()
        return _legal_hold_record(row)

    async def propose_erasure(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        reason: str,
        proposed_by: str,
    ) -> DataProtectionErasureRequestRecord:
        request_id = uuid.uuid4()  # EPHEMERAL: random erasure-request record id
        now = datetime.now(timezone.utc)
        await self._ensure_tenant(tenant_id)
        row = DataProtectionErasureRequestRow(
            request_id=request_id,
            tenant_id=tenant_id,
            subject_id=_nonempty(subject_id, field="subject_id"),
            reason=_nonempty(reason, field="reason"),
            status=ErasureRequestStatus.PROPOSED.value,
            proposed_by=_nonempty(proposed_by, field="proposed_by"),
            proposed_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        return _erasure_request_record(row)

    async def approve_erasure(
        self,
        *,
        tenant_id: str,
        request_id: uuid.UUID | str,
        approved_by: str,
    ) -> DataProtectionErasureRequestRecord:
        approver = _nonempty(approved_by, field="approved_by")
        row = await self._erasure_request_row(
            tenant_id=tenant_id,
            request_id=_uuid(request_id, field="request_id"),
        )
        if row is None:
            raise ErasureRequestNotFoundError("erasure request not found")
        status = ErasureRequestStatus(row.status)
        if status is not ErasureRequestStatus.PROPOSED:
            raise ErasureRequestLifecycleError(
                f"cannot approve a {row.status} erasure request"
            )
        if approver == row.proposed_by:
            raise ErasureRequestSeparationError(
                "erasure approver must differ from proposer"
            )
        if await self.has_active_legal_hold(
            tenant_id=tenant_id,
            subject_id=row.subject_id,
        ):
            row.status = ErasureRequestStatus.REJECTED.value
            row.blocked_reason = "active legal hold blocks DSAR erasure"
            await self._session.flush()
            raise LegalHoldBlockedError("active legal hold blocks DSAR erasure")
        now = datetime.now(timezone.utc)
        row.status = ErasureRequestStatus.APPROVED.value
        row.approved_by = approver
        row.approved_at = now
        await self._session.flush()
        await self._delete_subject_key(
            tenant_id=tenant_id,
            subject_id=row.subject_id,
        )
        row.status = ErasureRequestStatus.EXECUTED.value
        row.executed_at = now
        row.blocked_reason = None
        await self._session.flush()
        return _erasure_request_record(row)

    async def erase_subject_key(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        requested_by: str,
    ) -> uuid.UUID:
        del tenant_id, subject_id, requested_by
        raise DataProtectionError(
            "subject erasure requires dual-control propose/approve"
        )

    async def _delete_subject_key(
        self,
        *,
        tenant_id: str,
        subject_id: str,
    ) -> int:
        result = await self._session.execute(
            delete(DataProtectionDataKeyRow)
            .where(
                DataProtectionDataKeyRow.tenant_id == tenant_id,
                DataProtectionDataKeyRow.scope == "subject",
                DataProtectionDataKeyRow.scope_id == subject_id,
            )
            .returning(DataProtectionDataKeyRow.data_key_id)
        )
        return sum(1 for _ in result.scalars())

    async def _erasure_request_row(
        self,
        *,
        tenant_id: str,
        request_id: uuid.UUID,
    ) -> DataProtectionErasureRequestRow | None:
        stmt = select(DataProtectionErasureRequestRow).where(
            DataProtectionErasureRequestRow.request_id == request_id,
            DataProtectionErasureRequestRow.tenant_id == tenant_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def erase_tenant_keys(self, *, tenant_id: str) -> int:
        if await self.has_active_legal_hold(tenant_id=tenant_id):
            raise LegalHoldBlockedError("active legal hold blocks tenant erasure")
        result = await self._session.execute(
            delete(DataProtectionDataKeyRow)
            .where(DataProtectionDataKeyRow.tenant_id == tenant_id)
            .returning(DataProtectionDataKeyRow.data_key_id)
        )
        await self._session.flush()
        return sum(1 for _ in result.scalars())

    async def rotate_master_key(self, *, new_ring: MasterKeyRing) -> int:
        rows = (
            await self._session.execute(select(DataProtectionDataKeyRow))
        ).scalars()
        rewrapped = 0
        for row in rows:
            data_key = self._ring.unwrap_key(row)
            version, encrypted = new_ring.wrap_key(
                data_key=data_key,
                tenant_id=row.tenant_id,
                scope=row.scope,
                scope_id=row.scope_id,
                data_key_id=row.data_key_id,
            )
            row.master_key_version = version
            row.encrypted_key = encrypted
            row.rewrapped_at = datetime.now(timezone.utc)
            _ = new_ring.unwrap_key(row)
            rewrapped += 1
        await self._session.flush()
        self._ring = new_ring
        return rewrapped

    async def purge_expired_cognition_audits(self, *, now: datetime | None = None) -> int:
        cutoff_now = now or datetime.now(timezone.utc)
        rows = (
            await self._session.execute(select(TenantDataRetentionPolicyRow))
        ).scalars()
        deleted_total = 0
        for policy in rows:
            if await self.has_active_legal_hold(tenant_id=policy.tenant_id):
                continue
            cutoff = cutoff_now - timedelta(days=policy.retention_days)
            audit_row = _cognition_audit_row()
            result = await self._session.execute(
                delete(audit_row)
                .where(
                    audit_row.tenant_id == policy.tenant_id,
                    audit_row.captured_at < cutoff,
                )
                .returning(audit_row.audit_id)
            )
            deleted_total += sum(1 for _ in result.scalars())
        return deleted_total

    async def retention_days_for_tenant(self, tenant_id: str) -> int:
        stmt = select(TenantDataRetentionPolicyRow.retention_days).where(
            TenantDataRetentionPolicyRow.tenant_id == tenant_id
        )
        value = (await self._session.execute(stmt)).scalar_one_or_none()
        return int(value or 90)

    async def set_retention_policy(
        self,
        *,
        tenant_id: str,
        retention_days: int,
        updated_by: str,
    ) -> None:
        if retention_days < 1:
            raise DataProtectionError("retention_days must be positive")
        await self._ensure_tenant(tenant_id)
        existing = await self._session.get(TenantDataRetentionPolicyRow, tenant_id)
        if existing is None:
            self._session.add(
                TenantDataRetentionPolicyRow(
                    tenant_id=tenant_id,
                    retention_days=retention_days,
                    updated_by=updated_by,
                    updated_at=datetime.now(timezone.utc),
                )
            )
        else:
            existing.retention_days = retention_days
            existing.updated_by = updated_by
            existing.updated_at = datetime.now(timezone.utc)
        await self._session.flush()

    async def _require_key(
        self,
        *,
        tenant_id: str,
        subject_id: str | None,
        tenant_scoped: bool,
    ) -> _DataKey:
        scope = "tenant" if tenant_scoped else "subject"
        scope_identifier = _TENANT_SCOPE_ID if tenant_scoped else (subject_id or "").strip()
        if not scope_identifier:
            raise DataProtectionError("subject_id is required for subject-scoped encryption")
        row = await self._data_key_row(
            tenant_id=tenant_id,
            scope=scope,
            scope_id=scope_identifier,
        )
        if row is None:
            row = await self._create_data_key(
                tenant_id=tenant_id,
                scope=scope,
                scope_id=scope_identifier,
            )
        return _DataKey(
            data_key_id=row.data_key_id,
            tenant_id=row.tenant_id,
            scope=row.scope,
            scope_id=row.scope_id,
            key=self._ring.unwrap_key(row),
        )

    async def _data_key_row(
        self,
        *,
        tenant_id: str,
        scope: str,
        scope_id: str,
    ) -> DataProtectionDataKeyRow | None:
        stmt = select(DataProtectionDataKeyRow).where(
            DataProtectionDataKeyRow.tenant_id == tenant_id,
            DataProtectionDataKeyRow.scope == scope,
            DataProtectionDataKeyRow.scope_id == scope_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def _create_data_key(
        self,
        *,
        tenant_id: str,
        scope: str,
        scope_id: str,
    ) -> DataProtectionDataKeyRow:
        await self._ensure_tenant(tenant_id)
        data_key_id = uuid.uuid4()  # EPHEMERAL: random per-scope data-key id
        data_key = os.urandom(_DATA_KEY_BYTES)
        master_version, encrypted_key = self._ring.wrap_key(
            data_key=data_key,
            tenant_id=tenant_id,
            scope=scope,
            scope_id=scope_id,
            data_key_id=data_key_id,
        )
        row = DataProtectionDataKeyRow(
            data_key_id=data_key_id,
            tenant_id=tenant_id,
            scope=scope,
            scope_id=scope_id,
            master_key_version=master_version,
            encrypted_key=encrypted_key,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(row)
                await self._session.flush()
        except IntegrityError:
            existing = await self._data_key_row(
                tenant_id=tenant_id,
                scope=scope,
                scope_id=scope_id,
            )
            if existing is None:
                raise
            return existing
        return row

    async def _ensure_tenant(self, tenant_id: str) -> None:
        await self._session.merge(_tenant_row()(tenant_id=tenant_id))
        await self._session.flush()

    async def _encrypt_json_mapping(
        self,
        value: dict[str, Any],
        *,
        data_key: _DataKey,
        field: str,
    ) -> dict[str, Any]:
        encrypted: dict[str, Any] = {}
        for key, item in value.items():
            child_field = f"{field}.{key}"
            if isinstance(item, str) and key in _SENSITIVE_JSON_KEYS:
                encrypted[key] = self._encrypt_marker(
                    item.encode("utf-8"),
                    data_key=data_key,
                    field=child_field,
                )
            elif isinstance(item, Mapping):
                encrypted[key] = await self._encrypt_json_mapping(
                    _json_dict(cast(Mapping[Any, Any], item)),
                    data_key=data_key,
                    field=child_field,
                )
            elif isinstance(item, list):
                encrypted[key] = [
                    await self._encrypt_json_value(
                        element,
                        data_key=data_key,
                        field=f"{child_field}[]",
                    )
                    for element in cast(list[Any], item)
                ]
            else:
                encrypted[key] = item
        return encrypted

    async def _encrypt_json_value(
        self,
        value: Any,
        *,
        data_key: _DataKey,
        field: str,
    ) -> Any:
        if isinstance(value, Mapping):
            return await self._encrypt_json_mapping(
                _json_dict(cast(Mapping[Any, Any], value)),
                data_key=data_key,
                field=field,
            )
        if isinstance(value, list):
            return [
                await self._encrypt_json_value(
                    item,
                    data_key=data_key,
                    field=f"{field}[]",
                )
                for item in cast(list[Any], value)
            ]
        return value

    async def _decrypt_json_value(self, value: Any) -> Any:
        if _is_json_marker(value):
            plaintext = await self._decrypt_marker(cast(Mapping[str, Any], value))
            return plaintext.decode("utf-8")
        if isinstance(value, Mapping):
            mapping = cast(Mapping[Any, Any], value)
            return {
                str(key): await self._decrypt_json_value(item)
                for key, item in mapping.items()
            }
        if isinstance(value, list):
            return [
                await self._decrypt_json_value(item)
                for item in cast(list[Any], value)
            ]
        return value

    def _encrypt_marker(
        self,
        plaintext: bytes,
        *,
        data_key: _DataKey,
        field: str,
    ) -> dict[str, str]:
        nonce = os.urandom(_NONCE_BYTES)
        aad = _payload_aad(data_key=data_key, field=field)
        ciphertext = AESGCM(data_key.key).encrypt(nonce, plaintext, aad)
        return {
            _JSON_MARKER: _JSON_MARKER_VERSION,
            "kid": str(data_key.data_key_id),
            "f": field,
            "n": _b64e(nonce),
            "ct": _b64e(ciphertext),
        }

    async def _decrypt_marker(self, marker: Mapping[str, Any]) -> bytes:
        if marker.get(_JSON_MARKER) != _JSON_MARKER_VERSION:
            raise DataProtectionError("encrypted marker version is unsupported")
        try:
            data_key_id = uuid.UUID(str(marker["kid"]))
            field = str(marker["f"])
            nonce = _b64d(str(marker["n"]))
            ciphertext = _b64d(str(marker["ct"]))
        except Exception as exc:
            raise DataProtectionError("encrypted marker is invalid") from exc
        row = await self._session.get(DataProtectionDataKeyRow, data_key_id)
        if row is None:
            raise DataProtectionError("data key is unavailable or erased")
        data_key = _DataKey(
            data_key_id=row.data_key_id,
            tenant_id=row.tenant_id,
            scope=row.scope,
            scope_id=row.scope_id,
            key=self._ring.unwrap_key(row),
        )
        try:
            return AESGCM(data_key.key).decrypt(
                nonce,
                ciphertext,
                _payload_aad(data_key=data_key, field=field),
            )
        except InvalidTag as exc:
            raise DataProtectionError("encrypted payload could not be authenticated") from exc


def _scope_id(scope: str, value: str | None) -> str:
    if scope == "tenant":
        return _TENANT_SCOPE_ID
    if scope not in {"subject", "session"}:
        raise DataProtectionError("legal hold scope must be tenant, subject, or session")
    normalized = (value or "").strip()
    if not normalized:
        raise DataProtectionError(f"{scope} legal hold requires a scope_id")
    return normalized


def _nonempty(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise DataProtectionError(f"{field} must be non-empty")
    return normalized


def _uuid(value: uuid.UUID | str, *, field: str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise DataProtectionError(f"{field} must be a valid UUID") from exc


def _legal_hold_record(row: DataProtectionLegalHoldRow) -> DataProtectionLegalHoldRecord:
    return DataProtectionLegalHoldRecord(
        hold_id=row.hold_id,
        tenant_id=row.tenant_id,
        scope=row.scope,
        scope_id=row.scope_id,
        reason=row.reason,
        created_by=row.created_by,
        created_at=row.created_at,
        lifted_at=row.lifted_at,
        lifted_by=row.lifted_by,
    )


def _erasure_request_record(
    row: DataProtectionErasureRequestRow,
) -> DataProtectionErasureRequestRecord:
    return DataProtectionErasureRequestRecord(
        request_id=row.request_id,
        tenant_id=row.tenant_id,
        subject_id=row.subject_id,
        reason=row.reason,
        status=ErasureRequestStatus(row.status),
        proposed_by=row.proposed_by,
        proposed_at=row.proposed_at,
        approved_by=row.approved_by,
        approved_at=row.approved_at,
        executed_at=row.executed_at,
        blocked_reason=row.blocked_reason,
    )


def _payload_aad(*, data_key: _DataKey, field: str) -> bytes:
    return (
        "opdp.payload.v1|"
        f"{data_key.data_key_id}|{data_key.tenant_id}|"
        f"{data_key.scope}|{data_key.scope_id}|{field}"
    ).encode("utf-8")


def _data_key_aad(
    *,
    tenant_id: str,
    scope: str,
    scope_id: str,
    data_key_id: uuid.UUID,
    master_key_version: str,
) -> bytes:
    return (
        "opdp.datakey.v1|"
        f"{data_key_id}|{tenant_id}|{scope}|{scope_id}|{master_key_version}"
    ).encode("utf-8")


def _decode_key(raw: str | bytes) -> bytes:
    if isinstance(raw, bytes):
        key = raw
    else:
        text = raw.strip()
        if not text:
            raise DataProtectionError("master key material is required")
        key = _try_b64(text) or _try_hex(text) or text.encode("utf-8")
    if len(key) < _DATA_KEY_BYTES:
        raise DataProtectionError("master key material must contain at least 32 bytes")
    return key[:_DATA_KEY_BYTES]


def _try_b64(text: str) -> bytes | None:
    try:
        decoded = base64.b64decode(text, validate=True)
    except Exception:
        return None
    return decoded or None


def _try_hex(text: str) -> bytes | None:
    try:
        decoded = bytes.fromhex(text)
    except ValueError:
        return None
    return decoded or None


def _b64e(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64d(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _json_dict(value: Mapping[Any, Any]) -> dict[str, Any]:
    return {str(key): item for key, item in value.items()}


def _is_json_marker(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    marker = cast(Mapping[str, Any], value)
    return marker.get(_JSON_MARKER) == _JSON_MARKER_VERSION


def _is_text_marker(value: str) -> bool:
    return value.startswith(_TEXT_PREFIX)


def _cognition_audit_row() -> Any:
    from app.cognition.db.models import CognitionAuditRecordRow

    return CognitionAuditRecordRow


def _tenant_row() -> Any:
    from app.tenant.db.models import TenantRow

    return TenantRow


__all__ = [
    "DataProtectionErasureRequestRecord",
    "DataProtectionError",
    "DataProtectionLegalHoldRecord",
    "DataProtectionService",
    "ErasureRequestLifecycleError",
    "ErasureRequestNotFoundError",
    "ErasureRequestSeparationError",
    "ErasureRequestStatus",
    "LegalHoldBlockedError",
    "LegalHoldNotFoundError",
    "MasterKeyRing",
]
