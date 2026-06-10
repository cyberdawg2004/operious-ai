"""Release-gate readiness CLI (S-10, #12)."""

from __future__ import annotations

from app.core.config import Settings
from scripts.check_production_readiness import evaluate


def _ready_production(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "ENVIRONMENT": "production",
        "ANTHROPIC_API_KEY": "sk-ant-real",
        "TRANSLATION_PROVIDER": "anthropic",
        "VECTOR_DEFAULT_PROVIDER": "pgvector",
        "EMBEDDING_DEFAULT_PROVIDER": "openai",
        "OPENAI_API_KEY": "sk-openai-real",
        "TENANT_CREDENTIAL_MASTER_KEY": "x" * 32,
        "CREDENTIAL_KMS_BACKEND": "gcp",
        "OPERIOUS_KMS_KEY_RESOURCE": (
            "projects/operious-kms/locations/global/keyRings/operious/"
            "cryptoKeys/tenant-credentials"
        ),
        "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/operious-kms.json",
        "AUDIT_EXPORT_HMAC_SECRET": "y" * 32,
        "PUBLIC_BASE_URL": "https://api.operious.com",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_evaluate_ready_returns_true_no_problems() -> None:
    ready, problems = evaluate(_ready_production())
    assert ready is True
    assert problems == ()


def test_evaluate_not_ready_lists_problems() -> None:
    ready, problems = evaluate(
        _ready_production(ANTHROPIC_API_KEY="", AUDIT_EXPORT_HMAC_SECRET=None)
    )
    assert ready is False
    assert len(problems) >= 2
