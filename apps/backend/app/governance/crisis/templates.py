"""Crisis-mode template records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping


class CrisisTemplate(StrEnum):
    BLOCK_SKU = "block_sku"
    HALT_REFUNDS = "halt_refunds"
    ESCALATE_ALL = "escalate_all"
    FREEZE_CATEGORY = "freeze_category"


@dataclass(frozen=True, slots=True)
class CrisisDeploymentScope:
    template: CrisisTemplate
    sku: str | None = None
    category: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"template": self.template.value}
        if self.sku is not None:
            payload["sku"] = self.sku
        if self.category is not None:
            payload["category"] = self.category
        return payload

    @classmethod
    def from_mapping(
        cls,
        template: CrisisTemplate,
        scope: Mapping[str, Any],
    ) -> "CrisisDeploymentScope":
        sku = scope.get("sku")
        category = scope.get("category")
        return cls(
            template=template,
            sku=sku.strip() if isinstance(sku, str) and sku.strip() else None,
            category=(
                category.strip()
                if isinstance(category, str) and category.strip()
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class CrisisDeploymentRecord:
    deployment_id: str
    tenant_id: str
    template: CrisisTemplate
    scope: CrisisDeploymentScope
    ttl_minutes: int
    policy_id: str | None
    deployed_by: str
    deployed_at: datetime
    expires_at: datetime | None
    status: str
    redis_key: str
    decision: str
    metadata: Mapping[str, Any]


__all__ = [
    "CrisisDeploymentRecord",
    "CrisisDeploymentScope",
    "CrisisTemplate",
]
