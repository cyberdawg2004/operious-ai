"""Receipt-only service for tenant work-order fulfillment callbacks."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools.connectors.config import (
    ConnectorConfigRecord,
    ConnectorConfigRepository,
)
from app.boundary.adapters.builtin.work_order_fulfillment import (
    WorkOrderFulfillmentStatusAdapter,
)
from app.boundary.contracts import BoundaryIngressRequest
from app.boundary.enums import (
    BoundaryNormalizationStatus,
    BoundarySourceType,
)
from app.boundary.ingress import BoundaryIngressRuntime
from app.boundary.models import BoundarySource, IngressPayload
from app.boundary.persistence import BoundaryPersistenceProtocol
from app.boundary.registry import BoundaryAdapterRegistry
from app.identity import AuthorityContext

_SIGNATURE_HEADER = "x-operious-signature"
_CONNECTOR_TYPE_REPAIR_DISPATCH = "repair.dispatch"


class WorkOrderFulfillmentReceiptError(RuntimeError):
    """The boundary receipt could not be recorded."""


@dataclass(frozen=True, slots=True)
class WorkOrderFulfillmentReceiptResult:
    """Transport-neutral result of recording a fulfillment callback."""

    ingress_id: str
    event_id: str | None
    normalization_status: str
    message_type: str
    replay_disposition: str
    provider_work_order_id: str | None


class WorkOrderFulfillmentReceiptService:
    """Record inbound fulfillment status updates without orchestration."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        boundary_repository: BoundaryPersistenceProtocol,
        connector_config_repository: ConnectorConfigRepository | None = None,
    ) -> None:
        self._session = session
        self._boundary_repository = boundary_repository
        self._connector_config_repository = connector_config_repository

    async def record_callback(
        self,
        *,
        expected_tenant_id: str,
        payload: Mapping[str, Any],
        headers: Mapping[str, str],
        raw_body: bytes | None = None,
        request_path: str,
        source_id: str = "work-order-fulfillment",
    ) -> WorkOrderFulfillmentReceiptResult:
        """Persist the inbound status update and stop."""

        connector_config = await self._load_connector_config(expected_tenant_id)
        verify_callback_hmac(
            connector_config=connector_config,
            headers=headers,
            raw_body=raw_body,
        )

        runtime = BoundaryIngressRuntime(
            adapters=BoundaryAdapterRegistry(
                (WorkOrderFulfillmentStatusAdapter(),)
            ),
            persistence=self._boundary_repository,
        )
        request_id = _request_id(payload, expected_tenant_id)
        envelope = await runtime.ingest(
            BoundaryIngressRequest(
                source=BoundarySource(
                    source_type=BoundarySourceType.GENERIC,
                    source_id=source_id,
                    tenant_id=expected_tenant_id,
                ),
                adapter_name=WorkOrderFulfillmentStatusAdapter.DEFAULT_NAME,
                payload=IngressPayload(
                    body=dict(payload),
                    content_type="application/json",
                    headers=dict(headers),
                    request_path=request_path,
                ),
                correlation_id=_text(payload.get("provider_work_order_id")),
                request_id=request_id,
                authority=AuthorityContext.from_raw(
                    tenant_id=expected_tenant_id
                ),
                metadata={
                    "event_kind": "work_order_fulfillment",
                    "record_only": True,
                },
            )
        )
        if envelope.error is not None:
            await self._session.rollback()
            raise WorkOrderFulfillmentReceiptError(
                "work-order fulfillment receipt persistence failed"
            ) from envelope.error
        result = envelope.result
        if result is None:
            await self._session.rollback()
            raise WorkOrderFulfillmentReceiptError(
                "work-order fulfillment receipt produced no result"
            )
        if result.normalization.status is (
            BoundaryNormalizationStatus.MALFORMED
        ):
            await self._session.commit()
            raise WorkOrderFulfillmentReceiptError(
                result.normalization.error
                or "malformed work-order fulfillment callback"
            )
        await self._session.commit()
        return WorkOrderFulfillmentReceiptResult(
            ingress_id=str(result.ingress_id),
            event_id=(
                str(result.event_id)
                if result.event_id is not None
                else None
            ),
            normalization_status=result.normalization.status.value,
            message_type=result.normalization.message_type.value,
            replay_disposition=result.replay_disposition.value,
            provider_work_order_id=(
                result.normalization.external_conversation_id
            ),
        )

    async def _load_connector_config(
        self,
        tenant_id: str,
    ) -> ConnectorConfigRecord | None:
        if self._connector_config_repository is None:
            return None
        return await self._connector_config_repository.get_active_config(
            tenant_id=tenant_id,
            tool_name=_CONNECTOR_TYPE_REPAIR_DISPATCH,
            expected_tenant_id=tenant_id,
        )


def verify_callback_hmac(
    *,
    connector_config: ConnectorConfigRecord | None,
    headers: Mapping[str, str],
    raw_body: bytes | None,
) -> None:
    """Raise WorkOrderFulfillmentReceiptError if HMAC check fails.

    Only runs when ``connector_config`` is not None and has a non-None
    ``callback_hmac_secret``.  If both conditions hold, the request must
    carry a valid ``X-Operious-Signature: sha256=<hex>`` header.
    """
    if connector_config is None or connector_config.callback_hmac_secret is None:
        return

    secret = connector_config.callback_hmac_secret
    supplied_header = _header_value(headers, _SIGNATURE_HEADER)
    if not supplied_header:
        raise WorkOrderFulfillmentReceiptError("invalid callback signature")

    body_bytes = raw_body or b""
    expected_hex = hmac.new(
        secret.encode("utf-8"),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()

    supplied = supplied_header.strip()
    if supplied.startswith("sha256="):
        supplied = supplied[len("sha256="):]

    if not hmac.compare_digest(supplied.lower(), expected_hex.lower()):
        raise WorkOrderFulfillmentReceiptError("invalid callback signature")


def _header_value(headers: Mapping[str, str], name: str) -> str | None:
    """Case-insensitive header lookup."""
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


def _request_id(payload: Mapping[str, Any], tenant_id: str) -> str:
    callback_id = _text(payload.get("callback_id")) or _text(
        payload.get("event_id")
    )
    if callback_id is not None:
        return callback_id
    seed = "|".join(
        (
            tenant_id,
            _text(payload.get("provider_work_order_id")) or "missing-provider",
            _text(payload.get("status")) or "missing-status",
        )
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"work-order-fulfillment:{seed}"))


def _text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = [
    "WorkOrderFulfillmentReceiptError",
    "WorkOrderFulfillmentReceiptResult",
    "WorkOrderFulfillmentReceiptService",
    "verify_callback_hmac",
]
