"""Fail-closed production configuration gate (S-09 stubs / readiness).

Production deployments must not silently run on stubbed providers or
without security-critical secrets. :func:`validate_production_config`
collects EVERY such problem and raises once, so a single boot attempt
surfaces the full remediation list rather than one error at a time.

Stub conditions have no production opt-out. The ``ALLOW_STUB_*`` settings are
non-production escape hatches only. Security secrets (tenant credential master
key, audit export HMAC) also have no opt-out.

This is invoked from :func:`app.main.create_app` when
``settings.production_readiness_enforced`` is true.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import Settings

_KNOWLEDGE_NATIVE_EMBEDDING_DIMENSIONS = 1536


class ProductionReadinessError(RuntimeError):
    """Raised at boot when production configuration is not READY."""

    def __init__(self, problems: tuple[str, ...]) -> None:
        self.problems = problems
        joined = "\n  - ".join(problems)
        super().__init__(
            "Refusing to boot: production configuration is not ready:\n  - "
            f"{joined}\n"
            "Set the real provider/secret, or explicitly acknowledge a stub "
            "with the corresponding ALLOW_STUB_* flag."
        )


def collect_production_problems(settings: "Settings") -> tuple[str, ...]:
    """Return every production-readiness problem (empty when READY)."""

    problems: list[str] = []

    # ── Stubbed providers (no production opt-out) ────────────────────
    if not settings.ANTHROPIC_API_KEY.strip():
        problems.append(
            "ANTHROPIC_API_KEY is empty -> diagnostic cognition falls back "
            "to a deterministic stub LLM."
        )
    if (
        settings.TRANSLATION_PROVIDER.strip().casefold() != "anthropic"
    ):
        problems.append(
            f"TRANSLATION_PROVIDER={settings.TRANSLATION_PROVIDER!r} is not a "
            "real provider -> translation is identity/stub."
        )
    if (
        settings.VECTOR_DEFAULT_PROVIDER.strip().casefold() == "in_memory"
    ):
        problems.append(
            "VECTOR_DEFAULT_PROVIDER=in_memory -> the vector store is "
            "non-durable."
        )
    if (
        settings.EMBEDDING_DEFAULT_PROVIDER.strip().casefold() == "openai"
        and not (settings.OPENAI_API_KEY or "").strip()
    ):
        problems.append(
            "EMBEDDING_DEFAULT_PROVIDER=openai but OPENAI_API_KEY is empty -> "
            "embeddings fall back to a deterministic hash."
        )
    configured_embedding_dimensions = (
        settings.OPENAI_EMBEDDING_DIMENSIONS
        if settings.OPENAI_EMBEDDING_DIMENSIONS is not None
        else _KNOWLEDGE_NATIVE_EMBEDDING_DIMENSIONS
    )
    if (
        settings.EMBEDDING_DEFAULT_PROVIDER.strip().casefold() == "openai"
        and configured_embedding_dimensions
        != _KNOWLEDGE_NATIVE_EMBEDDING_DIMENSIONS
    ):
        problems.append(
            "OPENAI_EMBEDDING_DIMENSIONS="
            f"{configured_embedding_dimensions} does not match native "
            f"pgvector dimension {_KNOWLEDGE_NATIVE_EMBEDDING_DIMENSIONS}; "
            "run a matching embedding-dimension migration before changing it."
        )

    # ── Required security secrets (no opt-out) ───────────────────────
    if not settings.TENANT_CREDENTIAL_MASTER_KEY.strip():
        problems.append(
            "TENANT_CREDENTIAL_MASTER_KEY is empty -> tenant channel "
            "credentials cannot be encrypted/used."
        )
    credential_kms_backend = settings.CREDENTIAL_KMS_BACKEND.strip().casefold()
    if credential_kms_backend == "local":
        problems.append(
            "CREDENTIAL_KMS_BACKEND=local -> tenant channel credentials use "
            "the local master key instead of GCP Cloud KMS."
        )
    elif credential_kms_backend == "gcp":
        if not settings.credential_kms_key_resource:
            problems.append(
                "CREDENTIAL_KMS_BACKEND=gcp but OPERIOUS_KMS_KEY_RESOURCE "
                "is empty -> tenant credential DEKs cannot be wrapped by "
                "GCP Cloud KMS."
            )
        if not settings.GOOGLE_APPLICATION_CREDENTIALS.strip():
            problems.append(
                "CREDENTIAL_KMS_BACKEND=gcp but GOOGLE_APPLICATION_CREDENTIALS "
                "is empty -> the GCP Cloud KMS client cannot authenticate."
            )
    else:
        problems.append(
            f"CREDENTIAL_KMS_BACKEND={settings.CREDENTIAL_KMS_BACKEND!r} is "
            "unsupported; expected 'gcp' in production."
        )
    # Data-protection master key custody (#54/#55).
    data_protection_kms_backend = (
        settings.DATA_PROTECTION_KMS_BACKEND.strip().casefold()
    )
    if data_protection_kms_backend == "local":
        problems.append(
            "DATA_PROTECTION_KMS_BACKEND=local -> the data-protection master "
            "key sits at rest in plaintext instead of being wrapped by GCP "
            "Cloud KMS."
        )
    elif data_protection_kms_backend == "gcp":
        if not settings.data_protection_kms_key_resource:
            problems.append(
                "DATA_PROTECTION_KMS_BACKEND=gcp but OPERIOUS_KMS_KEY_RESOURCE "
                "is empty -> the data-protection master key cannot be "
                "unwrapped by GCP Cloud KMS."
            )
        if not settings.GOOGLE_APPLICATION_CREDENTIALS.strip():
            problems.append(
                "DATA_PROTECTION_KMS_BACKEND=gcp but GOOGLE_APPLICATION_"
                "CREDENTIALS is empty -> the GCP Cloud KMS client cannot "
                "authenticate."
            )
    else:
        problems.append(
            f"DATA_PROTECTION_KMS_BACKEND={settings.DATA_PROTECTION_KMS_BACKEND!r} "
            "is unsupported; expected 'gcp' in production."
        )
    if (
        not settings.DATA_PROTECTION_MASTER_KEYS.strip()
        and not settings.TENANT_CREDENTIAL_MASTER_KEY.strip()
    ):
        problems.append(
            "DATA_PROTECTION_MASTER_KEYS is empty and no tenant credential "
            "master key fallback is configured -> customer data cannot be "
            "envelope-encrypted at rest."
        )
    if not (settings.AUDIT_EXPORT_HMAC_SECRET or "").strip():
        problems.append(
            "AUDIT_EXPORT_HMAC_SECRET is empty -> audit exports cannot be "
            "signed/verified."
        )

    # ── Voice transport ──────────────────────────────────────────────
    if settings.VOICE_ENABLED and not settings.VOICE_SESSION_TOKEN_SECRET.strip():
        problems.append(
            "VOICE_ENABLED=true but VOICE_SESSION_TOKEN_SECRET is empty -> "
            "the voice WebSocket cannot authenticate sessions."
        )

    # ── Webhook signature canonical URL (spec 1b #23) ────────────────
    if settings.WEBHOOK_TRUST_URL_HEADER:
        problems.append(
            "WEBHOOK_TRUST_URL_HEADER=true -> webhook/voice provider signatures "
            "would trust a client-supplied canonical URL header; this must be "
            "false in production."
        )
    elif not settings.public_base_url_normalized:
        problems.append(
            "PUBLIC_BASE_URL is empty -> webhook/voice provider signatures "
            "cannot be verified against a server-derived URL."
        )

    # ── Legacy header authority must stay disabled in production (S-01) ──
    # Boot-fail if an operator override re-enables upstream-attested X-*-ID
    # identity headers as an authority source — the most catastrophic
    # breach path (cross-tenant identity spoofing). Defaults are already
    # fail-closed in prod; this turns a dangerous *override* into a boot error.
    if settings.legacy_header_authority_enabled:
        problems.append(
            "LEGACY_HEADER_AUTHORITY_ENABLED=true in production -> upstream "
            "X-*-ID identity headers would be an accepted authority source, "
            "allowing direct callers to spoof tenant identity; this must be "
            "false (verified bearer only) in production."
        )

    # ── CORS origins must be explicitly configured in production ─────────
    # Empty CORS_ALLOW_ORIGINS triggers the hardcoded fallback list in
    # main.py, which historically included http://localhost:3000.  Even
    # after localhost is removed from the fallback, an unconfigured
    # production deployment silently adopts whatever the hardcoded list
    # contains.  Forcing explicit configuration prevents that drift.
    if not (settings.CORS_ALLOW_ORIGINS or "").strip():
        problems.append(
            "CORS_ALLOW_ORIGINS is empty -> the CORS allowlist falls back to a "
            "hardcoded list that may include unintended origins. "
            "Set CORS_ALLOW_ORIGINS to the explicit production origin(s)."
        )

    # ── Authentication must be enabled in production (S-C1) ─────────────
    # AUTH_ENABLED=false silently disables all bearer-token verification.
    # Every security control that depends on principal identity
    # (tenant isolation, dual-control, capability gating) is predicated on
    # auth being on. A missing env var must not produce an open API.
    if not settings.AUTH_ENABLED:
        problems.append(
            "AUTH_ENABLED=false -> bearer-token verification is disabled; "
            "every authenticated endpoint is reachable without a credential. "
            "Set AUTH_ENABLED=true and a recognised AUTH_PROVIDER in production."
        )
    elif not (settings.AUTH_PROVIDER or "").strip():
        problems.append(
            "AUTH_ENABLED=true but AUTH_PROVIDER is empty -> no authentication "
            "provider is configured; all Authorization-bearing requests will be "
            "rejected with 401 verification_unavailable. "
            "Set AUTH_PROVIDER to a recognised value (e.g. 'auth0')."
        )

    return tuple(problems)


def validate_production_config(settings: "Settings") -> None:
    """Raise :class:`ProductionReadinessError` if any problem is found."""

    problems = collect_production_problems(settings)
    if problems:
        raise ProductionReadinessError(problems)


__all__ = [
    "ProductionReadinessError",
    "collect_production_problems",
    "validate_production_config",
]
