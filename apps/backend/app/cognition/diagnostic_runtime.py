"""LLM-backed diagnostic cognition runtime."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, cast

from pydantic import ValidationError

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
    DiagnosticCategory,
    DiagnosticLLMCompletion,
    DiagnosticLLMOutput,
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
context. Return compact JSON only. Do not wrap it in markdown fences and do
not include keys outside the schema below.

Required JSON schema:
{
  "summary": "non-empty string, max 4000 characters",
  "category": "one of: account_issue, charging_issue, connectivity_issue, product_defect, refund_issue, unknown_issue",
  "confidence": "number between 0.0 and 1.0",
  "reasoning": "string, max 4000 characters"
}

The category value must be exactly one of: account_issue, charging_issue,
connectivity_issue, product_defect, refund_issue, unknown_issue.
The confidence value must be a JSON number between 0.0 and 1.0, not a word.
Use charging_issue for charger, cable, battery, or device-not-charging
symptoms. Use product_defect for physical/manufacturing defect evidence that
is not primarily a charging or connectivity symptom.
Use canonical English. Preserve any governance-significant terms present in
the input or citations, and do not invent refunds, approvals, denials,
chargebacks, RMA, legal, fraud, compliance, replacement, credit, or escalation
terms that are not grounded in the input or citations."""

_DIAGNOSTIC_OUTPUT_FIELDS = frozenset(DiagnosticLLMOutput.model_fields)
_CATEGORY_VALUES = tuple(category.value for category in DiagnosticCategory)


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
        attempt_id: str | None = None,
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
            prompt_sha256 = _sha256_text(
                _full_prompt_snapshot(
                    system_prompt=_SYSTEM_PROMPT,
                    messages=messages,
                )
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
                canonical_text=content,
                allowed_text=f"{content}\n\n{_context_text(retrieval)}",
                output_text=(
                    f"{parsed.summary}\n{parsed.category.value}\n"
                    f"{parsed.reasoning}"
                ),
            )
            governance_decision_id = await self._govern_output(
                tenant_id=tenant_id,
                execution_id=execution_id,
                dispatch_id=dispatch_id,
                session_id=session_id,
                attempt_id=attempt_id,
                content=content,
                retrieval=retrieval,
                completion=completion,
                parsed=parsed,
                prompt_sha256=prompt_sha256,
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
                    **({"attempt_id": attempt_id} if attempt_id is not None else {}),
                    "semantic_terms": list(semantic.output_terms),
                    "raw_completion_sha256": _raw_completion_sha256(completion),
                },
            )
            await self._save_usage(record, tenant_id=tenant_id)
            return DiagnosticReasoningResult(
                summary=parsed.summary,
                category=parsed.category.value,
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
        except CognitionPersistenceError as exc:
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
        attempt_id: str | None,
        content: str,
        retrieval: KnowledgeRetrievalResult,
        completion: DiagnosticLLMCompletion,
        parsed: DiagnosticLLMOutput,
        prompt_sha256: str,
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
                "category": parsed.category.value,
                "confidence": parsed.confidence,
                "provider": completion.provider,
                "model": completion.model,
                "semantic_valid": semantic_valid,
                "semantic_terms": list(semantic_terms),
                "usage_total_tokens": completion.usage.total_tokens,
                **({"attempt_id": attempt_id} if attempt_id is not None else {}),
            },
        )
        decision_seed = _diagnostic_governance_decision_seed(
            tenant_id=tenant_id,
            execution_id=execution_id,
            dispatch_id=dispatch_id,
            session_id=session_id,
            attempt_id=attempt_id,
            provider=completion.provider,
            model=completion.model,
            prompt_sha256=prompt_sha256,
            completion_sha256=_raw_completion_sha256(completion),
        )
        try:
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
                        "governance.decision_seed": decision_seed,
                        **(
                            {"attempt_id": attempt_id}
                            if attempt_id is not None
                            else {}
                        ),
                    },
                )
            )
        except Exception as exc:
            raise CognitionPersistenceError(
                "diagnostic governance persistence failed: "
                f"{exc.__class__.__name__}: {_bounded_message(exc)}"
            ) from exc
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


def _parse_output(text: str) -> DiagnosticLLMOutput:
    try:
        raw = json.loads(_extract_json(text))
    except json.JSONDecodeError as exc:
        raise CognitionLLMProviderError("diagnostic model returned invalid JSON") from exc
    if not isinstance(raw, Mapping):
        raise CognitionLLMProviderError("diagnostic model returned non-object JSON")
    raw_map = cast(Mapping[str, Any], raw)
    try:
        return DiagnosticLLMOutput.model_validate(raw_map)
    except ValidationError as exc:
        if _only_extra_field_errors(exc):
            stripped: dict[str, Any] = {
                key: value
                for key, value in raw_map.items()
                if key in _DIAGNOSTIC_OUTPUT_FIELDS
            }
            try:
                return DiagnosticLLMOutput.model_validate(stripped)
            except ValidationError as stripped_exc:
                raise _diagnostic_schema_error(stripped_exc) from stripped_exc
        if _category_value_is_unknown(raw_map, exc):
            raise CognitionSemanticValidationError(
                "diagnostic model output semantic rejection: "
                f"category={_bounded_repr(raw_map.get('category'))} is not one of "
                f"{', '.join(_CATEGORY_VALUES)}"
            ) from exc
        raise _diagnostic_schema_error(exc) from exc


def _diagnostic_schema_error(exc: ValidationError) -> CognitionLLMProviderError:
    return CognitionLLMProviderError(
        "diagnostic model output failed schema validation: "
        f"{_validation_error_summary(exc)}"
    )


def _only_extra_field_errors(exc: ValidationError) -> bool:
    errors = exc.errors()
    return bool(errors) and all(
        str(error.get("type")) == "extra_forbidden" for error in errors
    )


def _category_value_is_unknown(
    raw: Mapping[str, Any],
    exc: ValidationError,
) -> bool:
    if "category" not in raw:
        return False
    return any(
        tuple(error.get("loc", ())) == ("category",)
        and str(error.get("type")) == "enum"
        for error in exc.errors()
    )


def _validation_error_summary(exc: ValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error.get("loc", ())) or "<root>"
        error_type = str(error.get("type") or "validation_error")
        message = str(error.get("msg") or "validation failed")
        input_value = (
            "<missing>"
            if error_type == "missing"
            else _bounded_repr(error.get("input"))
        )
        parts.append(
            f"{loc}: {error_type}: {message}; input={input_value}"
        )
    return "; ".join(parts)


def _bounded_repr(value: object) -> str:
    text = repr(value)
    if len(text) <= 120:
        return text
    return f"{text[:117]}..."


def _schema_appendix() -> str:
    return json.dumps(
        {
            "summary": "non-empty string, max 4000 characters",
            "category": list(_CATEGORY_VALUES),
            "confidence": "number between 0.0 and 1.0",
            "reasoning": "string, max 4000 characters",
        },
        sort_keys=True,
        separators=(",", ":"),
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
            "response_contract:",
            (
                "Return JSON only. Required keys: summary, category, "
                "confidence, reasoning. category must be exactly one of "
                "account_issue, charging_issue, connectivity_issue, "
                "product_defect, refund_issue, unknown_issue. Do not use "
                "human-readable category labels. confidence must be a "
                "number between 0.0 and 1.0, not a word. Do not include "
                f"extra keys. schema={_schema_appendix()}"
            ),
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


def _diagnostic_governance_decision_seed(
    *,
    tenant_id: str,
    execution_id: str,
    dispatch_id: str,
    session_id: str,
    attempt_id: str | None,
    provider: str,
    model: str,
    prompt_sha256: str,
    completion_sha256: str,
) -> str:
    return "cognition.diagnostic.output|" + json.dumps(
        {
            "attempt_id": attempt_id,
            "completion_sha256": completion_sha256,
            "dispatch_id": dispatch_id,
            "execution_id": execution_id,
            "model": model,
            "prompt_sha256": prompt_sha256,
            "provider": provider,
            "session_id": session_id,
            "tenant_id": tenant_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


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
