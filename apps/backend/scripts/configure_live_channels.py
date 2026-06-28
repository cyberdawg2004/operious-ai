"""Configure live demo channel credentials from environment variables.

This script is intended to run inside the deployed backend environment so it can
reuse the production database URL and tenant credential master key. It never
prints credential values.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings
from app.db.session import dispose_engine, get_session_factory
from app.db.tenant_context import set_current_tenant
from app.tenant.credentials import build_tenant_credential_encryptor_from_settings
from app.tenant.enums import TenantChannelStatus, TenantChannelType
from app.tenant.persistence.postgres import PostgresTenantConfigurationRepository
from app.tenant.runtime import TenantConfigurationRuntime

DEFAULT_TENANT_ID = "anker-pilot"


@dataclass(frozen=True, slots=True)
class ChannelResult:
    channel: str
    routing_address: str
    status: str
    configured: bool


async def main() -> int:
    tenant_id = os.environ.get("LIVE_CHANNEL_TENANT_ID", DEFAULT_TENANT_ID).strip()
    if not tenant_id:
        raise RuntimeError("LIVE_CHANNEL_TENANT_ID must not be empty")

    set_current_tenant(tenant_id)
    settings = get_settings()
    session_factory = get_session_factory()
    async with session_factory() as session:
        runtime = TenantConfigurationRuntime(
            repository=PostgresTenantConfigurationRepository(session),
            credential_encryptor=build_tenant_credential_encryptor_from_settings(
                settings
            ),
        )
        results: list[ChannelResult] = []
        whatsapp = _whatsapp_config()
        if whatsapp is not None:
            record = await runtime.configure_channel(
                tenant_id=tenant_id,
                channel_type=TenantChannelType.WHATSAPP,
                routing_address=whatsapp["phone_number_id"],
                credentials=whatsapp,
                webhook_secret=_required_env("LIVE_WHATSAPP_APP_SECRET"),
                status=TenantChannelStatus.ACTIVE,
            )
            results.append(
                ChannelResult(
                    channel=record.channel_type.value,
                    routing_address=record.routing_address,
                    status=record.status.value,
                    configured=True,
                )
            )
        email = _email_config()
        if email is not None:
            record = await runtime.configure_channel(
                tenant_id=tenant_id,
                channel_type=TenantChannelType.EMAIL,
                routing_address=email["source_email_address"],
                credentials=email,
                webhook_secret=_required_env("LIVE_SES_TOPIC_ARN"),
                status=TenantChannelStatus.ACTIVE,
            )
            results.append(
                ChannelResult(
                    channel=record.channel_type.value,
                    routing_address=record.routing_address,
                    status=record.status.value,
                    configured=True,
                )
            )
        slack = _slack_config()
        if slack is not None:
            record = await runtime.configure_channel(
                tenant_id=tenant_id,
                channel_type=TenantChannelType.SLACK,
                routing_address="operator-alerts",
                credentials=slack,
                webhook_secret="",
                status=TenantChannelStatus.ACTIVE,
            )
            results.append(
                ChannelResult(
                    channel=record.channel_type.value,
                    routing_address=record.routing_address,
                    status=record.status.value,
                    configured=True,
                )
            )
        await session.commit()

    if not results:
        print("No channel env vars present; nothing configured.")
    for result in results:
        print(
            f"configured channel={result.channel} "
            f"routing_address={result.routing_address} status={result.status}"
        )
    await dispose_engine()
    return 0


def _whatsapp_config() -> dict[str, Any] | None:
    if not _env_present("LIVE_WHATSAPP_PHONE_NUMBER_ID"):
        return None
    phone_number_id = _required_env("LIVE_WHATSAPP_PHONE_NUMBER_ID")
    return {
        "provider": "meta_whatsapp_cloud_api",
        "phone_number_id": phone_number_id,
        "access_token": _required_env("LIVE_WHATSAPP_ACCESS_TOKEN"),
        "graph_api_version": os.environ.get(
            "LIVE_WHATSAPP_GRAPH_API_VERSION", "v25.0"
        ).strip(),
        "webhook_verify_token": _required_env("LIVE_WHATSAPP_VERIFY_TOKEN"),
    }


def _email_config() -> dict[str, Any] | None:
    if not _env_present("LIVE_SES_SOURCE_EMAIL_ADDRESS"):
        return None
    return {
        "provider": "aws_ses",
        "source_email_address": _required_env("LIVE_SES_SOURCE_EMAIL_ADDRESS"),
        "access_key_id": _required_env("LIVE_SES_ACCESS_KEY_ID"),
        "secret_access_key": _required_env("LIVE_SES_SECRET_ACCESS_KEY"),
        "region": _required_env("LIVE_SES_REGION"),
        "configuration_set_name": _optional_env("LIVE_SES_CONFIGURATION_SET_NAME"),
        "endpoint_url": _optional_env("LIVE_SES_ENDPOINT_URL"),
    }


def _slack_config() -> dict[str, Any] | None:
    if not _env_present("LIVE_SLACK_OPERATOR_WEBHOOK_URL"):
        return None
    return {
        "webhook_url": _required_env("LIVE_SLACK_OPERATOR_WEBHOOK_URL"),
    }


def _env_present(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _optional_env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
