"""Coordination contracts — typed dispatch surface.

* `messages`  — `CoordinationMessage` (the communicative artifact
                 callers hand to the runtime).
* `requests`  — `CoordinationDispatchRequest` (one dispatch input).
* `results`   — `CoordinationDispatchResult` (one dispatch output)
                 + `CoordinationDispatchOutcome` (typed terminal
                 outcome enum).
"""

from app.coordination.contracts.messages import CoordinationMessage
from app.coordination.contracts.requests import CoordinationDispatchRequest
from app.coordination.contracts.results import (
    CoordinationDispatchOutcome,
    CoordinationDispatchResult,
)

__all__ = [
    "CoordinationMessage",
    "CoordinationDispatchRequest",
    "CoordinationDispatchResult",
    "CoordinationDispatchOutcome",
]
