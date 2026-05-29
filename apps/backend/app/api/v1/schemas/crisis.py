"""Transport contracts for crisis-mode governance."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.governance.crisis import (
    CrisisDeploymentRecord,
    CrisisDeploymentScope,
    CrisisTemplate,
)
from app.services.crisis_events import CrisisEventRecord


class CrisisDeployRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    template: CrisisTemplate
    scope: dict[str, Any] = Field(default_factory=dict)
    ttl_minutes: int = Field(default=30, ge=0)
    dry_run: bool = False


class CrisisDeploymentResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    deployment_id: str
    tenant_id: str
    template: CrisisTemplate
    scope: dict[str, Any]
    ttl_minutes: int
    policy_id: str | None
    deployed_by: str
    deployed_at: str
    expires_at: str | None
    status: str
    redis_key: str
    decision: str
    metadata: dict[str, Any]

    @classmethod
    def from_record(
        cls,
        record: CrisisDeploymentRecord,
    ) -> "CrisisDeploymentResponse":
        return cls(
            deployment_id=record.deployment_id,
            tenant_id=record.tenant_id,
            template=record.template,
            scope=record.scope.to_dict(),
            ttl_minutes=record.ttl_minutes,
            policy_id=record.policy_id,
            deployed_by=record.deployed_by,
            deployed_at=record.deployed_at.isoformat(),
            expires_at=(
                record.expires_at.isoformat()
                if record.expires_at is not None
                else None
            ),
            status=record.status,
            redis_key=record.redis_key,
            decision=record.decision,
            metadata=dict(record.metadata),
        )


class CrisisDeploymentListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[CrisisDeploymentResponse]


class CrisisEventResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    deployment_id: str
    event_kind: str
    template: str
    scope: dict[str, Any]
    actor: str
    occurred_at: str
    ttl_minutes: int

    @classmethod
    def from_record(cls, record: CrisisEventRecord) -> "CrisisEventResponse":
        return cls(
            event_id=record.event_id,
            deployment_id=record.deployment_id,
            event_kind=record.event_kind,
            template=record.template,
            scope=dict(record.scope_json),
            actor=record.actor,
            occurred_at=record.occurred_at.isoformat(),
            ttl_minutes=record.ttl_minutes,
        )


class CrisisEventListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[CrisisEventResponse]


def deployment_scope_from_request(
    template: CrisisTemplate,
    scope: dict[str, Any],
) -> CrisisDeploymentScope:
    return CrisisDeploymentScope.from_mapping(template, scope)


__all__ = [
    "CrisisDeployRequest",
    "CrisisDeploymentListResponse",
    "CrisisDeploymentResponse",
    "CrisisEventListResponse",
    "CrisisEventResponse",
    "deployment_scope_from_request",
]
