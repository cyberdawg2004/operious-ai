"""Fail-closed production configuration gate (S-09 stubs / readiness).

Production deployments must not silently run on stubbed providers or
without security-critical secrets. :func:`validate_production_config`
collects EVERY such problem and raises once, so a single boot attempt
surfaces the full remediation list rather than one error at a time.

Each stub condition is gated by an explicit ``ALLOW_STUB_*`` flag so an
operator can opt a pilot into a known-stub posture deliberately. The
security secrets (tenant credential master key, audit export HMAC) have
no opt-out — they are always required in production.

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

    # ── Stubbed providers (opt-out via ALLOW_STUB_*) ─────────────────
    if not settings.ANTHROPIC_API_KEY.strip() and not settings.ALLOW_STUB_LLM:
        problems.append(
            "ANTHROPIC_API_KEY is empty -> diagnostic cognition falls back "
            "to a deterministic stub LLM (set ALLOW_STUB_LLM=true to allow)."
        )
    if (
        settings.TRANSLATION_PROVIDER.strip().casefold() != "anthropic"
        and not settings.ALLOW_STUB_TRANSLATION
    ):
        problems.append(
            f"TRANSLATION_PROVIDER={settings.TRANSLATION_PROVIDER!r} is not a "
            "real provider -> translation is identity/stub (set "
            "ALLOW_STUB_TRANSLATION=true to allow)."
        )
    if (
        settings.VECTOR_DEFAULT_PROVIDER.strip().casefold() == "in_memory"
        and not settings.ALLOW_STUB_VECTOR
    ):
        problems.append(
            "VECTOR_DEFAULT_PROVIDER=in_memory -> the vector store is "
            "non-durable (set ALLOW_STUB_VECTOR=true to allow)."
        )
    if (
        settings.EMBEDDING_DEFAULT_PROVIDER.strip().casefold() == "openai"
        and not (settings.OPENAI_API_KEY or "").strip()
        and not settings.ALLOW_STUB_EMBEDDINGS
    ):
        problems.append(
            "EMBEDDING_DEFAULT_PROVIDER=openai but OPENAI_API_KEY is empty -> "
            "embeddings fall back to a deterministic hash (set "
            "ALLOW_STUB_EMBEDDINGS=true to allow)."
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
