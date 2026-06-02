"""Orchestration dependency providers.

The composition root for the orchestration runtime. This file is the
single place that:

* constructs the workflow registry,
* constructs the task registry (passing each task its concrete
  collaborators — `AIService` for `AICompletionTask`, etc.),
* composes the `OrchestrationRuntime` over both registries plus the
  `async_sessionmaker` it uses for per-checkpoint persistence,
* exposes FastAPI providers for the registries, runtime, and
  `OrchestrationService`.

Adding a new workflow:
    1. Implement it under `app/orchestration/workflows/<name>_workflow.py`.
    2. Register it in `_build_workflow_registry()` below.

Adding a new task:
    1. Implement it under `app/orchestration/tasks/<name>_task.py`.
    2. Construct it in `_build_task_registry()` with whichever services
       it depends on, and register it.

Reviewers know which workflows / tasks the process is willing to run by
reading these two functions. There is no auto-discovery.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends

from app.core.config import get_settings
from app.dependencies.database import get_session_factory
from app._deprecated.dependencies.memory import (
    build_document_ingestion_service_process_wide,
    build_retrieval_service_process_wide,
)
from app._deprecated.dependencies.providers import _build_gateway
from app._deprecated.dependencies.governance import (
    build_governed_assembly_runtime_process_wide,
)
from app._deprecated.dependencies.rag import build_context_assembly_service_process_wide
from app._deprecated.orchestration.runtime import OrchestrationRuntime
from app._deprecated.orchestration.tasks.ai_completion_task import AICompletionTask
from app._deprecated.orchestration.tasks.context_assembly_task import ContextAssemblyTask
from app._deprecated.orchestration.tasks.document_indexing_task import DocumentIndexingTask
from app._deprecated.orchestration.tasks.governed_context_assembly_task import (
    GovernedContextAssemblyTask,
)
from app._deprecated.orchestration.tasks.registry import TaskRegistry
from app._deprecated.orchestration.tasks.retrieval_task import RetrievalTask
from app._deprecated.orchestration.workflows.registry import WorkflowRegistry
from app._deprecated.orchestration.workflows.simple_chat_workflow import SimpleChatWorkflow
from app._deprecated.services.ai_service import AIService
from app._deprecated.services.orchestration_service import OrchestrationService


@lru_cache(maxsize=1)
def _build_workflow_registry() -> WorkflowRegistry:
    """Construct and populate the process-wide workflow registry."""
    registry = WorkflowRegistry()
    registry.register(SimpleChatWorkflow())
    return registry


@lru_cache(maxsize=1)
def _build_task_registry() -> TaskRegistry:
    """Construct and populate the process-wide task registry.

    Each task is constructed with its concrete collaborators here so
    that tasks themselves remain dependency-free in their definition.
    """
    settings = get_settings()
    ai_service = AIService(
        gateway=_build_gateway(),
        default_model=settings.OPENAI_DEFAULT_MODEL,
    )

    registry = TaskRegistry()
    registry.register(AICompletionTask(ai_service))
    registry.register(
        DocumentIndexingTask(build_document_ingestion_service_process_wide())
    )
    registry.register(RetrievalTask(build_retrieval_service_process_wide()))
    registry.register(
        ContextAssemblyTask(build_context_assembly_service_process_wide())
    )
    registry.register(
        GovernedContextAssemblyTask(
            build_governed_assembly_runtime_process_wide()
        )
    )
    return registry


@lru_cache(maxsize=1)
def _build_runtime() -> OrchestrationRuntime:
    """Construct the process-wide orchestration runtime."""
    return OrchestrationRuntime(
        workflow_registry=_build_workflow_registry(),
        task_registry=_build_task_registry(),
        session_factory=get_session_factory(),
    )


def get_workflow_registry() -> WorkflowRegistry:
    return _build_workflow_registry()


def get_task_registry() -> TaskRegistry:
    return _build_task_registry()


def get_orchestration_runtime() -> OrchestrationRuntime:
    return _build_runtime()


def get_orchestration_service(
    runtime: OrchestrationRuntime = Depends(get_orchestration_runtime),
) -> OrchestrationService:
    """FastAPI dependency: per-request `OrchestrationService` instance."""
    return OrchestrationService(runtime=runtime)


__all__ = [
    "get_workflow_registry",
    "get_task_registry",
    "get_orchestration_runtime",
    "get_orchestration_service",
]
