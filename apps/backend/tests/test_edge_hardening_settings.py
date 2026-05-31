"""Spec 1b — edge-hardening settings (rate limits, base URL, voice caps, coarsening)."""

from __future__ import annotations

from app.core.config import Settings


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {"ENVIRONMENT": "test"}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_rate_limit_defaults() -> None:
    s = _settings()
    assert s.RATE_LIMIT_ENABLED is True
    assert s.RATE_LIMIT_IP_PER_MINUTE == 120
    assert s.RATE_LIMIT_TENANT_PER_MINUTE == 600
    assert s.RATE_LIMIT_PRINCIPAL_PER_MINUTE == 300
    assert s.RATE_LIMIT_WINDOW_SECONDS == 60


def test_rate_limit_exempt_suffixes_default() -> None:
    s = _settings()
    assert s.rate_limit_exempt_suffixes == ("/health", "/live", "/ready")


def test_webhook_and_voice_cap_defaults() -> None:
    s = _settings()
    assert s.PUBLIC_BASE_URL == ""
    assert s.WEBHOOK_TRUST_URL_HEADER is False
    assert s.VOICE_MAX_CALL_SECONDS == 3600
    assert s.VOICE_IDLE_TIMEOUT_SECONDS == 30
    assert s.VOICE_MAX_FRAMES_PER_SECOND == 100
    assert s.COARSE_AUTH_ERRORS is False


def test_coarse_auth_errors_default_true_in_production() -> None:
    assert _settings(ENVIRONMENT="production").coarse_auth_errors_effective is True


def test_coarse_auth_errors_off_in_non_production() -> None:
    assert _settings(ENVIRONMENT="test").coarse_auth_errors_effective is False


def test_coarse_auth_errors_explicit_override_wins() -> None:
    assert _settings(ENVIRONMENT="test", COARSE_AUTH_ERRORS=True).coarse_auth_errors_effective is True


def test_public_base_url_strips_trailing_slash() -> None:
    s = _settings(PUBLIC_BASE_URL="https://api.example.com/")
    assert s.public_base_url_normalized == "https://api.example.com"
