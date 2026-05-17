"""Voice-substrate runtime contracts."""

from app.boundary.voice.contracts.requests import (
    EgressSynthesizeRequest,
    IngressTranscribeRequest,
)
from app.boundary.voice.contracts.results import (
    EgressSynthesizeResult,
    IngressTranscribeResult,
)

__all__ = [
    "EgressSynthesizeRequest",
    "EgressSynthesizeResult",
    "IngressTranscribeRequest",
    "IngressTranscribeResult",
]
