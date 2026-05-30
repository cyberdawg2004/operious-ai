"""SKU extraction from action approvals linked to defect clusters."""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Mapping
from typing import Any, cast

from sqlalchemy import bindparam, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution import PostgresExecutionPersistence
from app.execution.identity import as_execution_id
from app.execution.persistence import ExecutionPersistenceProtocol
from app.runtime.db.models import DefectClusterRow

_ACTION_APPROVAL_SKU_SQL = (
    text(
        """
        SELECT payload_json
        FROM public.action_approval_records
        WHERE tenant_id = :tenant_id
          AND CAST(session_id AS text) IN :session_ids
        """
    )
    .bindparams(bindparam("session_ids", expanding=True))
)


class SKUExtractionService:
    """Extract the dominant product SKU from cluster-linked action payloads."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        execution_repo: ExecutionPersistenceProtocol | None = None,
    ) -> None:
        self._session = session
        self._execution_repo = execution_repo or PostgresExecutionPersistence(session)

    async def extract_sku_for_cluster(
        self,
        *,
        execution_ids: tuple[str, ...],
        tenant_id: str,
        expected_tenant_id: str,
    ) -> str | None:
        """Return the most common product_sku from linked approvals."""

        if tenant_id != expected_tenant_id:
            raise ValueError("tenant_id does not match expected_tenant_id")
        session_ids = await self._session_ids_for_executions(
            execution_ids=execution_ids,
            expected_tenant_id=expected_tenant_id,
        )
        if not session_ids:
            return None

        rows = (
            await self._session.execute(
                _ACTION_APPROVAL_SKU_SQL,
                {
                    "tenant_id": tenant_id,
                    "session_ids": tuple(sorted(session_ids)),
                },
            )
        ).mappings()
        skus: list[str] = []
        for row in rows:
            sku = _product_sku(_payload(row.get("payload_json")))
            if sku is not None:
                skus.append(sku)
        if not skus:
            return None
        [(sku, _count)] = Counter(skus).most_common(1)
        return sku

    async def update_cluster_sku_hint(
        self,
        *,
        cluster_id: str,
        sku: str,
        tenant_id: str,
        expected_tenant_id: str,
    ) -> bool:
        if tenant_id != expected_tenant_id:
            raise ValueError("tenant_id does not match expected_tenant_id")
        stmt = (
            update(DefectClusterRow)
            .where(
                DefectClusterRow.cluster_id == uuid.UUID(cluster_id),
                DefectClusterRow.tenant_id == tenant_id,
            )
            .values(sku_hint=sku)
        )
        result = await self._session.execute(stmt)
        return bool(getattr(result, "rowcount", 0))

    async def _session_ids_for_executions(
        self,
        *,
        execution_ids: tuple[str, ...],
        expected_tenant_id: str,
    ) -> set[str]:
        session_ids: set[str] = set()
        for execution_id in execution_ids:
            try:
                parsed = as_execution_id(execution_id)
            except ValueError:
                continue
            execution = await self._execution_repo.get_execution(
                parsed,
                expected_tenant_id=expected_tenant_id,
            )
            if execution is not None and execution.session_id:
                session_ids.add(str(execution.session_id))
        return session_ids


def _payload(value: object) -> Mapping[str, Any]:
    return cast(Mapping[str, Any], value) if isinstance(value, Mapping) else {}


def _product_sku(payload: Mapping[str, Any]) -> str | None:
    value = payload.get("product_sku")
    return value.strip() if isinstance(value, str) and value.strip() else None


__all__ = ["SKUExtractionService"]
