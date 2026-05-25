"""Batch boundary-ingest request and response schemas."""

from __future__ import annotations

import enum
import os
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

_DEFAULT_MAX_BATCH_SIZE = 500


def max_batch_size() -> int:
    raw = os.environ.get("BATCH_INGEST_MAX_BATCH_SIZE")
    if raw is None:
        raw = os.environ.get("MAX_BATCH_SIZE")
    if raw is None:
        return _DEFAULT_MAX_BATCH_SIZE
    try:
        parsed = int(raw)
    except ValueError:
        return _DEFAULT_MAX_BATCH_SIZE
    return parsed if parsed > 0 else _DEFAULT_MAX_BATCH_SIZE


class BatchIngestItem(BaseModel):
    channel_type: str
    source_id: str
    external_message_id: str
    subject: str | None = None
    body: str
    received_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    tenant_id: str | None = None


class BatchIngestRequest(BaseModel):
    items: list[BatchIngestItem]

    @field_validator("items")
    @classmethod
    def validate_items(
        cls, value: list[BatchIngestItem]
    ) -> list[BatchIngestItem]:
        if not value:
            raise ValueError("items must not be empty")
        limit = max_batch_size()
        if len(value) > limit:
            raise ValueError(f"items must contain at most {limit} records")
        return value


class BatchItemStatus(str, enum.Enum):
    ACCEPTED = "ACCEPTED"
    DUPLICATE = "DUPLICATE"
    REJECTED = "REJECTED"


class BatchIngestItemResult(BaseModel):
    index: int
    external_message_id: str
    status: BatchItemStatus
    boundary_id: str | None = None
    reason: str | None = None


class BatchIngestResponse(BaseModel):
    total: int
    accepted: int
    duplicate: int
    rejected: int
    results: list[BatchIngestItemResult]


__all__ = [
    "BatchIngestItem",
    "BatchIngestItemResult",
    "BatchIngestRequest",
    "BatchIngestResponse",
    "BatchItemStatus",
    "max_batch_size",
]
