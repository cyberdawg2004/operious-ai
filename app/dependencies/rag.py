"""RAG subsystem composition root.

Builds and exposes:

* the retrieval-strategy table,
* the retrieval runtime,
* the reranker registry,
* the token estimator,
* the grounding-strategy table,
* `ContextAssemblyService` (per-request DI dependency + process-wide
  builder for orchestration registration).

Lifecycle:

* All process-wide structures (`RerankerRegistry`, `RetrievalRuntime`,
  `BaseTokenEstimator`, grounding tables) are built lazily via
  `lru_cache` and cached for the process lifetime.
* `ContextAssemblyService` instances are constructed per request and
  per orchestration-task registration, mirroring the
  `RetrievalService` / `DocumentIngestionService` lifecycle.

Adding a new reranker:
    1. Implement `BaseReranker`.
    2. Register it in `_build_reranker_registry()`.

Adding a new retrieval strategy:
    1. Implement `BaseRetrievalStrategy`.
    2. Register it in `_build_retrieval_strategies()`.

Adding a new grounding strategy:
    1. Implement `BaseGroundingStrategy`.
    2. Register it in `_build_grounding_strategies()`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Mapping

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.dependencies.memory import (
    build_retrieval_service_process_wide,
    get_retrieval_service,
)
from app.memory.retrieval.service import RetrievalService
from app.rag.assembly.service import ContextAssemblyService
from app.rag.budgeting.estimator import (
    BaseTokenEstimator,
    HeuristicTokenEstimator,
)
from app.rag.grounding.base import BaseGroundingStrategy
from app.rag.grounding.default import DefaultGroundingStrategy
from app.rag.reranking.identity import IdentityReranker
from app.rag.reranking.registry import RerankerRegistry
from app.rag.retrieval.base import BaseRetrievalStrategy
from app.rag.retrieval.runtime import RetrievalRuntime
from app.rag.retrieval.single_query import SingleQueryStrategy


# ─── Reranker registry ────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _build_reranker_registry() -> RerankerRegistry:
    """Construct + populate the process-wide reranker registry."""
    registry = RerankerRegistry()
    registry.register(IdentityReranker())
    return registry


def get_reranker_registry() -> RerankerRegistry:
    return _build_reranker_registry()


# ─── Token estimator ──────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _build_token_estimator() -> BaseTokenEstimator:
    settings = get_settings()
    return HeuristicTokenEstimator(
        ratio=settings.RAG_DEFAULT_TOKEN_ESTIMATOR_RATIO,
    )


def get_token_estimator() -> BaseTokenEstimator:
    return _build_token_estimator()


# ─── Grounding strategies ─────────────────────────────────────────────


@lru_cache(maxsize=1)
def _build_grounding_strategies() -> Mapping[str, BaseGroundingStrategy]:
    default = DefaultGroundingStrategy()
    return {default.name: default}


def get_grounding_strategies() -> Mapping[str, BaseGroundingStrategy]:
    return _build_grounding_strategies()


# ─── Retrieval strategies + runtime ───────────────────────────────────


def _build_retrieval_strategies(
    retrieval_service: RetrievalService,
) -> Mapping[str, BaseRetrievalStrategy]:
    """Construct strategy table given a retrieval service.

    Not `@lru_cache`'d on its own because the underlying
    `RetrievalService` instance differs between per-request DI and
    process-wide orchestration registration. Each caller passes its
    own service.
    """
    single = SingleQueryStrategy(retrieval_service=retrieval_service)
    return {single.info.name: single}


def _build_retrieval_runtime(
    retrieval_service: RetrievalService,
) -> RetrievalRuntime:
    return RetrievalRuntime(
        strategies=_build_retrieval_strategies(retrieval_service)
    )


# ─── Assembly service ─────────────────────────────────────────────────


def get_context_assembly_service(
    settings: Settings = Depends(get_settings),
    retrieval_service: RetrievalService = Depends(get_retrieval_service),
) -> ContextAssemblyService:
    """FastAPI dependency: per-request `ContextAssemblyService`."""
    return ContextAssemblyService(
        retrieval_runtime=_build_retrieval_runtime(retrieval_service),
        reranker_registry=_build_reranker_registry(),
        token_estimator=_build_token_estimator(),
        grounding_strategies=_build_grounding_strategies(),
        settings=settings,
    )


def build_context_assembly_service_process_wide() -> ContextAssemblyService:
    """Construct a process-wide assembly service for orchestration."""
    settings = get_settings()
    retrieval_service = build_retrieval_service_process_wide()
    return ContextAssemblyService(
        retrieval_runtime=_build_retrieval_runtime(retrieval_service),
        reranker_registry=_build_reranker_registry(),
        token_estimator=_build_token_estimator(),
        grounding_strategies=_build_grounding_strategies(),
        settings=settings,
    )


__all__ = [
    "get_reranker_registry",
    "get_token_estimator",
    "get_grounding_strategies",
    "get_context_assembly_service",
    "build_context_assembly_service_process_wide",
]
