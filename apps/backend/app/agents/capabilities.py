"""Agent capability contracts.

Three vocabulary types:

* `AgentCapability` — one named capability the agent declares
  (e.g. ``AgentCapability(name="retrieval.read",
  scope=CapabilityScope.READ)``).
* `CapabilitySet` — an ordered, immutable collection of capabilities.
  The runtime hands one of these to every execution.
* `ExecutionConstraints` — operational caps applied per execution
  (max tool invocations, allowed-tool whitelist, optional timeout).

No implicit capabilities. An agent that doesn't declare ``"tool.search"``
cannot invoke the search tool; the `AgentToolSession` enforces this
deterministically before any governance evaluation runs.

Both types are `frozen=True, slots=True`. `CapabilitySet` is hashable
via its tuple-of-frozen-dataclass storage; the inner `metadata`
mappings are not hashable, but that's fine — we never put
`AgentCapability` in a set, only in tuples.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.agents.enums import CapabilityScope
from app.types.json import JsonObject, MetadataMap


def _empty_json_object() -> JsonObject:
    return {}


@dataclass(frozen=True, slots=True)
class AgentCapability:
    """One declared capability.

    Attributes:
        name:        Stable namespaced identifier (e.g.
                     ``"retrieval.read"``, ``"tool.search"``).
                     Capability names are the vocabulary supervisor
                     runtimes and policies query against.
        scope:       Coarse-grained operation kind. Used by tool-level
                     access checks alongside the name.
        description: Human-readable description; never queried
                     against — store free text here.
        metadata:    Opaque structured payload (e.g. rate limits,
                     deployment-tier requirements). Carried into
                     governance subjects unchanged.
    """

    name: str
    scope: CapabilityScope
    description: str = ""
    metadata: MetadataMap = field(default_factory=_empty_json_object)


@dataclass(frozen=True, slots=True)
class CapabilitySet:
    """Immutable, ordered collection of capabilities.

    Stored as a tuple to preserve declaration order (used by
    deterministic-iteration code paths).
    """

    capabilities: tuple[AgentCapability, ...] = ()

    def has(self, name: str) -> bool:
        """True iff a capability with that name is declared."""
        return any(c.name == name for c in self.capabilities)

    def names(self) -> tuple[str, ...]:
        """Sorted tuple of declared capability names."""
        return tuple(sorted({c.name for c in self.capabilities}))

    def required(self, names: frozenset[str]) -> frozenset[str]:
        """Return the subset of `names` NOT covered by this set."""
        declared = {c.name for c in self.capabilities}
        return frozenset(n for n in names if n not in declared)


_DEFAULT_MAX_TOOL_INVOCATIONS = 50


@dataclass(frozen=True, slots=True)
class ExecutionConstraints:
    """Operational constraints applied per execution.

    Attributes:
        max_tool_invocations: Hard cap on tool calls within this
                              execution.  Defaults to
                              ``_DEFAULT_MAX_TOOL_INVOCATIONS`` (50) so
                              that an agent without explicit constraints
                              cannot loop unboundedly.  Pass ``0`` only
                              if you explicitly need no cap.
        allowed_tools:        Whitelist of tool names; empty means
                              "any tool the capabilities permit".
                              Tool calls outside this list produce a
                              denied invocation envelope, never a
                              raised exception.
        timeout_ms:           Optional soft timeout. Sprint J does not
                              implement enforcement — the field is
                              recorded so a future supervisor runtime
                              can detect over-budget executions from
                              the trace.
        metadata:             Free-form operational metadata.
    """

    max_tool_invocations: int = _DEFAULT_MAX_TOOL_INVOCATIONS
    allowed_tools: tuple[str, ...] = ()
    timeout_ms: int | None = None
    metadata: MetadataMap = field(default_factory=_empty_json_object)

    def permits_tool(self, tool_name: str) -> bool:
        """True iff `tool_name` is allowed by the constraints.

        Empty `allowed_tools` is interpreted as "any" — capabilities
        still gate the actual call.
        """
        if not self.allowed_tools:
            return True
        return tool_name in self.allowed_tools


__all__ = [
    "AgentCapability",
    "CapabilitySet",
    "ExecutionConstraints",
    "_DEFAULT_MAX_TOOL_INVOCATIONS",
]
