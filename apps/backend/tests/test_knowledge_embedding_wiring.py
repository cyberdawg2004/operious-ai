"""Real embedding provider wiring checks for production knowledge composition."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.dependencies import services
from app.knowledge.embeddings import (
    DEFAULT_EMBEDDING_DIMENSIONS,
    OpenAIEmbeddingProvider,
)
from app.knowledge.persistence.memory import InMemoryKnowledgeRepository
from app.knowledge.runtime import KnowledgeRuntime
from app.tenant.persistence.memory import InMemoryTenantConfigurationRepository

_BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _openai_settings() -> Settings:
    return Settings(
        ENVIRONMENT="production",
        EMBEDDING_DEFAULT_PROVIDER="openai",
        OPENAI_API_KEY="sk-real",
        OPENAI_EMBEDDING_DIMENSIONS=DEFAULT_EMBEDDING_DIMENSIONS,
    )


def test_runtime_default_provider_uses_factory_when_openai_configured(
    monkeypatch,
) -> None:
    import app.knowledge.runtime as runtime_module

    monkeypatch.setattr(runtime_module, "get_settings", _openai_settings)

    runtime = KnowledgeRuntime(
        repository=InMemoryKnowledgeRepository(),
        tenant_configuration_repository=InMemoryTenantConfigurationRepository(),
    )

    provider = runtime._embedding_provider
    assert isinstance(provider, OpenAIEmbeddingProvider)
    assert provider.dimensions == DEFAULT_EMBEDDING_DIMENSIONS


def test_service_composition_wires_openai_provider_when_configured(
    monkeypatch,
) -> None:
    monkeypatch.setattr(services, "get_settings", _openai_settings)
    monkeypatch.setattr(services, "_data_protection_service", lambda session: None)

    service = services.get_knowledge_service(cast(AsyncSession, object()))

    provider = service._runtime._embedding_provider
    assert isinstance(provider, OpenAIEmbeddingProvider)
    assert provider.dimensions == DEFAULT_EMBEDDING_DIMENSIONS


def test_live_composition_paths_do_not_construct_deterministic_provider() -> None:
    live_paths = (
        _BACKEND_ROOT / "app/knowledge/runtime.py",
        _BACKEND_ROOT / "app/dependencies/services.py",
        _BACKEND_ROOT / "app/workers/knowledge_tasks.py",
        _BACKEND_ROOT / "app/workers/agent_tasks.py",
        _BACKEND_ROOT / "app/workers/failure_pattern_tasks.py",
    )

    violations: list[str] = []
    for path in live_paths:
        source = path.read_text(encoding="utf-8")
        if "DeterministicHashEmbeddingProvider()" in source:
            violations.append(str(path))

    assert not violations
