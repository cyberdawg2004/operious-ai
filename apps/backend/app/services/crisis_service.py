"""Crisis-mode Redis activation service."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import sentry_sdk
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.governance.crisis.templates import (
    CrisisDeploymentRecord,
    CrisisDeploymentScope,
    CrisisTemplate,
)
from app.governance.db.models import CrisisDeploymentRow
from app.governance.crisis.stream import subscribe_crisis_intercept_events
from app.governance.policies.crisis import _crisis_key
from app.services.crisis_events import (
    CrisisEventRecord,
    CrisisEventRepository,
    PostgresCrisisEventRepository,
)

_DEPLOYMENT_NAMESPACE = uuid.UUID("aa89f110-57a2-52a3-b27e-69c35314d9ad")
_logger = get_logger(__name__)
_SentryLevel = Literal["warning", "info"]


class CrisisServiceError(RuntimeError):
    """Raised when a crisis deployment request cannot be completed."""


class CrisisService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        redis_client: Any,
        event_repository: CrisisEventRepository | None = None,
    ) -> None:
        self._session = session
        self._redis = redis_client
        self._event_repository = event_repository or PostgresCrisisEventRepository(
            session
        )

    async def deploy(
        self,
        *,
        tenant_id: str,
        template: CrisisTemplate,
        scope: CrisisDeploymentScope,
        ttl_minutes: int,
        deployed_by: str,
        expected_tenant_id: str,
        dry_run: bool = False,
    ) -> CrisisDeploymentRecord:
        _assert_tenant(tenant_id, expected_tenant_id)
        if ttl_minutes < 0:
            raise CrisisServiceError("ttl_minutes must be non-negative")
        normalized_scope = _normalize_scope(template, scope)
        redis_key = _redis_key(
            tenant_id=tenant_id,
            template=template,
            scope=normalized_scope,
        )
        decision = _decision_for(template)
        now = _utcnow()
        expires_at = (
            now + timedelta(minutes=ttl_minutes)
            if ttl_minutes > 0
            else None
        )
        deployment_id = _deployment_id(
            tenant_id=tenant_id,
            template=template,
            scope=normalized_scope,
        )
        metadata = {
            "redis_key": redis_key,
            "decision": decision,
            "dry_run": dry_run,
        }
        record = CrisisDeploymentRecord(
            deployment_id=str(deployment_id),
            tenant_id=tenant_id,
            template=template,
            scope=normalized_scope,
            ttl_minutes=ttl_minutes,
            policy_id=None,
            deployed_by=deployed_by,
            deployed_at=now,
            expires_at=expires_at,
            status="preview" if dry_run else "active",
            redis_key=redis_key,
            decision=decision,
            metadata=metadata,
        )
        if dry_run:
            return record

        await self._redis.set(
            redis_key,
            json.dumps(
                {
                    "deployment_id": str(deployment_id),
                    "deployed_by": deployed_by,
                    "deployed_at": now.isoformat(),
                },
                sort_keys=True,
            ),
            ex=ttl_minutes * 60 if ttl_minutes > 0 else None,
        )
        row = await self._session.get(CrisisDeploymentRow, deployment_id)
        if row is None:
            row = CrisisDeploymentRow(
                deployment_id=deployment_id,
                tenant_id=tenant_id,
                template=template.value,
                scope_json=normalized_scope.to_dict(),
                ttl_minutes=ttl_minutes,
                policy_id=None,
                deployed_by=deployed_by,
                deployed_at=now,
                expires_at=expires_at,
                status="active",
                metadata_json=metadata,
            )
            self._session.add(row)
        else:
            row.template = template.value
            row.scope_json = normalized_scope.to_dict()
            row.ttl_minutes = ttl_minutes
            row.policy_id = None
            row.deployed_by = deployed_by
            row.deployed_at = now
            row.expires_at = expires_at
            row.status = "active"
            row.metadata_json = metadata
        await self._session.commit()
        await self._write_event(
            _event_record(
                tenant_id=tenant_id,
                deployment_id=str(deployment_id),
                event_kind="deployed",
                template=template.value,
                scope=normalized_scope,
                ttl_minutes=ttl_minutes,
                actor=deployed_by,
                occurred_at=now,
            )
        )
        _capture_crisis_message(
            message=f"CRISIS RULE DEPLOYED: {template.value} on tenant {tenant_id}",
            level="warning",
            extras={
                "deployment_id": str(deployment_id),
                "template": template.value,
                "scope": _scope_dict(normalized_scope),
                "ttl_minutes": ttl_minutes,
                "deployed_by": deployed_by,
                "tenant_id": tenant_id,
            },
        )
        return _record_from_row(row)

    async def deactivate(
        self,
        *,
        deployment_id: str,
        deactivated_by: str,
        tenant_id: str,
        expected_tenant_id: str,
    ) -> CrisisDeploymentRecord:
        _assert_tenant(tenant_id, expected_tenant_id)
        row = await self._load_active(
            deployment_id=deployment_id,
            tenant_id=tenant_id,
        )
        redis_key = _row_redis_key(row)
        await self._redis.delete(redis_key)
        row.status = "deactivated"
        row.metadata_json = {
            **dict(row.metadata_json or {}),
            "deactivated_by": deactivated_by,
            "deactivated_at": _utcnow().isoformat(),
        }
        await self._session.commit()
        await self._write_event(
            _event_record(
                tenant_id=tenant_id,
                deployment_id=str(row.deployment_id),
                event_kind="deactivated",
                template=row.template,
                scope=CrisisDeploymentScope.from_mapping(
                    CrisisTemplate(row.template),
                    row.scope_json or {},
                ),
                ttl_minutes=row.ttl_minutes,
                actor=deactivated_by,
                occurred_at=_utcnow(),
            )
        )
        _capture_crisis_message(
            message=f"Crisis rule deactivated: {row.template} on {tenant_id}",
            level="info",
            extras={
                "deployment_id": str(row.deployment_id),
                "template": row.template,
                "scope": dict(row.scope_json or {}),
                "ttl_minutes": row.ttl_minutes,
                "deactivated_by": deactivated_by,
                "tenant_id": tenant_id,
            },
        )
        return _record_from_row(row)

    async def list_active(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
    ) -> list[CrisisDeploymentRecord]:
        _assert_tenant(tenant_id, expected_tenant_id)
        now = _utcnow()
        result = await self._session.scalars(
            select(CrisisDeploymentRow)
            .where(
                CrisisDeploymentRow.tenant_id == tenant_id,
                CrisisDeploymentRow.status == "active",
                or_(
                    CrisisDeploymentRow.expires_at.is_(None),
                    CrisisDeploymentRow.expires_at > now,
                ),
            )
            .order_by(CrisisDeploymentRow.deployed_at.desc())
        )
        return [_record_from_row(row) for row in result.all()]

    async def expire_due(self, *, limit: int = 100) -> int:
        now = _utcnow()
        result = await self._session.scalars(
            select(CrisisDeploymentRow)
            .where(
                CrisisDeploymentRow.status == "active",
                CrisisDeploymentRow.expires_at.is_not(None),
                CrisisDeploymentRow.expires_at <= now,
            )
            .order_by(CrisisDeploymentRow.expires_at.asc())
            .limit(limit)
        )
        rows = list(result.all())
        for row in rows:
            try:
                await self._redis.delete(_row_redis_key(row))
            except Exception as exc:  # noqa: BLE001 - Redis TTL may already have fired.
                _logger.warning(
                    "crisis_expiry_redis_delete_failed",
                    extra={
                        "deployment_id": str(row.deployment_id),
                        "error": str(exc),
                    },
                )
            row.status = "expired"
            row.metadata_json = {
                **dict(row.metadata_json or {}),
                "expired_at": now.isoformat(),
            }
        if rows:
            await self._session.commit()
            for row in rows:
                await self._write_event(
                    _event_record(
                        tenant_id=row.tenant_id,
                        deployment_id=str(row.deployment_id),
                        event_kind="expired",
                        template=row.template,
                        scope=CrisisDeploymentScope.from_mapping(
                            CrisisTemplate(row.template),
                            row.scope_json or {},
                        ),
                        ttl_minutes=row.ttl_minutes,
                        actor="system",
                        occurred_at=now,
                    ),
                    commit=False,
                )
            await self._session.commit()
            for row in rows:
                _capture_crisis_message(
                    message=f"Crisis rule expired: {row.template} on {row.tenant_id}",
                    level="info",
                    extras={
                        "deployment_id": str(row.deployment_id),
                        "template": row.template,
                        "scope": dict(row.scope_json or {}),
                        "ttl_minutes": row.ttl_minutes,
                        "tenant_id": row.tenant_id,
                    },
                )
        return len(rows)

    async def list_events(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
        limit: int = 100,
        since: datetime | None = None,
    ) -> list[CrisisEventRecord]:
        _assert_tenant(tenant_id, expected_tenant_id)
        return await self._event_repository.list_for_tenant(
            tenant_id=tenant_id,
            expected_tenant_id=expected_tenant_id,
            limit=limit,
            since=since,
        )

    def stream_intercepts(
        self,
        *,
        expected_tenant_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        return subscribe_crisis_intercept_events(
            redis_client=self._redis,
            expected_tenant_id=expected_tenant_id,
        )

    async def _write_event(
        self,
        record: CrisisEventRecord,
        *,
        commit: bool = True,
    ) -> None:
        await self._event_repository.write(record)
        if commit:
            await self._session.commit()

    async def _load_active(
        self,
        *,
        deployment_id: str,
        tenant_id: str,
    ) -> CrisisDeploymentRow:
        try:
            deployment_uuid = uuid.UUID(deployment_id)
        except ValueError as exc:
            raise CrisisServiceError("deployment_id is invalid") from exc
        row = await self._session.get(CrisisDeploymentRow, deployment_uuid)
        if (
            row is None
            or row.tenant_id != tenant_id
            or row.status != "active"
        ):
            raise CrisisServiceError("active crisis deployment not found")
        return row


def _normalize_scope(
    template: CrisisTemplate,
    scope: CrisisDeploymentScope,
) -> CrisisDeploymentScope:
    if scope.template is not template:
        scope = CrisisDeploymentScope(
            template=template,
            sku=scope.sku,
            category=scope.category,
        )
    if template is CrisisTemplate.BLOCK_SKU:
        sku = scope.sku.strip() if scope.sku is not None else ""
        if not sku:
            raise CrisisServiceError("BLOCK_SKU requires scope.sku")
        return CrisisDeploymentScope(template=template, sku=sku)
    if template is CrisisTemplate.FREEZE_CATEGORY:
        category = scope.category.strip() if scope.category is not None else ""
        if not category:
            raise CrisisServiceError("FREEZE_CATEGORY requires scope.category")
        return CrisisDeploymentScope(
            template=template,
            category=category,
        )
    return CrisisDeploymentScope(template=template)


def _redis_key(
    *,
    tenant_id: str,
    template: CrisisTemplate,
    scope: CrisisDeploymentScope,
) -> str:
    if template is CrisisTemplate.BLOCK_SKU:
        return _crisis_key(tenant_id, template.value, scope.sku or "")
    if template is CrisisTemplate.FREEZE_CATEGORY:
        return _crisis_key(tenant_id, template.value, scope.category or "")
    return _crisis_key(tenant_id, template.value)


def _row_redis_key(row: CrisisDeploymentRow) -> str:
    template = CrisisTemplate(row.template)
    scope = CrisisDeploymentScope.from_mapping(template, row.scope_json or {})
    return _redis_key(
        tenant_id=row.tenant_id,
        template=template,
        scope=scope,
    )


def _decision_for(template: CrisisTemplate) -> str:
    if template is CrisisTemplate.HALT_REFUNDS:
        return "require_approval"
    if template is CrisisTemplate.ESCALATE_ALL:
        return "escalate"
    return "deny"


def _deployment_id(
    *,
    tenant_id: str,
    template: CrisisTemplate,
    scope: CrisisDeploymentScope,
) -> uuid.UUID:
    scope_hash = hashlib.sha256(
        json.dumps(scope.to_dict(), sort_keys=True).encode("utf-8")
    ).hexdigest()
    return uuid.uuid5(
        _DEPLOYMENT_NAMESPACE,
        f"{tenant_id}|{template.value}|{scope_hash}",
    )


def _record_from_row(row: CrisisDeploymentRow) -> CrisisDeploymentRecord:
    template = CrisisTemplate(row.template)
    scope = CrisisDeploymentScope.from_mapping(template, row.scope_json or {})
    redis_key = str((row.metadata_json or {}).get("redis_key") or _row_redis_key(row))
    decision = str((row.metadata_json or {}).get("decision") or _decision_for(template))
    return CrisisDeploymentRecord(
        deployment_id=str(row.deployment_id),
        tenant_id=row.tenant_id,
        template=template,
        scope=scope,
        ttl_minutes=row.ttl_minutes,
        policy_id=str(row.policy_id) if row.policy_id is not None else None,
        deployed_by=row.deployed_by,
        deployed_at=row.deployed_at,
        expires_at=row.expires_at,
        status=row.status,
        redis_key=redis_key,
        decision=decision,
        metadata=dict(row.metadata_json or {}),
    )


def _event_record(
    *,
    tenant_id: str,
    deployment_id: str,
    event_kind: str,
    template: str,
    scope: CrisisDeploymentScope,
    ttl_minutes: int,
    actor: str,
    occurred_at: datetime,
) -> CrisisEventRecord:
    return CrisisEventRecord(
        event_id=str(uuid.uuid4()),  # APPROVED_EXCEPTION: immutable audit event id
        tenant_id=tenant_id,
        deployment_id=deployment_id,
        event_kind=event_kind,
        template=template,
        scope_json=_scope_dict(scope),
        ttl_minutes=ttl_minutes,
        actor=actor,
        occurred_at=occurred_at,
        metadata={},
    )


def _scope_dict(scope: CrisisDeploymentScope) -> dict[str, Any]:
    value = asdict(scope)
    template = value.get("template")
    if isinstance(template, CrisisTemplate):
        value["template"] = template.value
    return {str(key): item for key, item in value.items() if item is not None}


def _capture_crisis_message(
    *,
    message: str,
    level: _SentryLevel,
    extras: dict[str, Any],
) -> None:
    try:
        sentry_sdk.capture_message(
            message,
            level=level,
            extras=extras,
        )
    except Exception as exc:  # noqa: BLE001 - Sentry must not block crisis ops.
        _logger.warning(
            "crisis_sentry_notify_failed",
            extra={"error": str(exc)},
        )


def _assert_tenant(tenant_id: str, expected_tenant_id: str) -> None:
    if tenant_id != expected_tenant_id:
        raise CrisisServiceError("tenant_id does not match expected_tenant_id")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


__all__ = ["CrisisService", "CrisisServiceError"]
