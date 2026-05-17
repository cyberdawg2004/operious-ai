"""Supervisor runtime.

* `view_builder` — pure function: envelope/records → `InspectionView`.
* `runtime`      — `SupervisorRuntime` (apex inspector).
"""

from app.supervisor.runtime.runtime import SupervisorRuntime
from app.supervisor.runtime.view_builder import (
    build_inspection_view_from_envelope,
    build_inspection_view_from_records,
)

__all__ = [
    "SupervisorRuntime",
    "build_inspection_view_from_envelope",
    "build_inspection_view_from_records",
]
