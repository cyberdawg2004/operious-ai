"""Fail-closed production configuration validation (S-09 stubs, #31/#30/
#74/#17/#54).

Production must refuse to boot with stubbed providers or missing
security secrets. This prevents a demo/stub configuration from being
mistaken for a real production deployment.
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
        "CREDENTIAL_KMS_BACKEND": "gcp",
        "DATA_PROTECTION_KMS_BACKEND": "gcp",
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


def test_fully_configured_production_passes() -> None:
    validate_production_config(_production())


def test_missing_llm_key_blocks_boot() -> None:
    with pytest.raises(ProductionReadinessError) as exc:
        validate_production_config(_production(ANTHROPIC_API_KEY=""))
    assert any("LLM" in p or "llm" in p for p in exc.value.problems)


def test_stub_llm_flag_does_not_override_production_fail_closed() -> None:
    with pytest.raises(ProductionReadinessError):
        validate_production_config(
            _production(ANTHROPIC_API_KEY="", ALLOW_STUB_LLM=True)
        )


def test_identity_translation_blocks_boot() -> None:
    with pytest.raises(ProductionReadinessError):
        validate_production_config(_production(TRANSLATION_PROVIDER="identity"))


def test_identity_translation_flag_does_not_override_production_fail_closed() -> None:
    with pytest.raises(ProductionReadinessError):
        validate_production_config(
            _production(
                TRANSLATION_PROVIDER="identity",
                ALLOW_STUB_TRANSLATION=True,
            )
        )


def test_in_memory_vector_blocks_boot() -> None:
    with pytest.raises(ProductionReadinessError):
        validate_production_config(_production(VECTOR_DEFAULT_PROVIDER="in_memory"))


def test_missing_embedding_key_blocks_boot() -> None:
    with pytest.raises(ProductionReadinessError):
        validate_production_config(_production(OPENAI_API_KEY=None))


def test_embedding_dimension_mismatch_blocks_boot() -> None:
    with pytest.raises(ProductionReadinessError) as exc:
        validate_production_config(_production(OPENAI_EMBEDDING_DIMENSIONS=512))
    assert any("pgvector dimension" in problem for problem in exc.value.problems)


def test_missing_credential_master_key_blocks_boot() -> None:
    with pytest.raises(ProductionReadinessError):
        validate_production_config(_production(TENANT_CREDENTIAL_MASTER_KEY=""))


def test_local_credential_kms_backend_blocks_production_boot() -> None:
    with pytest.raises(ProductionReadinessError) as exc:
        validate_production_config(_production(CREDENTIAL_KMS_BACKEND="local"))
    assert any("CREDENTIAL_KMS_BACKEND=local" in p for p in exc.value.problems)


def test_gcp_credential_kms_requires_key_resource_and_credentials() -> None:
    with pytest.raises(ProductionReadinessError) as exc:
        validate_production_config(
            _production(
                OPERIOUS_KMS_KEY_RESOURCE="",
                GCP_KMS_KEY_RESOURCE="",
                GOOGLE_APPLICATION_CREDENTIALS="",
            )
        )
    assert any("OPERIOUS_KMS_KEY_RESOURCE" in p for p in exc.value.problems)
    assert any("GOOGLE_APPLICATION_CREDENTIALS" in p for p in exc.value.problems)


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


def test_legacy_header_authority_enabled_in_production_fails() -> None:
    # Breach path #1 / finding #3: re-enabling upstream X-*-ID identity
    # headers in production must be a boot failure, not a silent override.
    with pytest.raises(ProductionReadinessError) as excinfo:
        validate_production_config(
            _production(LEGACY_HEADER_AUTHORITY_ENABLED=True)
        )
    assert any(
        "LEGACY_HEADER_AUTHORITY_ENABLED" in problem
        for problem in excinfo.value.problems
    )


def test_baseline_production_keeps_legacy_header_authority_disabled() -> None:
    # The READY baseline must NOT trip the new gate (defaults fail-closed).
    validate_production_config(_production())


def test_data_protection_kms_local_blocks_boot() -> None:
    # #54/#55: the data-protection master key must be under KMS custody in
    # production, not sitting at rest in plaintext.
    with pytest.raises(ProductionReadinessError) as exc:
        validate_production_config(_production(DATA_PROTECTION_KMS_BACKEND="local"))
    assert any(
        "DATA_PROTECTION_KMS_BACKEND=local" in problem
        for problem in exc.value.problems
    )


def test_data_protection_kms_gcp_requires_key_resource() -> None:
    with pytest.raises(ProductionReadinessError) as exc:
        validate_production_config(
            _production(OPERIOUS_KMS_KEY_RESOURCE="", GCP_KMS_KEY_RESOURCE="")
        )
    assert any(
        "data-protection master key" in problem.lower()
        or "OPERIOUS_KMS_KEY_RESOURCE" in problem
        for problem in exc.value.problems
    )
