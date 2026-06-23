"""A diagnostic parsing failure must reach a human, not dead-letter.

When the LLM never produces parseable output within budget (whether
from a max_tokens truncation that survived its one escalated retry, or
the pre-existing unescaped-quote flavor), _persist_diagnostic_success
raises a raw CognitionLLMProviderError. Before this fix, the generic
try/except in execute_diagnostic_agent_runtime wrapped ANY such failure
into CognitionPersistenceFailureError (PERSISTENCE_FAILURE) regardless
of cause -- the wrong retry budget, and ineligible for the existing
SEMANTIC_REJECTION/GOVERNANCE_DENY terminal-escalation route, so it
dead-lettered (silently dropped) instead of landing in front of a human.

These are narrow unit tests on the pure classification/escalation
functions themselves -- no DB, no Celery, no session -- since the full
worker-level integration (ExecutionRuntime, EscalationAgentRuntime,
governance records) has no existing test harness to extend and would
be substantial new infrastructure orthogonal to this fix.
"""

from __future__ import annotations

from app.cognition.exceptions import (
    CognitionLLMProviderError,
    CognitionParsingFailureError,
    CognitionPersistenceFailureError,
)
from app.workers.agent_tasks import (
    _classify_diagnostic_exception,
    _diagnostic_failure_should_escalate,
    _is_parsing_failure_message,
    _parsing_failure_error_from_chain,
    _success_persistence_failure_exception,
)


# ─── message-marker matching ───────────────────────────────────────────────


def test_invalid_json_message_is_a_parsing_failure_marker() -> None:
    assert _is_parsing_failure_message(
        "diagnostic model returned invalid JSON: Unterminated string"
    )


def test_unrelated_message_is_not_a_parsing_failure_marker() -> None:
    assert not _is_parsing_failure_message("connection reset by peer")


# ─── classification: a JSON-parse error maps to PARSING_FAILURE ───────────


def test_invalid_json_provider_error_classifies_as_parsing_failure() -> None:
    exc = CognitionLLMProviderError(
        "diagnostic model returned invalid JSON: Unterminated string"
    )
    assert _classify_diagnostic_exception(exc) == "PARSING_FAILURE"


def test_unrelated_provider_error_does_not_classify_as_parsing_failure() -> None:
    exc = CognitionLLMProviderError("Anthropic diagnostic request failed: TimeoutError")
    assert _classify_diagnostic_exception(exc) != "PARSING_FAILURE"


# ─── LOAD-BEARING: the wrapping no longer swallows the real error class ───


def test_success_persistence_wrapper_preserves_json_parse_failure_as_parsing_failure() -> (
    None
):
    """Before the fix, this returned CognitionPersistenceFailureError
    (PERSISTENCE_FAILURE: wrong retry budget, dead-letters instead of
    escalating). It must now return a CognitionParsingFailureError so
    _classify_diagnostic_exception sees PARSING_FAILURE."""
    original = CognitionLLMProviderError(
        "diagnostic model returned invalid JSON: Unterminated string "
        "starting at: line 1 column 2250 (char 2249)"
    )
    wrapped = _success_persistence_failure_exception(original)

    assert isinstance(wrapped, CognitionParsingFailureError)
    assert not isinstance(wrapped, CognitionPersistenceFailureError)
    assert _classify_diagnostic_exception(wrapped) == "PARSING_FAILURE"


def test_success_persistence_wrapper_preserves_genuine_db_failure_unchanged() -> None:
    """A failure with nothing parsing-related in its chain (a genuine DB
    write problem) keeps today's behavior exactly -- generic
    CognitionPersistenceFailureError, PERSISTENCE_FAILURE policy,
    dead-letters when terminal. No regression to the real persistence-
    failure path."""
    original = RuntimeError("connection to database lost")
    wrapped = _success_persistence_failure_exception(original)

    assert isinstance(wrapped, CognitionPersistenceFailureError)
    assert _classify_diagnostic_exception(wrapped) == "PERSISTENCE_FAILURE"


def test_success_persistence_wrapper_finds_parsing_failure_buried_in_chain() -> None:
    """The real call site wraps the cognition-runtime exception inside
    other context via `raise ... from exc` chains -- confirm the walk
    finds a CognitionLLMProviderError several frames down, not just at
    the top level."""
    root = CognitionLLMProviderError(
        "diagnostic model returned invalid JSON: Expecting ',' delimiter"
    )
    try:
        try:
            raise root
        except CognitionLLMProviderError as exc:
            raise RuntimeError("persist_reasoning_result failed") from exc
    except RuntimeError as outer:
        wrapped = _success_persistence_failure_exception(outer)

    assert isinstance(wrapped, CognitionParsingFailureError)


def test_parsing_failure_error_from_chain_returns_none_when_absent() -> None:
    assert _parsing_failure_error_from_chain(RuntimeError("unrelated")) is None


# ─── LOAD-BEARING: PARSING_FAILURE escalates to a human, not dead-letter ──


def test_parsing_failure_routes_to_human_escalation_not_dead_letter() -> None:
    assert _diagnostic_failure_should_escalate("PARSING_FAILURE") is True


def test_persistence_failure_still_dead_letters_no_regression() -> None:
    """A genuine DB-write failure (PERSISTENCE_FAILURE, unrelated to
    parsing) is NOT added to the escalation set by this change -- it
    keeps today's dead-letter-when-terminal behavior exactly."""
    assert _diagnostic_failure_should_escalate("PERSISTENCE_FAILURE") is False


def test_semantic_rejection_and_governance_deny_still_escalate_no_regression() -> None:
    assert _diagnostic_failure_should_escalate("SEMANTIC_REJECTION") is True
    assert _diagnostic_failure_should_escalate("GOVERNANCE_DENY") is True
