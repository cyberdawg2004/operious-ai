"""Postgres implementation of voice persistence."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.boundary.voice.db.models import (
    VoiceEgressRecordRow,
    VoiceIngressRecordRow,
)
from app.boundary.voice.enums import (
    AudioFormat,
    VoiceDirection,
    VoiceProviderKind,
    VoiceStatus,
)
from app.boundary.voice.exceptions import VoicePersistenceError
from app.boundary.voice.identity import (
    VoiceCorrelationId,
    VoiceEventId,
    VoiceLineageId,
    VoiceReplayId,
    VoiceSynthesisId,
    VoiceTranscriptId,
    derive_lineage_id,
)
from app.boundary.voice.models.audio import VoiceAudioHandle
from app.boundary.voice.models.identity_bundle import VoiceIdentity
from app.boundary.voice.models.lineage import (
    VoiceLineage,
    VoiceLineageEntry,
)
from app.boundary.voice.models.replay import VoiceReplay
from app.boundary.voice.models.synthesis import VoiceSynthesis
from app.boundary.voice.models.transcript import VoiceTranscript
from app.boundary.voice.persistence.records import (
    VoiceEgressRecord,
    VoiceIngressRecord,
)
from app.boundary.voice.persistence.repository import (
    VoicePersistenceProtocol,
)
from app.db.repository import TenantScopedRepository

_SESSION_SCOPE_SQL = text(
    "SELECT set_config('app.current_tenant_id', :tenant_id, true)"
)
_CURRENT_TENANT_SQL = text(
    "SELECT current_setting('app.current_tenant_id', true)"
)


class PostgresVoicePersistence(
    TenantScopedRepository, VoicePersistenceProtocol
):
    """Postgres-backed voice persistence."""

    async def write_ingress(
        self, record: VoiceIngressRecord
    ) -> None:
        await self._scope_for_write(record.identity.tenant_id)
        row = _ingress_record_to_row(record)
        try:
            async with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError as exc:
            raise VoicePersistenceError(
                f"duplicate ingress voice record: {record.identity.event_id}"
            ) from exc

    async def get_ingress(
        self, event_id: VoiceEventId
    ) -> VoiceIngressRecord | None:
        await self._scope_for_read()
        stmt = select(VoiceIngressRecordRow).where(
            VoiceIngressRecordRow.record_id == event_id
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _row_to_ingress_record(row)

    async def write_egress(
        self, record: VoiceEgressRecord
    ) -> None:
        await self._scope_for_write(record.identity.tenant_id)
        row = _egress_record_to_row(record)
        try:
            async with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError as exc:
            raise VoicePersistenceError(
                f"duplicate egress voice record: {record.identity.event_id}"
            ) from exc

    async def get_egress(
        self, event_id: VoiceEventId
    ) -> VoiceEgressRecord | None:
        await self._scope_for_read()
        stmt = select(VoiceEgressRecordRow).where(
            VoiceEgressRecordRow.record_id == event_id
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _row_to_egress_record(row)

    async def list_lineage_entries(
        self, correlation_id: VoiceCorrelationId
    ) -> tuple[VoiceLineageEntry, ...]:
        await self._scope_for_read()
        ingress_stmt = select(VoiceIngressRecordRow).where(
            VoiceIngressRecordRow.correlation_id == correlation_id
        )
        egress_stmt = select(VoiceEgressRecordRow).where(
            VoiceEgressRecordRow.correlation_id == correlation_id
        )
        ingress_rows = (
            await self.session.execute(ingress_stmt)
        ).scalars().all()
        egress_rows = (
            await self.session.execute(egress_stmt)
        ).scalars().all()
        entries = [
            _lineage_entry_from_metadata(row.metadata_json)
            for row in (*ingress_rows, *egress_rows)
        ]
        return tuple(sorted(entries, key=lambda entry: entry.sequence))

    async def reconstruct_lineage(
        self, correlation_id: VoiceCorrelationId
    ) -> VoiceLineage | None:
        entries = await self.list_lineage_entries(correlation_id)
        if not entries:
            return None
        return VoiceLineage(
            lineage_id=derive_lineage_id(seed=str(correlation_id)),
            correlation_id=correlation_id,
            entries=entries,
        )

    async def _scope_for_write(self, tenant_id: str | None) -> None:
        if tenant_id is None or tenant_id == "":
            raise VoicePersistenceError(
                "Postgres voice persistence requires tenant_id"
            )
        await self.session.execute(
            _SESSION_SCOPE_SQL, {"tenant_id": tenant_id}
        )

    async def _scope_for_read(self) -> None:
        tenant_id = await self.session.scalar(_CURRENT_TENANT_SQL)
        await self.session.execute(
            _SESSION_SCOPE_SQL, {"tenant_id": str(tenant_id or "")}
        )


def _ingress_record_to_row(
    record: VoiceIngressRecord,
) -> VoiceIngressRecordRow:
    metadata = _ingress_metadata(record)
    return VoiceIngressRecordRow(
        record_id=uuid.UUID(str(record.identity.event_id)),
        tenant_id=_tenant_id(record.identity),
        session_id=_required_uuid(metadata, "session_id"),
        direction=record.lineage_entry.direction.value,
        status=VoiceStatus.COMPLETED.value,
        transcript_text=record.transcript.text,
        audio_handle_id=_audio_handle_id(record.transcript.audio),
        provider_kind=_provider_kind(record.transcript.audio),
        provider_model=record.transcript.provider_name,
        duration_ms=record.transcript.audio.duration_ms,
        fingerprint_sha256=record.transcript.transcript_fingerprint,
        lineage_id=uuid.UUID(str(record.identity.lineage_id)),
        correlation_id=uuid.UUID(str(record.identity.correlation_id)),
        runtime_instance_id=_optional_uuid(
            record.transcript.attributes.get("runtime_instance_id")
        ),
        created_at=record.transcript.captured_at,
        metadata_json=metadata,
    )


def _egress_record_to_row(
    record: VoiceEgressRecord,
) -> VoiceEgressRecordRow:
    metadata = _egress_metadata(record)
    return VoiceEgressRecordRow(
        record_id=uuid.UUID(str(record.identity.event_id)),
        tenant_id=_tenant_id(record.identity),
        session_id=_required_uuid(metadata, "session_id"),
        direction=record.lineage_entry.direction.value,
        status=VoiceStatus.COMPLETED.value,
        synthesis_text=record.synthesis.source_text,
        audio_handle_id=_audio_handle_id(record.synthesis.audio),
        provider_kind=_provider_kind(record.synthesis.audio),
        provider_model=record.synthesis.provider_name,
        duration_ms=record.synthesis.audio.duration_ms,
        fingerprint_sha256=record.synthesis.audio_fingerprint,
        lineage_id=uuid.UUID(str(record.identity.lineage_id)),
        correlation_id=uuid.UUID(str(record.identity.correlation_id)),
        runtime_instance_id=_optional_uuid(
            record.synthesis.attributes.get("runtime_instance_id")
        ),
        governance_decision_id=_required_uuid(
            metadata, "governance_decision_id"
        ),
        created_at=record.synthesis.captured_at,
        metadata_json=metadata,
    )


def _row_to_ingress_record(
    row: VoiceIngressRecordRow,
) -> VoiceIngressRecord:
    metadata = row.metadata_json
    audio = _audio_from_metadata(metadata)
    captured_at = row.created_at
    transcript = VoiceTranscript(
        transcript_id=VoiceTranscriptId(
            _required_uuid(metadata, "transcript_id")
        ),
        text=row.transcript_text or "",
        language=str(metadata.get("language") or audio.language),
        confidence=float(metadata.get("confidence") or 1.0),
        provider_name=row.provider_model or "unknown",
        audio_fingerprint=str(metadata.get("audio_fingerprint") or ""),
        transcript_fingerprint=row.fingerprint_sha256 or "",
        audio=audio,
        captured_at=captured_at,
        attributes=dict(metadata.get("transcript_attributes") or {}),
    )
    identity = _identity_from_metadata(row, metadata)
    replay = _replay_from_metadata(metadata, captured_at)
    return VoiceIngressRecord(
        identity=identity,
        transcript=transcript,
        lineage_entry=_lineage_entry_from_metadata(metadata),
        replay=replay,
    )


def _row_to_egress_record(
    row: VoiceEgressRecordRow,
) -> VoiceEgressRecord:
    metadata = row.metadata_json
    audio = _audio_from_metadata(metadata)
    captured_at = row.created_at
    synthesis = VoiceSynthesis(
        synthesis_id=VoiceSynthesisId(
            _required_uuid(metadata, "synthesis_id")
        ),
        source_text=row.synthesis_text or "",
        target_language=str(metadata.get("language") or audio.language),
        provider_name=row.provider_model or "unknown",
        text_fingerprint=str(metadata.get("text_fingerprint") or ""),
        audio_fingerprint=row.fingerprint_sha256 or "",
        audio=audio,
        captured_at=captured_at,
        attributes=dict(metadata.get("synthesis_attributes") or {}),
    )
    identity = _identity_from_metadata(row, metadata)
    replay = _replay_from_metadata(metadata, captured_at)
    return VoiceEgressRecord(
        identity=identity,
        synthesis=synthesis,
        lineage_entry=_lineage_entry_from_metadata(metadata),
        replay=replay,
    )


def _ingress_metadata(record: VoiceIngressRecord) -> dict[str, Any]:
    return _jsonable(
        {
            "record_type": "ingress",
            "session_id": record.transcript.attributes.get("session_id"),
            "request_id": record.identity.request_id,
            "seed": record.identity.seed,
            "lineage_id": str(record.identity.lineage_id),
            "correlation_id": str(record.identity.correlation_id),
            "transcript_id": str(record.transcript.transcript_id),
            "language": record.transcript.language,
            "confidence": record.transcript.confidence,
            "audio_fingerprint": record.transcript.audio_fingerprint,
            "transcript_fingerprint": (
                record.transcript.transcript_fingerprint
            ),
            "audio": _audio_metadata(record.transcript.audio),
            "transcript_attributes": dict(record.transcript.attributes),
            "lineage_entry": _lineage_metadata(record.lineage_entry),
            "replay": _replay_metadata(record.replay),
        }
    )


def _egress_metadata(record: VoiceEgressRecord) -> dict[str, Any]:
    return _jsonable(
        {
            "record_type": "egress",
            "session_id": record.synthesis.attributes.get("session_id"),
            "governance_decision_id": (
                record.synthesis.attributes.get(
                    "governance_decision_id"
                )
            ),
            "request_id": record.identity.request_id,
            "seed": record.identity.seed,
            "lineage_id": str(record.identity.lineage_id),
            "correlation_id": str(record.identity.correlation_id),
            "synthesis_id": str(record.synthesis.synthesis_id),
            "language": record.synthesis.target_language,
            "text_fingerprint": record.synthesis.text_fingerprint,
            "audio_fingerprint": record.synthesis.audio_fingerprint,
            "audio": _audio_metadata(record.synthesis.audio),
            "synthesis_attributes": dict(record.synthesis.attributes),
            "lineage_entry": _lineage_metadata(record.lineage_entry),
            "replay": _replay_metadata(record.replay),
        }
    )


def _audio_metadata(audio: VoiceAudioHandle) -> dict[str, Any]:
    return {
        "handle": audio.handle,
        "audio_format": audio.audio_format.value,
        "sample_rate_hz": audio.sample_rate_hz,
        "duration_ms": audio.duration_ms,
        "language": audio.language,
        "attributes": dict(audio.attributes),
    }


def _lineage_metadata(entry: VoiceLineageEntry) -> dict[str, Any]:
    return {
        "sequence": entry.sequence,
        "direction": entry.direction.value,
        "audio_fingerprint": entry.audio_fingerprint,
        "transcript_fingerprint": entry.transcript_fingerprint,
        "provider_name": entry.provider_name,
        "seed": entry.seed,
    }


def _replay_metadata(replay: VoiceReplay) -> dict[str, Any]:
    return {
        "replay_id": str(replay.replay_id),
        "seed": replay.seed,
        "audio_fingerprint": replay.audio_fingerprint,
        "transcript_fingerprint": replay.transcript_fingerprint,
        "provider_name": replay.provider_name,
        "captured_at": replay.captured_at.isoformat(),
        "attributes": dict(replay.attributes),
    }


def _lineage_entry_from_metadata(
    metadata: Mapping[str, Any],
) -> VoiceLineageEntry:
    data = dict(metadata.get("lineage_entry") or {})
    return VoiceLineageEntry(
        sequence=int(data.get("sequence") or 0),
        direction=VoiceDirection(str(data.get("direction") or "ingress")),
        audio_fingerprint=str(data.get("audio_fingerprint") or ""),
        transcript_fingerprint=str(
            data.get("transcript_fingerprint") or ""
        ),
        provider_name=str(data.get("provider_name") or "unknown"),
        seed=str(data.get("seed") or metadata.get("seed") or "unknown"),
    )


def _identity_from_metadata(
    row: VoiceIngressRecordRow | VoiceEgressRecordRow,
    metadata: Mapping[str, Any],
) -> VoiceIdentity:
    return VoiceIdentity(
        event_id=VoiceEventId(row.record_id),
        lineage_id=VoiceLineageId(_required_row_uuid(row.lineage_id)),
        correlation_id=VoiceCorrelationId(
            _required_row_uuid(row.correlation_id)
        ),
        seed=str(metadata.get("seed") or row.record_id),
        request_id=(
            str(metadata["request_id"])
            if metadata.get("request_id") is not None
            else None
        ),
        tenant_id=row.tenant_id,
    )


def _replay_from_metadata(
    metadata: Mapping[str, Any],
    captured_at: datetime,
) -> VoiceReplay:
    data = dict(metadata.get("replay") or {})
    return VoiceReplay(
        replay_id=VoiceReplayId(
            uuid.UUID(
                str(
                    data.get("replay_id")
                    or uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        str(metadata.get("seed") or "voice-replay"),
                    )
                )
            )
        ),
        seed=str(data.get("seed") or metadata.get("seed") or "unknown"),
        audio_fingerprint=str(data.get("audio_fingerprint") or ""),
        transcript_fingerprint=str(
            data.get("transcript_fingerprint") or ""
        ),
        provider_name=str(data.get("provider_name") or "unknown"),
        captured_at=captured_at,
        attributes=dict(data.get("attributes") or {}),
    )


def _audio_from_metadata(metadata: Mapping[str, Any]) -> VoiceAudioHandle:
    data = dict(metadata.get("audio") or {})
    return VoiceAudioHandle(
        handle=str(data.get("handle") or "unknown"),
        audio_format=AudioFormat(
            str(data.get("audio_format") or AudioFormat.UNKNOWN.value)
        ),
        sample_rate_hz=int(data.get("sample_rate_hz") or 1),
        duration_ms=int(data.get("duration_ms") or 0),
        language=str(data.get("language") or "und"),
        attributes=dict(data.get("attributes") or {}),
    )


def _tenant_id(identity: VoiceIdentity) -> str:
    if identity.tenant_id is None or identity.tenant_id == "":
        raise VoicePersistenceError("voice records require tenant_id")
    return identity.tenant_id


def _audio_handle_id(audio: VoiceAudioHandle) -> uuid.UUID | None:
    value = audio.attributes.get("audio_handle_id")
    if value is not None:
        return _optional_uuid(value)
    return uuid.uuid5(uuid.NAMESPACE_URL, audio.handle)


def _provider_kind(audio: VoiceAudioHandle) -> str:
    raw = audio.attributes.get("provider_kind")
    if isinstance(raw, str) and raw:
        return raw
    return VoiceProviderKind.DETERMINISTIC_STUB.value


def _required_uuid(metadata: Mapping[str, Any], key: str) -> uuid.UUID:
    value = metadata.get(key)
    if value is None or str(value) == "":
        raise VoicePersistenceError(f"voice record missing {key}")
    return uuid.UUID(str(value))


def _optional_uuid(value: object) -> uuid.UUID | None:
    if value is None or str(value) == "":
        return None
    return uuid.UUID(str(value))


def _required_row_uuid(value: uuid.UUID | None) -> uuid.UUID:
    if value is None:
        raise VoicePersistenceError("voice row is missing required UUID")
    return value


def _jsonable(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(k): _jsonable(v) for k, v in mapping.items()}
    if isinstance(value, (list, tuple)):
        sequence = cast(Sequence[object], value)
        return [_jsonable(item) for item in sequence]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


__all__ = ["PostgresVoicePersistence"]
