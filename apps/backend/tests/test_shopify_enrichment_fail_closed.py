"""Shopify enrichment must fail closed in production (#73).

Without a live Shopify channel, production must leave a cluster un-enriched
rather than fabricate deterministic fixture product/inventory data. These are
hermetic (no DB): they exercise the client-selection branch and the effective
setting directly.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from app.boundary.shopify import DeterministicStubShopifyClient
from app.core.config import Settings
from app.services.shopify_enrichment_service import ShopifyEnrichmentService
from app.tenant.persistence import (
    TenantChannelConfigurationPage,
    TenantChannelConfigurationQuery,
)


class _RaisingTenantRuntime:
    """Stands in for a tenant with no usable live Shopify channel."""

    async def list_channels(
        self,
        *,
        tenant_id: str,
        query: TenantChannelConfigurationQuery,
    ) -> TenantChannelConfigurationPage:
        raise ValueError("no active shopify channel configured")

    async def load_channel_credentials(
        self,
        *,
        tenant_id: str,
        channel_type: Any,
    ) -> dict[str, Any]:
        raise AssertionError("must not be reached without a channel")


def _service(*, allow_stub: bool) -> ShopifyEnrichmentService:
    return ShopifyEnrichmentService(
        session=cast(Any, object()),
        tenant_runtime=_RaisingTenantRuntime(),
        allow_stub_enrichment=allow_stub,
    )


@pytest.mark.asyncio
async def test_no_live_channel_fails_closed_when_stubs_disabled() -> None:
    service = _service(allow_stub=False)
    with pytest.raises(Exception):  # noqa: B017 - re-raised live-lookup failure
        await service._client_for_tenant(tenant_id="tenant-1")  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_no_live_channel_uses_stub_when_explicitly_allowed() -> None:
    service = _service(allow_stub=True)
    client, source = await service._client_for_tenant(  # type: ignore[attr-defined]
        tenant_id="tenant-1"
    )
    assert isinstance(client, DeterministicStubShopifyClient)
    assert source == "stub"


def test_effective_setting_is_fail_closed_in_production() -> None:
    assert (
        Settings(ENVIRONMENT="production").allow_stub_shopify_enrichment_effective
        is False
    )
    # Even an explicit opt-in cannot enable fixtures in production.
    assert (
        Settings(
            ENVIRONMENT="production", ALLOW_STUB_SHOPIFY_ENRICHMENT=True
        ).allow_stub_shopify_enrichment_effective
        is False
    )
    assert (
        Settings(ENVIRONMENT="test").allow_stub_shopify_enrichment_effective is True
    )
    assert (
        Settings(
            ENVIRONMENT="local", ALLOW_STUB_SHOPIFY_ENRICHMENT=False
        ).allow_stub_shopify_enrichment_effective
        is False
    )
