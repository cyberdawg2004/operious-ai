"""Typed execution result JSONB envelope."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, cast


CURRENT_SCHEMA_VERSION = "1"
PRE_VERSIONED_SCHEMA_VERSION = "0"


def _empty_metadata() -> dict[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class ExecutionResultEnvelope(Mapping[str, Any]):
    """Typed wrapper for execution result JSONB storage.

    ``schema_version`` keeps reads forward-compatible with rows written
    before result payloads were versioned.
    """

    schema_version: str = CURRENT_SCHEMA_VERSION

    diagnostic_category: str | None = None
    diagnostic_confidence: float | None = None
    diagnostic_summary: str | None = None

    governance_decision_id: str | None = None
    governance_decision: str | None = None

    resolution_proposal_id: str | None = None
    resolution_draft_id: str | None = None

    error_code: str | None = None
    error_message: str | None = None

    metadata: dict[str, Any] = field(default_factory=_empty_metadata)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSONB-ready dictionary."""
        return {
            "_schema_version": self.schema_version,
            "diagnostic_category": self.diagnostic_category,
            "diagnostic_confidence": self.diagnostic_confidence,
            "diagnostic_summary": self.diagnostic_summary,
            "governance_decision_id": self.governance_decision_id,
            "governance_decision": self.governance_decision,
            "resolution_proposal_id": self.resolution_proposal_id,
            "resolution_draft_id": self.resolution_draft_id,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any] | "ExecutionResultEnvelope"
    ) -> "ExecutionResultEnvelope":
        """Deserialize from stored JSONB.

        Older records may lack ``_schema_version`` and may use the
        legacy diagnostic keys ``category``, ``confidence``, and
        ``summary``. Unknown keys are preserved under ``metadata``.
        """
        if isinstance(data, cls):
            return data
        known_keys = {
            "_schema_version",
            "diagnostic_category",
            "diagnostic_confidence",
            "diagnostic_summary",
            "governance_decision_id",
            "governance_decision",
            "resolution_proposal_id",
            "resolution_draft_id",
            "error_code",
            "error_message",
            "metadata",
        }
        extra = {key: value for key, value in data.items() if key not in known_keys}
        return cls(
            schema_version=_optional_str(
                data.get("_schema_version")
            )
            or PRE_VERSIONED_SCHEMA_VERSION,
            diagnostic_category=_optional_str(
                data.get("diagnostic_category")
            )
            or _optional_str(data.get("category")),
            diagnostic_confidence=_first_float(
                _optional_float(data.get("diagnostic_confidence")),
                _optional_float(data.get("confidence")),
            ),
            diagnostic_summary=_optional_str(
                data.get("diagnostic_summary")
            )
            or _optional_str(data.get("summary")),
            governance_decision_id=_optional_str(
                data.get("governance_decision_id")
            ),
            governance_decision=_optional_str(data.get("governance_decision")),
            resolution_proposal_id=_optional_str(
                data.get("resolution_proposal_id")
            ),
            resolution_draft_id=_optional_str(
                data.get("resolution_draft_id")
            ),
            error_code=_optional_str(data.get("error_code")),
            error_message=_optional_str(data.get("error_message")),
            metadata={**_metadata(data.get("metadata")), **extra},
        )

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ExecutionResultEnvelope):
            return self.to_dict() == other.to_dict()
        if isinstance(other, Mapping):
            other_payload = dict(cast(Mapping[str, Any], other))
            if "_schema_version" in other_payload:
                return self.to_dict() == other_payload
            return self._legacy_payload() == other_payload
        return NotImplemented

    def _legacy_payload(self) -> dict[str, Any]:
        payload = dict(self.metadata)
        if self.diagnostic_category is not None:
            payload["category"] = self.diagnostic_category
        if self.diagnostic_confidence is not None:
            payload["confidence"] = self.diagnostic_confidence
        if self.diagnostic_summary is not None:
            payload["summary"] = self.diagnostic_summary
        if self.governance_decision_id is not None:
            payload["governance_decision_id"] = self.governance_decision_id
        if self.error_message is not None:
            payload.setdefault("message", self.error_message)
        return payload


def _optional_str(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if value is None:
        return None
    return str(value)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _first_float(*values: float | None) -> float | None:
    for value in values:
        if value is not None:
            return value
    return None


def _metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(cast(Mapping[str, Any], value))
    return {}


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "ExecutionResultEnvelope",
    "PRE_VERSIONED_SCHEMA_VERSION",
]
