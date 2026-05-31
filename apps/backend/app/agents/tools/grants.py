"""Durable one-time grants for pre-approved agent actions."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from typing import Any, Protocol, cast

from sqlalchemy import RowMapping, text
from sqlalchemy.exc import IntegrityError

from app.agents.context import AgentExecutionContext
from app.db.repository import TenantScopedRepository
from app.types.json import JsonObject, JsonValue, MetadataMap

AGENT_ACTION_ACTOR_KEY = "agent_action_actor"
AGENT_ACTION_GRANT_ID_KEY = "agent_action_grant_id"
AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY = "agent_action_provider_idempotency_key"

_AGENT_ACTION_GRANT_NAMESPACE = uuid.UUID(
    "aa6e7001-0009-4009-8009-000000000009"
)
_AGENT_ACTION_PROVIDER_IDEMPOTENCY_NAMESPACE = uuid.UUID(
    "aa6e7001-0010-4010-8010-000000000010"
)
_SESSION_SCOPE_SQL = text(
    "SELECT set_config('app.current_tenant_id', :tenant_id, true)"
)

_INSERT_GRANT_SQL = text(
    """
    INSERT INTO public.agent_action_grants (
        grant_id,
        tenant_id,
        decision_id,
        tool_name,
        action,
        actor,
        payload_hash,
        binding_hash,
        idempotency_key,
        issued_at,
        expires_at,
        consumed_at,
        consumed_by,
        metadata
    )
    VALUES (
        CAST(:grant_id AS uuid),
        :tenant_id,
        CAST(:decision_id AS uuid),
        :tool_name,
        :action,
        :actor,
        :payload_hash,
        :binding_hash,
        :idempotency_key,
        :issued_at,
        :expires_at,
        NULL,
        NULL,
        CAST(:metadata AS jsonb)
    )
    ON CONFLICT (decision_id) DO NOTHING
    """
)

_SELECT_GRANT_SQL = text(
    """
    SELECT
        grant_id,
        tenant_id,
        decision_id,
        tool_name,
        action,
        actor,
        payload_hash,
        binding_hash,
        idempotency_key,
        issued_at,
        expires_at,
        consumed_at,
        consumed_by,
        metadata
    FROM public.agent_action_grants
    WHERE decision_id = CAST(:decision_id AS uuid)
      AND tenant_id = :tenant_id
    """
)

_CONSUME_GRANT_SQL = text(
    """
    UPDATE public.agent_action_grants
    SET consumed_at = now(),
        consumed_by = :actor
    WHERE decision_id = CAST(:decision_id AS uuid)
      AND tenant_id = :tenant_id
      AND consumed_at IS NULL
    RETURNING
        grant_id,
        tenant_id,
        decision_id,
        tool_name,
        action,
        actor,
        payload_hash,
        binding_hash,
        idempotency_key,
        issued_at,
        expires_at,
        consumed_at,
        consumed_by,
        metadata
    """
)


class AgentActionGrantError(RuntimeError):
    """Base class for durable action grant failures."""


class AlreadyConsumedError(AgentActionGrantError):
    """Raised when a grant row is absent or already consumed."""


class ActorMismatchError(AgentActionGrantError):
    """Raised when a grant is presented by a different execution actor."""

    status_code: int = 403


def _empty_json_object() -> JsonObject:
    return {}


@dataclass(frozen=True, slots=True)
class AgentActionGrantRecord:
    grant_id: str
    tenant_id: str
    decision_id: str
    tool_name: str
    action: str
    actor: str
    payload_hash: str
    binding_hash: str
    idempotency_key: str
    issued_at: datetime
    expires_at: datetime | None
    consumed_at: datetime | None = None
    consumed_by: str | None = None
    metadata: MetadataMap = field(default_factory=_empty_json_object)


class AgentActionGrantRepository(Protocol):
    async def issue_grant(
        self,
        *,
        tenant_id: str,
        decision_id: uuid.UUID,
        tool_name: str,
        action: str,
        actor: str,
        payload_hash: str,
        binding_hash: str,
        issued_at: datetime,
        expires_at: datetime | None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AgentActionGrantRecord: ...

    async def consume_grant(
        self,
        *,
        decision_id: uuid.UUID,
        tenant_id: str,
        actor: str,
    ) -> AgentActionGrantRecord: ...

    async def get_grant(
        self,
        *,
        decision_id: uuid.UUID,
        tenant_id: str,
    ) -> AgentActionGrantRecord | None: ...


class PostgresAgentActionGrantRepository(TenantScopedRepository):
    """Postgres-backed durable grant repository."""

    async def issue_grant(
        self,
        *,
        tenant_id: str,
        decision_id: uuid.UUID,
        tool_name: str,
        action: str,
        actor: str,
        payload_hash: str,
        binding_hash: str,
        issued_at: datetime,
        expires_at: datetime | None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AgentActionGrantRecord:
        await self._scope(tenant_id)
        grant_id = derive_agent_action_grant_id(
            tenant_id=tenant_id,
            decision_id=decision_id,
        )
        idempotency_key = derive_provider_idempotency_key(
            tenant_id=tenant_id,
            grant_id=grant_id,
            payload_hash=payload_hash,
        )
        try:
            async with self.session.begin_nested():
                await self.session.execute(
                    _INSERT_GRANT_SQL,
                    {
                        "grant_id": str(grant_id),
                        "tenant_id": tenant_id,
                        "decision_id": str(decision_id),
                        "tool_name": tool_name,
                        "action": action,
                        "actor": actor,
                        "payload_hash": payload_hash,
                        "binding_hash": binding_hash,
                        "idempotency_key": str(idempotency_key),
                        "issued_at": issued_at,
                        "expires_at": expires_at,
                        "metadata": json.dumps(
                            _metadata_with_schema_version(metadata or {}),
                            sort_keys=True,
                        ),
                    },
                )
        except IntegrityError as exc:
            raise AgentActionGrantError(
                "failed to issue durable action grant"
            ) from exc
        record = await self.get_grant(
            decision_id=decision_id,
            tenant_id=tenant_id,
        )
        if record is None:
            raise AgentActionGrantError(
                "issued action grant is not visible for tenant"
            )
        _assert_issued_grant_matches(
            record=record,
            tool_name=tool_name,
            action=action,
            actor=actor,
            payload_hash=payload_hash,
            binding_hash=binding_hash,
            idempotency_key=str(idempotency_key),
        )
        return record

    async def consume_grant(
        self,
        *,
        decision_id: uuid.UUID,
        tenant_id: str,
        actor: str,
    ) -> AgentActionGrantRecord:
        await self._scope(tenant_id)
        existing = await self.get_grant(
            decision_id=decision_id,
            tenant_id=tenant_id,
        )
        if existing is not None and existing.actor != actor:
            raise ActorMismatchError(
                "action grant actor mismatch: "
                f"expected {existing.actor!r}, got {actor!r}"
            )
        row = (
            await self.session.execute(
                _CONSUME_GRANT_SQL,
                {
                    "decision_id": str(decision_id),
                    "tenant_id": tenant_id,
                    "actor": actor,
                },
            )
        ).mappings().one_or_none()
        if row is None:
            raise AlreadyConsumedError(
                "action grant already consumed or absent"
            )
        return _row_to_record(row)

    async def get_grant(
        self,
        *,
        decision_id: uuid.UUID,
        tenant_id: str,
    ) -> AgentActionGrantRecord | None:
        await self._scope(tenant_id)
        row = (
            await self.session.execute(
                _SELECT_GRANT_SQL,
                {
                    "decision_id": str(decision_id),
                    "tenant_id": tenant_id,
                },
            )
        ).mappings().one_or_none()
        return None if row is None else _row_to_record(row)

    async def _scope(self, tenant_id: str) -> None:
        await self.session.execute(_SESSION_SCOPE_SQL, {"tenant_id": tenant_id})


def derive_agent_action_grant_id(
    *,
    tenant_id: str,
    decision_id: uuid.UUID,
) -> uuid.UUID:
    """Derive the deterministic UUID5 grant identity."""

    return uuid.uuid5(
        _AGENT_ACTION_GRANT_NAMESPACE,
        f"{tenant_id}|{decision_id}",
    )


def derive_provider_idempotency_key(
    *,
    tenant_id: str,
    grant_id: uuid.UUID,
    payload_hash: str,
) -> uuid.UUID:
    """Derive provider idempotency from tenant, grant, and payload."""

    return uuid.uuid5(
        _AGENT_ACTION_PROVIDER_IDEMPOTENCY_NAMESPACE,
        f"{tenant_id}|{grant_id}|{payload_hash}",
    )


def compute_agent_action_payload_hash(payload: Mapping[str, Any]) -> str:
    """Canonical SHA-256 hash of a tool action payload."""

    payload_canonical = json.dumps(
        dict(payload), sort_keys=True, separators=(",", ":"), default=str
    )
    return sha256(payload_canonical.encode("utf-8")).hexdigest()


def compute_agent_execution_actor(context: AgentExecutionContext) -> str:
    """Return the stable actor bound into action grants.

    Manager-approved re-invocation rehydrates ``AGENT_ACTION_ACTOR_KEY``
    from the original approval metadata; normal invocations fall back to
    the typed principal axis, then the stable agent identity.
    """

    metadata_actor = context.metadata.get(AGENT_ACTION_ACTOR_KEY)
    if isinstance(metadata_actor, str) and metadata_actor:
        return metadata_actor
    authority = context.authority
    if authority is not None and authority.principal_id is not None:
        return str(authority.principal_id)
    return f"agent:{context.identity.agent_id}"


def _metadata_with_schema_version(metadata: Mapping[str, Any]) -> dict[str, Any]:
    versioned = dict(metadata)
    versioned["_schema_version"] = "1"
    return versioned


def _row_to_record(row: RowMapping) -> AgentActionGrantRecord:
    return AgentActionGrantRecord(
        grant_id=str(row["grant_id"]),
        tenant_id=str(row["tenant_id"]),
        decision_id=str(row["decision_id"]),
        tool_name=str(row["tool_name"]),
        action=str(row["action"]),
        actor=str(row["actor"]),
        payload_hash=str(row["payload_hash"]),
        binding_hash=str(row["binding_hash"]),
        idempotency_key=str(row["idempotency_key"]),
        issued_at=cast(datetime, row["issued_at"]),
        expires_at=cast(datetime | None, row["expires_at"]),
        consumed_at=cast(datetime | None, row["consumed_at"]),
        consumed_by=(
            str(row["consumed_by"]) if row["consumed_by"] is not None else None
        ),
        metadata=_json_object(row["metadata"]),
    )


def _assert_issued_grant_matches(
    *,
    record: AgentActionGrantRecord,
    tool_name: str,
    action: str,
    actor: str,
    payload_hash: str,
    binding_hash: str,
    idempotency_key: str,
) -> None:
    mismatches: list[str] = []
    expected = {
        "tool_name": tool_name,
        "action": action,
        "actor": actor,
        "payload_hash": payload_hash,
        "binding_hash": binding_hash,
        "idempotency_key": idempotency_key,
    }
    for field_name, expected_value in expected.items():
        actual_value = getattr(record, field_name)
        if actual_value != expected_value:
            mismatches.append(field_name)
    if mismatches:
        raise AgentActionGrantError(
            "existing action grant differs from requested issuance: "
            + ", ".join(sorted(mismatches))
        )


def _json_object(value: object) -> JsonObject:
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {
            str(key): _json_value(json_value)
            for key, json_value in mapping.items()
        }
    return {}


def _json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        return _json_object(cast(Mapping[object, object], value))
    if isinstance(value, list | tuple):
        sequence = cast(list[object] | tuple[object, ...], value)
        return [_json_value(item) for item in sequence]
    return str(value)


__all__ = [
    "AGENT_ACTION_ACTOR_KEY",
    "AGENT_ACTION_GRANT_ID_KEY",
    "AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY",
    "ActorMismatchError",
    "AgentActionGrantError",
    "AgentActionGrantRecord",
    "AgentActionGrantRepository",
    "AlreadyConsumedError",
    "PostgresAgentActionGrantRepository",
    "compute_agent_action_payload_hash",
    "compute_agent_execution_actor",
    "derive_agent_action_grant_id",
    "derive_provider_idempotency_key",
]
