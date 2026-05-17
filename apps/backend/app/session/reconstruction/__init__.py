"""Session reconstruction — deterministic historical rebuild.

CRITICAL: reconstruction is **historical reconstruction**, not
re-execution. The reconstruction pipeline rebuilds the continuity
state from immutable persistence records — it never invokes
agents, dispatches coordination, or mutates external state.
"""

from app.session.reconstruction.reconstructor import (
    SessionReconstructor,
)

__all__ = ["SessionReconstructor"]
