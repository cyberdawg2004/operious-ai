from __future__ import annotations

from app.agents.runtime.retry_policy import get_policy
from app.cognition.exceptions import (
    CognitionGovernanceRejectionError,
    CognitionLLMProviderError,
    CognitionPersistenceFailureError,
    CognitionSemanticRejectionError,
    CognitionSemanticValidationError,
    GovernanceDenyError,
    ProviderQuotaExceededError,
    ProviderRateLimitError,
    ProviderTransientError,
)
from app.queues import QUEUE_DEAD_LETTER, QUEUE_DIAGNOSTIC_RETRY
from app.workers.agent_tasks import (
    _classify_diagnostic_exception,
    _diagnostic_retry_decision,
    _success_persistence_failure_exception,
)


def test_quota_exceeded_routes_to_retry_queue() -> None:
    exc = ProviderQuotaExceededError(
        tenant_id="tenant-a",
        provider="anthropic",
        model="claude",
        quota_type="requests_per_minute",
        retry_after_seconds=90,
    )

    decision = _diagnostic_retry_decision(exc, retry_count=0)

    assert decision.error_class == "QUOTA_EXCEEDED"
    assert decision.retry_requested is True
    assert decision.queue == QUEUE_DIAGNOSTIC_RETRY
    assert decision.countdown_seconds == 90


def test_provider_429_uses_correct_retry_policy() -> None:
    policy = get_policy("PROVIDER_429")
    exc = ProviderRateLimitError("rate limited", retry_after_seconds=120)

    decision = _diagnostic_retry_decision(exc, retry_count=0)

    assert policy.max_retries == 4
    assert policy.base_delay_seconds == 60
    assert decision.error_class == "PROVIDER_429"
    assert decision.queue == QUEUE_DIAGNOSTIC_RETRY
    assert decision.countdown_seconds == 120


def test_semantic_rejection_goes_directly_to_dlq() -> None:
    decision = _diagnostic_retry_decision(
        CognitionSemanticRejectionError("invalid enum category"),
        retry_count=0,
    )

    assert decision.error_class == "SEMANTIC_REJECTION"
    assert decision.retry_requested is False
    assert decision.terminal is True
    assert decision.queue == QUEUE_DEAD_LETTER


def test_success_persistence_semantic_validation_error_stays_terminal() -> None:
    semantic_error = CognitionSemanticValidationError(
        "model output drifted governance-significant terms"
    )

    normalized = _success_persistence_failure_exception(semantic_error)
    decision = _diagnostic_retry_decision(normalized, retry_count=0)

    assert normalized is semantic_error
    assert decision.error_class == "SEMANTIC_REJECTION"
    assert decision.retry_requested is False
    assert decision.terminal is True
    assert decision.queue == QUEUE_DEAD_LETTER


def test_success_persistence_semantic_cause_stays_terminal() -> None:
    semantic_error = CognitionSemanticValidationError(
        "model output drifted governance-significant terms"
    )
    wrapped = RuntimeError("outer persistence wrapper")
    wrapped.__cause__ = semantic_error

    normalized = _success_persistence_failure_exception(wrapped)
    decision = _diagnostic_retry_decision(normalized, retry_count=0)

    assert normalized is semantic_error
    assert decision.error_class == "SEMANTIC_REJECTION"
    assert decision.retry_requested is False
    assert decision.queue == QUEUE_DEAD_LETTER


def test_success_persistence_governance_cause_stays_governance_deny() -> None:
    governance_error = CognitionGovernanceRejectionError(
        "governance rejected diagnostic model output"
    )
    wrapped = RuntimeError("outer persistence wrapper")
    wrapped.__cause__ = governance_error

    normalized = _success_persistence_failure_exception(wrapped)
    decision = _diagnostic_retry_decision(normalized, retry_count=0)

    assert normalized is governance_error
    assert decision.error_class == "GOVERNANCE_DENY"
    assert decision.retry_requested is False
    assert decision.queue == QUEUE_DEAD_LETTER


def test_semantic_validation_rejection_uses_dead_letter_escalation_route() -> None:
    decision = _diagnostic_retry_decision(
        CognitionSemanticValidationError(
            "model output drifted governance-significant terms"
        ),
        retry_count=0,
    )

    assert decision.error_class == "SEMANTIC_REJECTION"
    assert decision.retry_requested is False
    assert decision.terminal is True
    assert decision.queue == QUEUE_DEAD_LETTER
    assert decision.countdown_seconds == 0


def test_governance_deny_goes_directly_to_dlq() -> None:
    for exc in (
        GovernanceDenyError("governance denied"),
        CognitionGovernanceRejectionError("legacy governance rejection"),
    ):
        decision = _diagnostic_retry_decision(exc, retry_count=0)

        assert decision.error_class == "GOVERNANCE_DENY"
        assert decision.retry_requested is False
        assert decision.terminal is True
        assert decision.queue == QUEUE_DEAD_LETTER


def test_persistence_failure_retries_on_retry_queue() -> None:
    decision = _diagnostic_retry_decision(
        CognitionPersistenceFailureError("write failed"),
        retry_count=0,
    )

    assert decision.error_class == "PERSISTENCE_FAILURE"
    assert decision.policy.max_retries == 3
    assert decision.retry_requested is True
    assert decision.queue == QUEUE_DIAGNOSTIC_RETRY
    assert decision.countdown_seconds == 15


def test_success_persistence_non_semantic_failure_still_retries() -> None:
    normalized = _success_persistence_failure_exception(
        RuntimeError("database write failed")
    )
    decision = _diagnostic_retry_decision(normalized, retry_count=0)

    assert isinstance(normalized, CognitionPersistenceFailureError)
    assert decision.error_class == "PERSISTENCE_FAILURE"
    assert decision.retry_requested is True
    assert decision.terminal is False
    assert decision.queue == QUEUE_DIAGNOSTIC_RETRY
    assert decision.countdown_seconds == 15


def test_retry_countdown_increases_exponentially() -> None:
    exc = ProviderTransientError("provider unavailable")

    assert _diagnostic_retry_decision(exc, retry_count=0).countdown_seconds == 30
    assert _diagnostic_retry_decision(exc, retry_count=1).countdown_seconds == 60
    assert _diagnostic_retry_decision(exc, retry_count=2).countdown_seconds == 120


def test_retry_exhaustion_routes_to_dlq() -> None:
    exc = ProviderTransientError("provider unavailable")

    decision = _diagnostic_retry_decision(exc, retry_count=3)

    assert decision.error_class == "PROVIDER_5XX"
    assert decision.retry_requested is False
    assert decision.terminal is True
    assert decision.queue == QUEUE_DEAD_LETTER


def test_schema_validation_provider_error_is_parsing_failure() -> None:
    error_class = _classify_diagnostic_exception(
        CognitionLLMProviderError(
            "diagnostic model output failed schema validation"
        )
    )

    assert error_class == "PARSING_FAILURE"
