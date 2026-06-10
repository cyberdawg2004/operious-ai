"""Spec 1b — production-readiness gates for webhook signature URL (#23)."""

from __future__ import annotations

from app.core.config import Settings
from app.core.production_readiness import collect_production_problems


def _prod(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "ENVIRONMENT": "production",
        "TENANT_CREDENTIAL_MASTER_KEY": "k" * 32,
        "CREDENTIAL_KMS_BACKEND": "gcp",
        "OPERIOUS_KMS_KEY_RESOURCE": (
            "projects/operious-kms/locations/global/keyRings/operious/"
            "cryptoKeys/tenant-credentials"
        ),
        "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/operious-kms.json",
        "AUDIT_EXPORT_HMAC_SECRET": "s" * 32,
        "ANTHROPIC_API_KEY": "a" * 8,
        "TRANSLATION_PROVIDER": "anthropic",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_trust_url_header_rejected_in_production() -> None:
    problems = collect_production_problems(
        _prod(WEBHOOK_TRUST_URL_HEADER=True, PUBLIC_BASE_URL="https://api.operious.com")
    )
    assert any("WEBHOOK_TRUST_URL_HEADER" in p for p in problems)


def test_public_base_url_required_when_not_trusting_header() -> None:
    problems = collect_production_problems(
        _prod(PUBLIC_BASE_URL="", WEBHOOK_TRUST_URL_HEADER=False)
    )
    assert any("PUBLIC_BASE_URL" in p for p in problems)


def test_public_base_url_set_is_clean() -> None:
    problems = collect_production_problems(
        _prod(PUBLIC_BASE_URL="https://api.operious.com", WEBHOOK_TRUST_URL_HEADER=False)
    )
    assert not any(
        "PUBLIC_BASE_URL" in p or "WEBHOOK_TRUST_URL_HEADER" in p for p in problems
    )
