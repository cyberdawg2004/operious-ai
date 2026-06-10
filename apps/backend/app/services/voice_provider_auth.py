"""Voice provider credential lookup for signed media handshakes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.tenant.credentials import build_tenant_credential_encryptor_from_settings
from app.tenant.enums import TenantChannelType
from app.tenant.exceptions import TenantConfigurationError
from app.tenant.persistence import PostgresTenantConfigurationRepository
from app.tenant.runtime import TenantConfigurationRuntime

VoiceProviderAuthTokenLoader = Callable[[str], Awaitable[str | None]]


def get_voice_provider_auth_token_loader() -> VoiceProviderAuthTokenLoader:
    async def load_auth_token(tenant_id: str) -> str | None:
        settings = get_settings()
        try:
            credential_codec = build_tenant_credential_encryptor_from_settings(
                settings
            )
            session_factory = get_session_factory()
            async with session_factory() as session:
                runtime = TenantConfigurationRuntime(
                    repository=PostgresTenantConfigurationRepository(session),
                    credential_encryptor=credential_codec,
                )
                credentials = await runtime.load_channel_credentials(
                    tenant_id=tenant_id,
                    channel_type=TenantChannelType.VOICE,
                )
        except TenantConfigurationError:
            return None
        return voice_provider_auth_token(credentials)

    return load_auth_token


def voice_provider_auth_token(credentials: Mapping[str, Any]) -> str | None:
    for key in ("auth_token", "twilio_auth_token", "provider_auth_token"):
        value = credentials.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


__all__ = [
    "VoiceProviderAuthTokenLoader",
    "get_voice_provider_auth_token_loader",
    "voice_provider_auth_token",
]
