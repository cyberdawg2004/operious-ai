"""Translation adapter interface and reference deterministic adapters.

Renamed from ``app.boundary.translation.providers`` to
``app.boundary.translation.adapters`` in PR-A3 so the package
name aligns with the constitutional ``boundary/adapters/`` apex
layout. Class names (``BaseTranslationProvider`` etc.) retain
the ``Provider`` suffix for now — that semantic rename is a
separate follow-up to keep PR-A3 strictly mechanical.
"""

from app.boundary.translation.adapters.base import (
    BaseTranslationProvider,
    TranslationProviderRequest,
    TranslationProviderResponse,
)
from app.boundary.translation.adapters.identity import (
    IdentityTranslationProvider,
)
from app.boundary.translation.adapters.stub import (
    DeterministicStubTranslationProvider,
)

__all__ = [
    "BaseTranslationProvider",
    "DeterministicStubTranslationProvider",
    "IdentityTranslationProvider",
    "TranslationProviderRequest",
    "TranslationProviderResponse",
]
