"""Typed runtime results for the translation substrate."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.boundary.translation.enums import TranslationStatus
from app.boundary.translation.models.canonical import (
    CanonicalLanguageProjection,
)
from app.boundary.translation.models.identity import (
    TranslationIdentity,
)
from app.boundary.translation.models.localization import (
    LocalizationMetadata,
)
from app.boundary.translation.models.replay import (
    TranslationReplay,
)
from app.boundary.translation.models.validation import (
    TranslationValidation,
)


@dataclass(frozen=True, slots=True)
class _BaseResult:
    sequence: int
    runtime_instance_id: uuid.UUID
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    status: TranslationStatus
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IngressTranslateResult(_BaseResult):
    identity: TranslationIdentity | None = None
    projection: CanonicalLanguageProjection | None = None
    validation: TranslationValidation | None = None
    replay: TranslationReplay | None = None


@dataclass(frozen=True, slots=True)
class EgressLocalizeResult(_BaseResult):
    identity: TranslationIdentity | None = None
    localization: LocalizationMetadata | None = None
    validation: TranslationValidation | None = None
    replay: TranslationReplay | None = None


__all__ = [
    "EgressLocalizeResult",
    "IngressTranslateResult",
]
