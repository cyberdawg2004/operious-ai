"""Arbitration runtime — apex evaluator + aggregator.

* `aggregator` — `build_arbitration_decision`, the single authority
                  on "most-authoritative wins".
* `runtime`    — `OperationalArbitrationRuntime`.
"""

from app.arbitration.runtime.aggregator import (
    build_arbitration_decision,
)
from app.arbitration.runtime.runtime import (
    OperationalArbitrationRuntime,
)

__all__ = [
    "OperationalArbitrationRuntime",
    "build_arbitration_decision",
]
