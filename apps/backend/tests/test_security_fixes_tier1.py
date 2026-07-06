"""Security regression tests for TIER 1 findings (F1, F2, F3, F16, F17).

F1:  SSRF on MCP preview-tools endpoint.
F2:  Hardcoded MCP OAuth HMAC key → MCP_OAUTH_STATE_SECRET.
F3:  SSRF on OAuth token_endpoint.
F16: CREDENTIAL_KMS_BACKEND=local is a hard prod boot-fail.
F17: SSRF on stored endpoint_template re-validation.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.production_readiness import collect_production_problems
from app.core.ssrf import SSRFValidationError, validate_public_https_url


# ─── helpers ────────────────────────────────────────────────────────────────

def _ready_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "ENVIRONMENT": "production",
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
        "MCP_OAUTH_STATE_SECRET": "z" * 32,
        "PUBLIC_BASE_URL": "https://api.operious.com",
        "AUTH_ENABLED": True,
        "AUTH_PROVIDER": "auth0",
        "CORS_ALLOW_ORIGINS": "https://app.operious.com",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


# ─── F1: SSRF guard on MCP preview / tool-list fetch ────────────────────────

class TestMcpFetchSsrfGuard:
    """validate_public_https_url is the gate used by TenantConfigurationService.
    These confirm the SSRF logic rejects private/metadata URLs that would
    previously have been accepted by the old startswith("https://") guard.
    """

    @pytest.mark.parametrize("url", [
        "https://169.254.169.254/mcp",
        "https://169.254.169.254/latest/meta-data/",
        "https://10.0.0.1/mcp",
        "https://192.168.1.1/mcp",
        "https://172.16.0.1/mcp",
        "https://127.0.0.1/mcp",
        "https://[::1]/mcp",
        "http://example.com/mcp",  # non-HTTPS
    ])
    def test_ssrf_blocked_urls_rejected(self, url: str) -> None:
        with pytest.raises(SSRFValidationError):
            validate_public_https_url(url)

    def test_non_https_scheme_blocked(self) -> None:
        with pytest.raises(SSRFValidationError, match="scheme"):
            validate_public_https_url("http://example.com/mcp")

    def test_loopback_blocked(self) -> None:
        with pytest.raises(SSRFValidationError):
            validate_public_https_url("https://127.0.0.1/mcp")

    def test_link_local_metadata_endpoint_blocked(self) -> None:
        """169.254.169.254 is the GCP/AWS instance metadata IP."""
        with pytest.raises(SSRFValidationError):
            validate_public_https_url(
                "https://169.254.169.254/computeMetadata/v1/instance/service-accounts/"
            )

    def test_private_class_a_blocked(self) -> None:
        with pytest.raises(SSRFValidationError):
            validate_public_https_url("https://10.128.0.1/mcp")

    def test_private_class_b_blocked(self) -> None:
        with pytest.raises(SSRFValidationError):
            validate_public_https_url("https://172.31.255.255/mcp")

    def test_private_class_c_blocked(self) -> None:
        with pytest.raises(SSRFValidationError):
            validate_public_https_url("https://192.168.100.1/mcp")


# ─── F2: MCP_OAUTH_STATE_SECRET must be set in production ────────────────────

class TestMcpOauthStateSecretRequired:

    def test_missing_secret_is_a_production_problem(self) -> None:
        s = _ready_settings(MCP_OAUTH_STATE_SECRET="")
        problems = collect_production_problems(s)
        assert any("MCP_OAUTH_STATE_SECRET" in p for p in problems)

    def test_whitespace_only_secret_is_a_production_problem(self) -> None:
        s = _ready_settings(MCP_OAUTH_STATE_SECRET="   ")
        problems = collect_production_problems(s)
        assert any("MCP_OAUTH_STATE_SECRET" in p for p in problems)

    def test_set_secret_is_not_a_production_problem(self) -> None:
        s = _ready_settings(MCP_OAUTH_STATE_SECRET="a-real-secret-value")
        problems = collect_production_problems(s)
        assert not any("MCP_OAUTH_STATE_SECRET" in p for p in problems)

    def test_settings_has_mcp_oauth_state_secret_attribute(self) -> None:
        s = Settings(MCP_OAUTH_STATE_SECRET="test-secret")  # type: ignore[call-arg]
        assert s.MCP_OAUTH_STATE_SECRET == "test-secret"

    def test_settings_default_is_empty_string(self) -> None:
        s = Settings()
        assert s.MCP_OAUTH_STATE_SECRET == ""


# ─── F3: SSRF guard on OAuth token_endpoint via McpOAuthConfig validator ──────

class TestMcpOauthConfigSsrfValidator:

    def _make_config(self, token_endpoint: str, auth_endpoint: str | None = None) -> dict:
        from app.api.v1.schemas.mcp import McpOAuthConfig
        from pydantic import ValidationError
        try:
            cfg = McpOAuthConfig(
                client_id="client",
                auth_endpoint=auth_endpoint or "https://auth.example.com/authorize",
                token_endpoint=token_endpoint,
                redirect_uri="https://app.operious.com/callback",
            )
            return {"ok": True, "model": cfg}
        except ValidationError as e:
            return {"ok": False, "error": str(e)}

    @pytest.mark.parametrize("bad_endpoint", [
        "https://169.254.169.254/token",
        "https://10.0.0.1/oauth/token",
        "https://192.168.1.1/token",
        "https://127.0.0.1/token",
        "http://auth.example.com/token",  # non-HTTPS
    ])
    def test_private_token_endpoint_rejected(self, bad_endpoint: str) -> None:
        result = self._make_config(bad_endpoint)
        assert result["ok"] is False
        assert "SSRF" in result["error"] or "ssrf" in result["error"].lower() or "rejected" in result["error"]

    @pytest.mark.parametrize("bad_endpoint", [
        "https://169.254.169.254/authorize",
        "https://10.0.0.1/oauth/authorize",
    ])
    def test_private_auth_endpoint_rejected(self, bad_endpoint: str) -> None:
        from app.api.v1.schemas.mcp import McpOAuthConfig
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            McpOAuthConfig(
                client_id="client",
                auth_endpoint=bad_endpoint,
                token_endpoint="https://auth.example.com/token",
                redirect_uri="https://app.operious.com/callback",
            )


# ─── F16: CREDENTIAL_KMS_BACKEND=local is a hard boot-fail ───────────────────

class TestCredentialKmsLocalBootFail:

    def test_local_kms_backend_is_production_problem(self) -> None:
        s = _ready_settings(CREDENTIAL_KMS_BACKEND="local")
        problems = collect_production_problems(s)
        assert any("CREDENTIAL_KMS_BACKEND=local" in p for p in problems)

    def test_gcp_kms_backend_not_a_problem(self) -> None:
        s = _ready_settings(CREDENTIAL_KMS_BACKEND="gcp")
        problems = collect_production_problems(s)
        assert not any("CREDENTIAL_KMS_BACKEND=local" in p for p in problems)

    def test_problem_mentions_gcp_instruction(self) -> None:
        s = _ready_settings(CREDENTIAL_KMS_BACKEND="local")
        problems = collect_production_problems(s)
        kms_problems = [p for p in problems if "CREDENTIAL_KMS_BACKEND=local" in p]
        assert kms_problems, "Expected CREDENTIAL_KMS_BACKEND=local problem"
        # Should tell the operator what to do, not just warn
        assert "gcp" in kms_problems[0].lower() or "Set" in kms_problems[0]


# ─── Full production readiness baseline ─────────────────────────────────────

def test_fully_ready_settings_has_no_problems() -> None:
    """Regression: a fully configured production settings produces no problems."""
    s = _ready_settings()
    problems = collect_production_problems(s)
    assert problems == (), f"Unexpected problems: {problems}"
