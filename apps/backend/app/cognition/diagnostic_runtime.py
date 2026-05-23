"""LLM-backed diagnostic cognition runtime."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, cast

from app.cognition.exceptions import (
    CognitionGovernanceRejectionError,
    CognitionLLMProviderError,
    CognitionPersistenceError,
    CognitionSemanticValidationError,
)
from app.cognition.governance import LLMDiagnosticOutputPolicy
from app.cognition.identity import (
    CognitionLLMUsageId,
    derive_cognition_audit_id,
    derive_llm_usage_id,
)
from app.cognition.llm import DiagnosticLLMClient, DiagnosticLLMMessage
from app.cognition.models import (
    CognitionAuditRecord,
    CognitionLLMUsageRecord,
    CognitionLLMUsageStatus,
    DiagnosticLLMCompletion,
    DiagnosticReasoningResult,
)
from app.cognition.persistence import CognitionUsagePersistenceProtocol
from app.cognition.semantic import validate_governance_terms
from app.governance.context import GovernanceContext
from app.governance.enums import Decision, EnforcementStage
from app.governance.enforcement.handlers import (
    AllowHandler,
    DegradeHandler,
    DenyHandler,
    EnforcementHandlerRegistry,
    EscalateHandler,
    RedactHandler,
    RequireApprovalHandler,
)
from app.governance.enforcement.runtime import GovernanceRuntime
from app.governance.evaluators.engine import PolicyEvaluationEngine
from app.governance.persistence import BaseGovernanceRepository
from app.governance.policies.chain import PolicyChain
from app.governance.subjects.execution import ExecutionGovernanceSubject
from app.identity import coerce_tenant_id
from app.knowledge.models import KnowledgeRetrievalResult
from app.knowledge.runtime import KnowledgeRuntime

_SYSTEM_PROMPT = """You are Operious diagnostic cognition.
Classify the support ticket using only the ticket text and cited tenant SOP
context. Return compact JSON only with keys: summary, category, confidence.
Use canonical English. Preserve any governance-significant terms present in
the input or citations, and do not invent refunds, approvals, denials,
chargebacks, RMA, legal, fraud, compliance, replacement, credit, or escalation
terms that are not grounded in the input or citations."""
_ALLOWED_OUTPUT_KEYS = frozenset(
    {"summary", "category", "confidence", "reasoning"}
)
_ALLOWED_CATEGORIES = frozenset(
    {
        "account_issue",
        "charging_issue",
        "connectivity_issue",
        "refund_issue",
        "unknown_issue",
    }
)


@dataclass(frozen=True, slots=True)
class DiagnosticCognitionRuntimeConfig:
    max_output_tokens: int = 512
    temperature: float = 0.0
    context_top_k: int = 6
    context_token_budget: int = 2500
    require_citations: bool = False
    input_token_micro_usd: int = 3
    output_token_micro_usd: int = 15


class DiagnosticCognitionRuntime:
    """Runtime for RAG-grounded diagnostic model reasoning."""

    def __init__(
        self,
        *,
        knowledge_runtime: KnowledgeRuntime,
        llm_client: DiagnosticLLMClient,
        usage_persistence: CognitionUsagePersistenceProtocol,
        governance_repository: BaseGovernanceRepository | None = None,
        config: DiagnosticCognitionRuntimeConfig | None = None,
    ) -> None:
        self._knowledge_runtime = knowledge_runtime
        self._llm_client = llm_client
        self._usage_persistence = usage_persistence
        self._governance = _governance_runtime(
            governance_repository=governance_repository,
            require_citations=(
                config.require_citations if config is not None else False
            ),
        )
        self._config = config or DiagnosticCognitionRuntimeConfig()

    async def reason_about_ticket(
        self,
        *,
        tenant_id: str,
        execution_id: str,
        dispatch_id: str,
        session_id: str,
        content: str,
    ) -> DiagnosticReasoningResult:
        retrieval = await self._knowledge_runtime.retrieve(
            tenant_id=tenant_id,
            query=content,
            top_k=self._config.context_top_k,
            max_tokens=self._config.context_token_budget,
        )
        prompt = _render_user_prompt(
            tenant_id=tenant_id,
            dispatch_id=dispatch_id,
            session_id=session_id,
            content=content,
            retrieval=retrieval,
        )
        usage_id = derive_llm_usage_id(
            tenant_id=tenant_id,
            execution_id=execution_id,
            model=self._llm_client.model_name,
        )
        completion: DiagnosticLLMCompletion | None = None
        audit_id: str | None = None
        messages = (DiagnosticLLMMessage(role="user", content=prompt),)
        try:
            completion = await self._complete_llm(
                system_prompt=_SYSTEM_PROMPT,
                messages=messages,
                tenant_id=tenant_id,
            )
            audit_id = await self._save_cognition_audit(
                usage_id=usage_id,
                tenant_id=tenant_id,
                execution_id=execution_id,
                system_prompt=_SYSTEM_PROMPT,
                messages=messages,
                completion=completion,
            )
            parsed = _parse_output(completion.text)
            semantic = validate_governance_terms(
                canonical_text=f"{content}\n\n{_context_text(retrieval)}",
                output_text=(
                    f"{parsed.summary}\n{parsed.category}"
                ),
            )
            governance_decision_id = await self._govern_output(
                tenant_id=tenant_id,
                execution_id=execution_id,
                dispatch_id=dispatch_id,
                session_id=session_id,
                content=content,
                retrieval=retrieval,
                completion=completion,
                parsed=parsed,
                semantic_terms=semantic.output_terms,
                semantic_valid=True,
            )
            record = _usage_record(
                usage_id=usage_id,
                tenant_id=tenant_id,
                execution_id=execution_id,
                dispatch_id=dispatch_id,
                session_id=session_id,
                completion=completion,
                status=CognitionLLMUsageStatus.ACCEPTED,
                estimated_cost_micro_usd=_estimate_cost(
                    completion=completion,
                    input_micro_usd=self._config.input_token_micro_usd,
                    output_micro_usd=self._config.output_token_micro_usd,
                ),
                metadata={
                    "governance_decision_id": governance_decision_id,
                    "cognition_audit_id": audit_id,
                    "cognition_audit_record_id": audit_id,
                    "citation_count": len(retrieval.citations),
                    "semantic_terms": list(semantic.output_terms),
                    "raw_completion_sha256": _raw_completion_sha256(completion),
                },
            )
            await self._save_usage(record, tenant_id=tenant_id)
            return DiagnosticReasoningResult(
                summary=parsed.summary,
                category=parsed.category,
                confidence=parsed.confidence,
                provider=completion.provider,
                model=completion.model,
                prompt_tokens=completion.usage.prompt_tokens,
                completion_tokens=completion.usage.completion_tokens,
                total_tokens=completion.usage.total_tokens,
                estimated_cost_micro_usd=record.estimated_cost_micro_usd,
                usage_id=record.usage_id,
                governance_decision_id=governance_decision_id,
                citations=tuple(citation.index for citation in retrieval.citations),
                semantic_terms=semantic.output_terms,
                retrieval=retrieval,
                metadata={
                    "raw": dict(completion.raw_metadata),
                    "cognition_audit_id": audit_id,
                    "cognition_audit_record_id": audit_id,
                    "raw_completion_sha256": _raw_completion_sha256(completion),
                },
            )
        except CognitionSemanticValidationError as exc:
            await self._save_rejected_usage(
                usage_id=usage_id,
                tenant_id=tenant_id,
                execution_id=execution_id,
                dispatch_id=dispatch_id,
                session_id=session_id,
                error=exc,
                provider=self._llm_client.provider_name,
                model=self._llm_client.model_name,
                completion=completion,
                audit_id=audit_id,
            )
            raise
        except CognitionGovernanceRejectionError as exc:
            await self._save_rejected_usage(
                usage_id=usage_id,
                tenant_id=tenant_id,
                execution_id=execution_id,
                dispatch_id=dispatch_id,
                session_id=session_id,
                error=exc,
                provider=self._llm_client.provider_name,
                model=self._llm_client.model_name,
                completion=completion,
                audit_id=audit_id,
            )
            raise
        except CognitionLLMProviderError as exc:
            await self._save_rejected_usage(
                usage_id=usage_id,
                tenant_id=tenant_id,
                execution_id=execution_id,
                dispatch_id=dispatch_id,
                session_id=session_id,
                error=exc,
                provider=self._llm_client.provider_name,
                model=self._llm_client.model_name,
                completion=completion,
                audit_id=audit_id,
            )
            raise
        except Exception as exc:
            await self._save_rejected_usage(
                usage_id=usage_id,
                tenant_id=tenant_id,
                execution_id=execution_id,
                dispatch_id=dispatch_id,
                session_id=session_id,
                error=exc,
                provider=self._llm_client.provider_name,
                model=self._llm_client.model_name,
                completion=completion,
                audit_id=audit_id,
                failed=True,
            )
            raise CognitionLLMProviderError(
                f"diagnostic cognition failed: {exc.__class__.__name__}"
            ) from exc

    async def _complete_llm(
        self,
        *,
        system_prompt: str,
        messages: tuple[DiagnosticLLMMessage, ...],
        tenant_id: str,
    ) -> DiagnosticLLMCompletion:
        try:
            return await self._llm_client.complete(
                system_prompt=system_prompt,
                messages=messages,
                max_output_tokens=self._config.max_output_tokens,
                temperature=self._config.temperature,
                tenant_id=tenant_id,
            )
        except TypeError as exc:
            if "tenant_id" not in str(exc):
                raise
            return await self._llm_client.complete(
                system_prompt=system_prompt,
                messages=messages,
                max_output_tokens=self._config.max_output_tokens,
                temperature=self._config.temperature,
            )

    async def _govern_output(
        self,
        *,
        tenant_id: str,
        execution_id: str,
        dispatch_id: str,
        session_id: str,
        content: str,
        retrieval: KnowledgeRetrievalResult,
        completion: DiagnosticLLMCompletion,
        parsed: "_ParsedDiagnosticOutput",
        semantic_terms: tuple[str, ...],
        semantic_valid: bool,
    ) -> str | None:
        subject = ExecutionGovernanceSubject(
            query=content,
            tenant_id=tenant_id,
            execution_action="ai.diagnostic_classification",
            downstream_targets=(f"model:{completion.provider}:{completion.model}",),
            citation_count=len(retrieval.citations),
            fragment_count=len(retrieval.items),
            candidate_count_included=len(retrieval.items),
            estimated_tokens=retrieval.total_tokens + completion.usage.total_tokens,
            grounding_strategy="tenant_sop_rag",
            metadata={
                "category": parsed.category,
                "confidence": parsed.confidence,
                "provider": completion.provider,
                "model": completion.model,
                "semantic_valid": semantic_valid,
                "semantic_terms": list(semantic_terms),
                "usage_total_tokens": completion.usage.total_tokens,
            },
        )
        envelope = await self._governance.evaluate(
            GovernanceContext(
                stage=EnforcementStage.PRE_EXECUTION,
                action="ai.diagnostic_classification",
                resource=f"execution:{execution_id}",
                actor="agent:diagnostic",
                tenant_id=coerce_tenant_id(tenant_id),
                subject=subject,
                metadata={
                    "dispatch_id": dispatch_id,
                    "session_id": session_id,
                },
            )
        )
        decision_id = (
            str(envelope.decision.decision_id)
            if envelope.decision is not None
            else None
        )
        if (
            not envelope.is_ok
            or envelope.decision is None
            or envelope.decision.decision is not Decision.ALLOW
        ):
            raise CognitionGovernanceRejectionError(
                "governance rejected diagnostic model output"
            )
        return decision_id

    async def _save_usage(
        self,
        record: CognitionLLMUsageRecord,
        *,
        tenant_id: str,
    ) -> None:
        try:
            await self._usage_persistence.save_llm_usage(
                record,
                expected_tenant_id=tenant_id,
            )
        except Exception as exc:
            raise CognitionPersistenceError("LLM usage persistence failed") from exc

    async def _save_cognition_audit(
        self,
        *,
        usage_id: CognitionLLMUsageId,
        tenant_id: str,
        execution_id: str,
        system_prompt: str,
        messages: tuple[DiagnosticLLMMessage, ...],
        completion: DiagnosticLLMCompletion,
    ) -> str:
        prompt_full = _full_prompt_snapshot(
            system_prompt=system_prompt,
            messages=messages,
        )
        prompt_sha256 = _sha256_text(prompt_full)
        completion_sha256 = _raw_completion_sha256(completion)
        audit_id = derive_cognition_audit_id(
            tenant_id=tenant_id,
            execution_id=execution_id,
            model=completion.model,
            prompt_sha256=prompt_sha256,
            completion_sha256=completion_sha256,
        )
        record = CognitionAuditRecord(
            audit_id=audit_id,
            tenant_id=tenant_id,
            execution_id=execution_id,
            usage_id=usage_id,
            prompt_full=prompt_full,
            completion_full=completion.text,
            prompt_sha256=prompt_sha256,
            completion_sha256=completion_sha256,
            model_name=completion.model,
            token_usage={
                "provider": completion.provider,
                "model": completion.model,
                "prompt_tokens": completion.usage.prompt_tokens,
                "completion_tokens": completion.usage.completion_tokens,
                "total_tokens": completion.usage.total_tokens,
            },
            captured_at=_utcnow(),
        )
        try:
            await self._usage_persistence.save_cognition_audit(
                record,
                expected_tenant_id=tenant_id,
            )
        except Exception as exc:
            raise CognitionPersistenceError(
                "cognition audit persistence failed"
            ) from exc
        return str(audit_id)

    async def _save_rejected_usage(
        self,
        *,
        usage_id: CognitionLLMUsageId,
        tenant_id: str,
        execution_id: str,
        dispatch_id: str,
        session_id: str,
        error: BaseException,
        provider: str,
        model: str,
        completion: DiagnosticLLMCompletion | None = None,
        audit_id: str | None = None,
        failed: bool = False,
    ) -> None:
        prompt_tokens = completion.usage.prompt_tokens if completion is not None else 0
        completion_tokens = (
            completion.usage.completion_tokens if completion is not None else 0
        )
        total_tokens = completion.usage.total_tokens if completion is not None else 0
        cost = (
            _estimate_cost(
                completion=completion,
                input_micro_usd=self._config.input_token_micro_usd,
                output_micro_usd=self._config.output_token_micro_usd,
            )
            if completion is not None
            else 0
        )
        record = CognitionLLMUsageRecord(
            usage_id=usage_id,
            tenant_id=tenant_id,
            execution_id=execution_id,
            dispatch_id=dispatch_id,
            session_id=session_id,
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost_micro_usd=cost,
            status=(
                CognitionLLMUsageStatus.FAILED
                if failed
                else CognitionLLMUsageStatus.REJECTED
            ),
            created_at=_utcnow(),
            metadata={
                "error_type": error.__class__.__name__,
                "message": _bounded_message(error),
                **(
                    {
                        "cognition_audit_id": audit_id,
                        "cognition_audit_record_id": audit_id,
                    }
                    if audit_id is not None
                    else {}
                ),
                **(
                    {"raw_completion_sha256": _raw_completion_sha256(completion)}
                    if completion is not None
                    else {}
                ),
            },
        )
        await self._save_usage(record, tenant_id=tenant_id)


@dataclass(frozen=True, slots=True)
class _ParsedDiagnosticOutput:
    summary: str
    category: str
    confidence: float


def _governance_runtime(
    *,
    governance_repository: BaseGovernanceRepository | None,
    require_citations: bool,
) -> GovernanceRuntime:
    registry = EnforcementHandlerRegistry()
    for handler in (
        AllowHandler(),
        DenyHandler(),
        RedactHandler(),
        DegradeHandler(),
        EscalateHandler(),
        RequireApprovalHandler(),
    ):
        registry.register(handler)
    return GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=registry,
        chains={
            EnforcementStage.PRE_EXECUTION: PolicyChain(
                chain_id="cognition.llm_diagnostic.pre_execution",
                stage=EnforcementStage.PRE_EXECUTION,
                policies=(
                    LLMDiagnosticOutputPolicy(require_citations=require_citations),
                ),
            )
        },
        persistence=governance_repository,
    )


def _parse_output(text: str) -> _ParsedDiagnosticOutput:
    try:
        raw = json.loads(_extract_json(text))
    except json.JSONDecodeError as exc:
        raise CognitionLLMProviderError("diagnostic model returned invalid JSON") from exc
    if not isinstance(raw, Mapping):
        raise CognitionLLMProviderError("diagnostic model returned non-object JSON")
    data = cast(Mapping[str, Any], raw)
    extra_keys = set(data) - _ALLOWED_OUTPUT_KEYS
    if extra_keys:
        raise CognitionLLMProviderError(
            "diagnostic model returned unsupported keys"
        )
    summary = data.get("summary")
    category = data.get("category")
    confidence = data.get("confidence")
    if not isinstance(summary, str) or not summary.strip():
        raise CognitionLLMProviderError("diagnostic model summary is missing")
    if not isinstance(category, str) or not category.strip():
        raise CognitionLLMProviderError("diagnostic model category is missing")
    category_text = category.strip()
    if category_text not in _ALLOWED_CATEGORIES:
        raise CognitionLLMProviderError("diagnostic model category is unsupported")
    if not isinstance(confidence, (int, float)):
        raise CognitionLLMProviderError("diagnostic model confidence is missing")
    confidence_float = float(confidence)
    if not 0.0 <= confidence_float <= 1.0:
        raise CognitionLLMProviderError("diagnostic model confidence must be in [0, 1]")
    return _ParsedDiagnosticOutput(
        summary=summary.strip(),
        category=category_text,
        confidence=confidence_float,
    )


def _extract_json(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        return stripped
    return stripped[start : end + 1]


def _render_user_prompt(
    *,
    tenant_id: str,
    dispatch_id: str,
    session_id: str,
    content: str,
    retrieval: KnowledgeRetrievalResult,
) -> str:
    return "\n\n".join(
        (
            f"tenant_id: {tenant_id}",
            f"dispatch_id: {dispatch_id}",
            f"session_id: {session_id}",
            "ticket:",
            content,
            "tenant_sop_citations:",
            _context_text(retrieval) or "(no indexed SOP citations available)",
        )
    )


def _context_text(retrieval: KnowledgeRetrievalResult) -> str:
    return "\n\n".join(
        (
            f"[{item.citation_index}] {item.title} "
            f"v{item.document_version}: {item.content}"
        )
        for item in retrieval.items
    )


def _usage_record(
    *,
    usage_id: CognitionLLMUsageId,
    tenant_id: str,
    execution_id: str,
    dispatch_id: str,
    session_id: str,
    completion: DiagnosticLLMCompletion,
    status: CognitionLLMUsageStatus,
    estimated_cost_micro_usd: int,
    metadata: Mapping[str, Any],
) -> CognitionLLMUsageRecord:
    return CognitionLLMUsageRecord(
        usage_id=usage_id,
        tenant_id=tenant_id,
        execution_id=execution_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        provider=completion.provider,
        model=completion.model,
        prompt_tokens=completion.usage.prompt_tokens,
        completion_tokens=completion.usage.completion_tokens,
        total_tokens=completion.usage.total_tokens,
        estimated_cost_micro_usd=estimated_cost_micro_usd,
        status=status,
        created_at=_utcnow(),
        metadata=metadata,
    )


def _raw_completion_sha256(completion: DiagnosticLLMCompletion) -> str:
    return _sha256_text(completion.text)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _full_prompt_snapshot(
    *,
    system_prompt: str,
    messages: tuple[DiagnosticLLMMessage, ...],
) -> str:
    return json.dumps(
        {
            "system": system_prompt,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _estimate_cost(
    *,
    completion: DiagnosticLLMCompletion,
    input_micro_usd: int,
    output_micro_usd: int,
) -> int:
    return (
        completion.usage.prompt_tokens * input_micro_usd
        + completion.usage.completion_tokens * output_micro_usd
    )


def _bounded_message(error: BaseException) -> str:
    message = str(error)
    if len(message) <= 240:
        return message
    return f"{message[:237]}..."


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "DiagnosticCognitionRuntime",
    "DiagnosticCognitionRuntimeConfig",
]
