"""Translation-substrate runtime contracts."""

from app.boundary.translation.contracts.requests import (
    EgressLocalizeRequest,
    IngressTranslateRequest,
)
from app.boundary.translation.contracts.results import (
    EgressLocalizeResult,
    IngressTranslateResult,
)

__all__ = [
    "EgressLocalizeRequest",
    "EgressLocalizeResult",
    "IngressTranslateRequest",
    "IngressTranslateResult",
]
