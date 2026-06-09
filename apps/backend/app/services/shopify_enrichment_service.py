"""Shopify enrichment for detected defect clusters."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.boundary.shopify import (
    DeterministicStubShopifyClient,
    ShopifyAPIClient,
    ShopifyEnrichmentResult,
    ShopifyOrder,
    ShopifyProduct,
    ShopifyProductVariant,
)
from app.core.config import get_settings
from app.runtime.db.models import DefectClusterRow
from app.tenant.credentials import TenantCredentialEncryptor
from app.tenant.enums import TenantChannelStatus, TenantChannelType
from app.tenant.persistence import (
    PostgresTenantConfigurationRepository,
    TenantChannelConfigurationPage,
    TenantChannelConfigurationQuery,
)
from app.tenant.runtime import TenantConfigurationRuntime

logger = logging.getLogger(__name__)


class ShopifyClientProtocol(Protocol):
    async def get_product_by_sku(self, sku: str) -> ShopifyProduct | None: ...

    async def get_recent_orders_by_sku(
        self,
        sku: str,
        limit: int = 10,
    ) -> list[ShopifyOrder]: ...


class TenantCredentialLoaderProtocol(Protocol):
    async def list_channels(
        self,
        *,
        tenant_id: str,
        query: TenantChannelConfigurationQuery,
    ) -> TenantChannelConfigurationPage: ...

    async def load_channel_credentials(
        self,
        *,
        tenant_id: str,
        channel_type: TenantChannelType,
    ) -> dict[str, Any]: ...


class ShopifyEnrichmentService:
    """Attach read-only Shopify product/order context to a cluster."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        tenant_runtime: TenantCredentialLoaderProtocol | None = None,
        client: ShopifyClientProtocol | None = None,
        now: Callable[[], datetime] | None = None,
        allow_stub_enrichment: bool | None = None,
    ) -> None:
        self._session = session
        self._tenant_runtime = tenant_runtime
        self._client = client
        self._now = now or _utcnow
        # Fail-closed in production: fixture data must never masquerade as
        # real Shopify product/inventory context (#73).
        self._allow_stub_enrichment = (
            allow_stub_enrichment
            if allow_stub_enrichment is not None
            else get_settings().allow_stub_shopify_enrichment_effective
        )

    async def enrich_cluster(
        self,
        *,
        cluster_id: str,
        sku_hint: str | None,
        tenant_id: str,
        expected_tenant_id: str,
    ) -> bool:
        if tenant_id != expected_tenant_id:
            raise ValueError("tenant_id does not match expected_tenant_id")
        if sku_hint is None or not sku_hint.strip():
            return False
        try:
            cluster = await self._session.get(DefectClusterRow, uuid.UUID(cluster_id))
            if cluster is None or cluster.tenant_id != tenant_id:
                return False

            client, source = await self._client_for_tenant(tenant_id=tenant_id)
            sku = sku_hint.strip()
            product = await client.get_product_by_sku(sku)
            orders = tuple(await client.get_recent_orders_by_sku(sku, limit=10))
            result = ShopifyEnrichmentResult(
                sku=sku,
                product=product,
                recent_orders=orders,
                batch_hint=None,
                enrichment_source=source,
            )
            metadata = dict(cluster.metadata_json or {})
            metadata["shopify_enrichment"] = _enrichment_payload(
                result,
                enriched_at=self._now(),
            )
            cluster.metadata_json = metadata
            await self._session.flush()
            return True
        except Exception as exc:  # noqa: BLE001 - enrichment is fail-open.
            logger.warning(
                "shopify_enrichment_failed",
                extra={
                    "tenant_id": tenant_id,
                    "cluster_id": cluster_id,
                    "error_class": exc.__class__.__name__,
                },
            )
            return False

    async def _client_for_tenant(
        self,
        *,
        tenant_id: str,
    ) -> tuple[ShopifyClientProtocol, str]:
        if self._client is not None:
            source = (
                "stub"
                if isinstance(self._client, DeterministicStubShopifyClient)
                else "live"
            )
            return self._client, source
        try:
            tenant_runtime = self._tenant_runtime or _build_tenant_runtime(self._session)
            page = await tenant_runtime.list_channels(
                tenant_id=tenant_id,
                query=TenantChannelConfigurationQuery(
                    channel_type=TenantChannelType.SHOPIFY,
                    status=TenantChannelStatus.ACTIVE,
                    limit=1,
                ),
            )
            if not page.items:
                raise ValueError("no active shopify channel configured")
            record = page.items[0]
            credentials = await tenant_runtime.load_channel_credentials(
                tenant_id=tenant_id,
                channel_type=TenantChannelType.SHOPIFY,
            )
            shop_domain = _shop_domain(
                routing_address=record.routing_address,
                credentials=credentials,
            )
            access_token = _required_credential(credentials, "access_token")
            return (
                ShopifyAPIClient(
                    shop_domain=shop_domain,
                    access_token=access_token,
                ),
                "live",
            )
        except Exception:  # noqa: BLE001 - no live client resolved.
            if not self._allow_stub_enrichment:
                # Fail closed: never fabricate Shopify context in production.
                # enrich_cluster catches this and leaves the cluster
                # un-enriched (returns False) rather than seeding fixtures.
                raise
            return DeterministicStubShopifyClient(), "stub"


def _build_tenant_runtime(session: AsyncSession) -> TenantConfigurationRuntime:
    key = get_settings().TENANT_CREDENTIAL_MASTER_KEY
    if not key.strip():
        raise RuntimeError("tenant credential master key is required")
    return TenantConfigurationRuntime(
        repository=PostgresTenantConfigurationRepository(session),
        credential_encryptor=TenantCredentialEncryptor(platform_master_key=key),
    )


def _required_credential(credentials: dict[str, Any], key: str) -> str:
    value = credentials.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"shopify credential {key} is required")
    return value.strip()


def _shop_domain(
    *,
    routing_address: str,
    credentials: dict[str, Any],
) -> str:
    configured = credentials.get("shop_domain")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    if routing_address.strip():
        return routing_address.strip()
    raise ValueError("shopify shop domain is required")


def _enrichment_payload(
    result: ShopifyEnrichmentResult,
    *,
    enriched_at: datetime,
) -> dict[str, Any]:
    orders = [_order_payload(order) for order in result.recent_orders]
    variants = (
        [_variant_payload(variant) for variant in result.product.variants]
        if result.product is not None
        else []
    )
    return {
        "sku": result.sku,
        "product": (
            _product_payload(result.product)
            if result.product is not None
            else None
        ),
        "recent_orders": orders,
        "batch_number": result.batch_hint,
        "shipment_dates": [order["created_at"] for order in orders],
        "variant_info": variants,
        "enrichment_source": result.enrichment_source,
        "enriched_at": enriched_at.isoformat(),
    }


def _product_payload(product: ShopifyProduct) -> dict[str, Any]:
    return {
        "product_id": product.product_id,
        "title": product.title,
        "vendor": product.vendor,
        "product_type": product.product_type,
        "variants": [_variant_payload(variant) for variant in product.variants],
        "created_at": product.created_at,
        "updated_at": product.updated_at,
    }


def _variant_payload(variant: ShopifyProductVariant) -> dict[str, Any]:
    return {
        "variant_id": variant.variant_id,
        "title": variant.title,
        "sku": variant.sku,
        "inventory_quantity": variant.inventory_quantity,
        "created_at": variant.created_at,
        "updated_at": variant.updated_at,
    }


def _order_payload(order: ShopifyOrder) -> dict[str, Any]:
    return {
        "order_id": order.order_id,
        "order_number": order.order_number,
        "created_at": order.created_at,
        "fulfillment_status": order.fulfillment_status,
        "line_item_skus": list(order.line_item_skus),
    }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


__all__ = ["ShopifyEnrichmentService"]
