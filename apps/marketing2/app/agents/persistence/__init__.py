"""Agent runtime persistence — contracts only.

Sprint J ships the **persistence contract**, not a storage backend.
Three pieces:

* `records.py`    — frozen `to_dict` / `from_dict` records that
                    persistence backends serialize.
* `repository.py` — `BaseAgentRepository` Protocol every backend
                    implements.
* `memory.py`     — `InMemoryAgentRepository` reference impl
                    (tests + dev environments).

Append-only writes. No ORM coupling. Future production backends ship
in new modules behind the same Protocol; the substrate is untouched.

The records mirror the structure of `AgentExecutionTrace` and
`ToolInvocationTrace` but use string identifiers for cross-system
portability — same discipline as the governance persistence layer.
"""

from app.agents.persistence.memory import InMemoryAgentRepository
from app.agents.persistence.models import ExecutionQuery, RecordPage
from app.agents.persistence.records import (
    AgentExecutionRecord,
    StateTransitionRecord,
    ToolInvocationRecord,
)
from app.agents.persistence.repository import BaseAgentRepository
from app.agents.persistence.serializers import (
    execution_envelope_to_records,
    execution_trace_to_record,
    tool_trace_to_record,
)

__all__ = [
    "AgentExecutionRecord",
    "ToolInvocationRecord",
    "StateTransitionRecord",
    "ExecutionQuery",
    "RecordPage",
    "BaseAgentRepository",
    "InMemoryAgentRepository",
    "execution_trace_to_record",
    "tool_trace_to_record",
    "execution_envelope_to_records",
]
