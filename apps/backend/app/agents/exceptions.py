"""Typed exception vocabulary for the agent runtime.

The substrate uses these typed exceptions for **internal control
flow** only. The runtime APIs (`AgentRuntime.execute`,
`ToolInvoker.invoke`, `AgentToolSession.invoke`) NEVER raise — every
failure mode produces a typed envelope. These exceptions exist so
internal validation (state-machine transitions, registry lookups) can
be expressed clearly and so dependency-audit rules can constrain the
substrate to a closed exception vocabulary.
"""

from __future__ import annotations


class AgentError(Exception):
    """Base for every typed substrate exception."""


class AgentNotFoundError(AgentError):
    """Raised when an unregistered `agent_id` is requested.

    Caught by `AgentRuntime.execute()` and turned into a failed
    envelope.
    """


class AgentConfigurationError(AgentError):
    """Raised at composition time for invalid runtime configuration.

    Examples: duplicate agent registration, empty agent_id, missing
    required tool registry.
    """


class StateTransitionError(AgentError):
    """Raised by `state_machine.assert_transition` for illegal moves.

    Caught by `AgentRuntime` and folded into a failed envelope. Tests
    use the raised form to validate the transition table directly.
    """


class ToolNotFoundError(AgentError):
    """Raised when an unregistered tool name is invoked.

    Caught by `ToolInvoker.invoke()` and turned into a failed
    invocation envelope.
    """


class ToolConfigurationError(AgentError):
    """Raised at composition time for invalid tool registration."""


class CapabilityViolationError(AgentError):
    """Raised when a tool requires a capability the agent lacks.

    Folded into a failed invocation envelope — the agent runtime
    surfaces the structured failure rather than re-raising.
    """


class ConstraintViolationError(AgentError):
    """Raised when execution constraints (max invocations, allowed
    tools) are exceeded.

    Folded into a failed invocation envelope.
    """


__all__ = [
    "AgentError",
    "AgentNotFoundError",
    "AgentConfigurationError",
    "StateTransitionError",
    "ToolNotFoundError",
    "ToolConfigurationError",
    "CapabilityViolationError",
    "ConstraintViolationError",
]
