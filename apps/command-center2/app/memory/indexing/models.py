"""Document ingestion result types.

`IngestionResult` is the durable summary of one successful pipeline
run. It is what the indexing service returns; the orchestration task
wrapping the service exposes it through `TaskResult.output`.

`IngestionStatus` records the operational outcome — the difference
between "ingested fresh" and "skipped because identical content was
already indexed" matters for downstream metrics and idempotency tests.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping


class IngestionStatus(str, Enum):
    """Operational outcome of one ingestion call."""
    INDEXED = "indexed"
    SKIPPED_DUPLICATE = "skipped_duplicate"


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Summary record of one ingestion pipeline execution."""

    document_id: uuid.UUID
    source: str
    content_hash: str
    chunk_count: int
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    vector_index_name: str
    status: IngestionStatus
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        """Render as a JSON-safe mapping for task output / API responses."""
        return {
            "document_id": str(self.document_id),
            "source": self.source,
            "content_hash": self.content_hash,
            "chunk_count": self.chunk_count,
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "embedding_dimensions": self.embedding_dimensions,
            "vector_index_name": self.vector_index_name,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat(),
            "latency_ms": self.latency_ms,
            "request_id": self.request_id,
            "metadata": dict(self.metadata),
        }


__all__ = ["IngestionResult", "IngestionStatus"]
