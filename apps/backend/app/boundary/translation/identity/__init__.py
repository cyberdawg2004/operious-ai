"""Translation-substrate identity primitives."""

from __future__ import annotations

import itertools
import secrets
import uuid
from typing import NewType


# ─── Type aliases ───────────────────────────────────────────────────


TranslationId = NewType("TranslationId", uuid.UUID)
TranslationLineageId = NewType("TranslationLineageId", uuid.UUID)
TranslationCorrelationId = NewType(
    "TranslationCorrelationId", uuid.UUID
)
TranslationTraceId = NewType("TranslationTraceId", uuid.UUID)
TranslationProviderId = NewType(
    "TranslationProviderId", uuid.UUID
)
TranslationReplayId = NewType("TranslationReplayId", uuid.UUID)
LocalizationId = NewType("LocalizationId", uuid.UUID)


# ─── Permanent namespaces ───────────────────────────────────────────


_TRANSLATION_NAMESPACE = uuid.UUID(
    "020ec1a0-0001-4001-8001-100000000001"
)
_LINEAGE_NAMESPACE = uuid.UUID(
    "020ec1a0-0002-4002-8002-100000000002"
)
_CORRELATION_NAMESPACE = uuid.UUID(
    "020ec1a0-0003-4003-8003-100000000003"
)
_TRACE_NAMESPACE = uuid.UUID(
    "020ec1a0-0004-4004-8004-100000000004"
)
_PROVIDER_NAMESPACE = uuid.UUID(
    "020ec1a0-0005-4005-8005-100000000005"
)
_REPLAY_NAMESPACE = uuid.UUID(
    "020ec1a0-0006-4006-8006-100000000006"
)
_LOCALIZATION_NAMESPACE = uuid.UUID(
    "020ec1a0-0007-4007-8007-100000000007"
)
_RUNTIME_BOOT_ID = secrets.token_urlsafe(32)
_RUNTIME_COUNTER = itertools.count()


def generate_translation_id() -> TranslationId:
    return TranslationId(uuid.uuid5(_TRANSLATION_NAMESPACE, _runtime_seed("translation")))


def generate_lineage_id() -> TranslationLineageId:
    return TranslationLineageId(uuid.uuid5(_LINEAGE_NAMESPACE, _runtime_seed("lineage")))


def generate_trace_id() -> TranslationTraceId:
    return TranslationTraceId(uuid.uuid5(_TRACE_NAMESPACE, _runtime_seed("trace")))


def generate_correlation_id() -> TranslationCorrelationId:
    return TranslationCorrelationId(uuid.uuid5(_CORRELATION_NAMESPACE, _runtime_seed("correlation")))


def generate_replay_id() -> TranslationReplayId:
    return TranslationReplayId(uuid.uuid5(_REPLAY_NAMESPACE, _runtime_seed("replay")))


def generate_localization_id() -> LocalizationId:
    return LocalizationId(uuid.uuid5(_LOCALIZATION_NAMESPACE, _runtime_seed("localization")))


def _runtime_seed(label: str) -> str:
    return f"runtime|{label}|{_RUNTIME_BOOT_ID}|{next(_RUNTIME_COUNTER)}"


def derive_translation_id(*, seed: str) -> TranslationId:
    if not seed:
        raise ValueError(
            "derive_translation_id requires non-empty seed"
        )
    return TranslationId(
        uuid.uuid5(_TRANSLATION_NAMESPACE, seed)
    )


def derive_lineage_id(*, seed: str) -> TranslationLineageId:
    if not seed:
        raise ValueError(
            "derive_lineage_id requires non-empty seed"
        )
    return TranslationLineageId(
        uuid.uuid5(_LINEAGE_NAMESPACE, seed)
    )


def derive_correlation_id(
    *, seed: str
) -> TranslationCorrelationId:
    if not seed:
        raise ValueError(
            "derive_correlation_id requires non-empty seed"
        )
    return TranslationCorrelationId(
        uuid.uuid5(_CORRELATION_NAMESPACE, seed)
    )


def derive_trace_id(*, seed: str) -> TranslationTraceId:
    if not seed:
        raise ValueError(
            "derive_trace_id requires non-empty seed"
        )
    return TranslationTraceId(
        uuid.uuid5(_TRACE_NAMESPACE, seed)
    )


def derive_provider_id(*, name: str) -> TranslationProviderId:
    if not name:
        raise ValueError(
            "derive_provider_id requires non-empty name"
        )
    return TranslationProviderId(
        uuid.uuid5(_PROVIDER_NAMESPACE, name)
    )


def derive_replay_id(*, seed: str) -> TranslationReplayId:
    if not seed:
        raise ValueError(
            "derive_replay_id requires non-empty seed"
        )
    return TranslationReplayId(
        uuid.uuid5(_REPLAY_NAMESPACE, seed)
    )


def derive_localization_id(*, seed: str) -> LocalizationId:
    if not seed:
        raise ValueError(
            "derive_localization_id requires non-empty seed"
        )
    return LocalizationId(
        uuid.uuid5(_LOCALIZATION_NAMESPACE, seed)
    )


__all__ = [
    "LocalizationId",
    "TranslationCorrelationId",
    "TranslationId",
    "TranslationLineageId",
    "TranslationProviderId",
    "TranslationReplayId",
    "TranslationTraceId",
    "derive_correlation_id",
    "derive_lineage_id",
    "derive_localization_id",
    "derive_provider_id",
    "derive_replay_id",
    "derive_trace_id",
    "derive_translation_id",
    "generate_correlation_id",
    "generate_lineage_id",
    "generate_localization_id",
    "generate_replay_id",
    "generate_trace_id",
    "generate_translation_id",
]
