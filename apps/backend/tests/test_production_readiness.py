"""Fail-closed production configuration validation (S-09 stubs, #31/#30/
#74/#17/#54).

Production must refuse to boot with stubbed providers or missing
security secrets unless each is EXPLICITLY acknowledged via a feature
flag. This prevents a demo/stub configuration from being mistaken for a
real production deployment.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.production_readiness import (
    ProductionReadinessError,
    validate_production_config,
)


def _production(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "ENVIRONMENT": "production",
        # Real secrets / providers so the baseline is READY; individual
        # tests knock one out.
        "ANTHROPIC_API_KEY": "sk-ant-real",
        "TRANSLATION_PROVIDER": "anthropic",
        "VECTOR_DEFAULT_PROVIDER": "pgvector",
        "EMBEDDING_DEFAULT_PROVIDER": "openai",
        "OPENAI_API_KEY": "sk-openai-real",
        "TENANT_CREDENTIAL_MASTER_KEY": "x" * 32,
        "AUDIT_EXPORT_HMAC_SECRET": "y" * 32,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_fully_configured_production_passes() -> None:
    validate_production_config(_production())


def test_missing_llm_key_blocks_boot() -> None:
    with pytest.raises(ProductionReadinessError) as exc:
        validate_production_config(_production(ANTHROPIC_API_KEY=""))
    assert any("LLM" in p or "llm" in p for p in exc.value.problems)


def test_stub_llm_allowed_with_flag() -> None:
    validate_production_config(
        _production(ANTHROPIC_API_KEY="", ALLOW_STUB_LLM=True)
    )


def test_identity_translation_blocks_boot() -> None:
    with pytest.raises(ProductionReadinessError):
        validate_production_config(_production(TRANSLATION_PROVIDER="identity"))


def test_identity_translation_allowed_with_flag() -> None:
    validate_production_config(
        _production(TRANSLATION_PROVIDER="identity", ALLOW_STUB_TRANSLATION=True)
    )


def test_in_memory_vector_blocks_boot() -> None:
    with pytest.raises(ProductionReadinessError):
        validate_production_config(_production(VECTOR_DEFAULT_PROVIDER="in_memory"))


def test_missing_embedding_key_blocks_boot() -> None:
    with pytest.raises(ProductionReadinessError):
        validate_production_config(_production(OPENAI_API_KEY=None))


def test_missing_credential_master_key_blocks_boot() -> None:
    with pytest.raises(ProductionReadinessError):
        validate_production_config(_production(TENANT_CREDENTIAL_MASTER_KEY=""))


def test_missing_audit_secret_blocks_boot() -> None:
    with pytest.raises(ProductionReadinessError):
        validate_production_config(_production(AUDIT_EXPORT_HMAC_SECRET=None))


def test_voice_enabled_without_secret_blocks_boot() -> None:
    with pytest.raises(ProductionReadinessError):
        validate_production_config(
            _production(VOICE_ENABLED=True, VOICE_SESSION_TOKEN_SECRET="")
        )


def test_all_problems_are_collected() -> None:
    with pytest.raises(ProductionReadinessError) as exc:
        validate_production_config(
            _production(
                ANTHROPIC_API_KEY="",
                TRANSLATION_PROVIDER="identity",
                AUDIT_EXPORT_HMAC_SECRET=None,
            )
        )
    # Every problem is surfaced at once (not just the first).
    assert len(exc.value.problems) >= 3
