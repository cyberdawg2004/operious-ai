from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_owner_session_factory
from app.tenant.credentials import TenantCredentialEncryptor
from app.tenant.enums import TenantChannelStatus, TenantChannelType
from app.tenant.persistence import PostgresTenantConfigurationRepository
from app.tenant.runtime import TenantConfigurationRuntime
from tests.load.conftest import (
    committed_burst_seed,
    isolate_global_quota_runtime,
    suppress_semantic_validation,
    suppress_supervisor_enqueue,
)

__all__ = [
    "committed_burst_seed",
    "isolate_global_quota_runtime",
    "suppress_semantic_validation",
    "suppress_supervisor_enqueue",
]

CHAOS_TENANT_CREDENTIAL_MASTER_KEY = "chaos-webhook-master-key-32-bytes-min"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "chaos: mark chaos/failure tests")


@pytest_asyncio.fixture
async def chaos_email_channel_seed(
    committed_burst_seed,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[Callable[[str, str, str], object]]:
    monkeypatch.setenv(
        "TENANT_CREDENTIAL_MASTER_KEY",
        CHAOS_TENANT_CREDENTIAL_MASTER_KEY,
    )
    get_settings.cache_clear()
    seeded_tenants: set[str] = set()

    async def seed(
        tenant_id: str,
        routing_address: str,
        webhook_secret: str,
    ) -> None:
        await committed_burst_seed["seed_tenant"](tenant_id)
        async with get_owner_session_factory()() as session:
            runtime = TenantConfigurationRuntime(
                repository=PostgresTenantConfigurationRepository(session),
                credential_encryptor=TenantCredentialEncryptor(
                    platform_master_key=CHAOS_TENANT_CREDENTIAL_MASTER_KEY,
                ),
            )
            await runtime.configure_channel(
                tenant_id=tenant_id,
                channel_type=TenantChannelType.EMAIL,
                routing_address=routing_address,
                credentials={"token": "chaos-email-token"},
                webhook_secret=webhook_secret,
                status=TenantChannelStatus.ACTIVE,
            )
            await session.commit()
        seeded_tenants.add(tenant_id)

    try:
        yield seed
    finally:
        async with get_owner_session_factory()() as session:
            for tenant_id in seeded_tenants:
                await session.execute(
                    text(
                        """
                        DELETE FROM webhook_nonce_records
                        WHERE tenant_id = :tenant_id
                        """
                    ),
                    {"tenant_id": tenant_id},
                )
                await session.execute(
                    text(
                        """
                        DELETE FROM tenant_channel_configurations
                        WHERE tenant_id = :tenant_id
                        """
                    ),
                    {"tenant_id": tenant_id},
                )
            await session.commit()
