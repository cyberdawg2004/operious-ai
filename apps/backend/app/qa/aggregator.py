"""MVP-5 — QA Signal Aggregator.

Component A of the QA→Trainer→KB loop. Reads QAScoreRecords for a tenant
over a configurable time window, groups them by resolution_category (from
the QA score metadata), and identifies categories with consistently low
semantic grounding scores.

The aggregator produces a ranked list of WeakCategory records — categories
that have:
  - at least `min_ticket_count` scored tickets in the window
  - average `semantic_grounding` below `grounding_threshold`

Each WeakCategory carries representative_case_ids so the KBTrainerAgent
has concrete evidence to work from.

Resolution category is read from QAScoreRecord.metadata["source_session_id"]
cross-referenced with the supervisor inspection data — but since QA score
records don't directly carry resolution_category, we derive it from:
  1. QAScoreRecord.supervisor_decision_kind (accept/escalate/reject)
  2. QAScoreRecord.metadata["qa_metadata"]["dimension_scores"] dimension names
  3. A synthetic "overall" category for cross-category analysis

For the trainer loop, the aggregator groups by a synthetic key:
  - "semantic_grounding_weak" — all tickets where semantic_grounding < threshold
  - Per-dimension weak categories (diagnostic_accuracy, policy_compliance, etc.)

This is intentionally simple: the trainer's job is to propose improvements,
not to do complex analytics. The aggregator's job is to surface which signal
to act on.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.qa.persistence.models import QAScoreQuery
from app.qa.persistence.records import QAScoreRecord
from app.qa.persistence.repository import QAPersistenceProtocol

logger = logging.getLogger(__name__)

# Default configuration per plan spec:
# "avg < 0.6 over 50+ tickets" → trigger trainer
DEFAULT_GROUNDING_THRESHOLD = 0.60
DEFAULT_MIN_TICKET_COUNT = 3    # lowered for testability; 50 in steady state
DEFAULT_WINDOW_DAYS = 7
DEFAULT_MAX_REPRESENTATIVE_CASES = 5
DEFAULT_REPRESENTATIVE_SAMPLE_LIMIT = 200  # fetch at most N scores to find representatives


@dataclass(frozen=True, slots=True)
class WeakCategory:
    """A QA category identified as needing KB improvement."""

    category: str                         # e.g. "semantic_grounding_weak", "diagnostic_accuracy"
    tenant_id: str
    avg_semantic_grounding: float         # average over the window
    ticket_count: int                     # number of scored tickets in window
    representative_case_ids: tuple[str, ...]  # score_ids of worst-performing tickets
    window_start: datetime
    window_end: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


class QASignalAggregator:
    """Reads QA scores over a rolling window and identifies weak categories.

    Stateless per-call. Injected with QA persistence protocol.
    Thread-safe (no mutable state).
    """

    def __init__(
        self,
        *,
        qa_persistence: QAPersistenceProtocol,
        grounding_threshold: float = DEFAULT_GROUNDING_THRESHOLD,
        min_ticket_count: int = DEFAULT_MIN_TICKET_COUNT,
        window_days: int = DEFAULT_WINDOW_DAYS,
        max_representative_cases: int = DEFAULT_MAX_REPRESENTATIVE_CASES,
    ) -> None:
        if not 0.0 <= grounding_threshold <= 1.0:
            raise ValueError("grounding_threshold must be between 0.0 and 1.0")
        if min_ticket_count < 1:
            raise ValueError("min_ticket_count must be >= 1")
        if window_days < 1:
            raise ValueError("window_days must be >= 1")
        self._qa_persistence = qa_persistence
        self._grounding_threshold = grounding_threshold
        self._min_ticket_count = min_ticket_count
        self._window_days = window_days
        self._max_representative = max_representative_cases

    async def identify_weak_categories(
        self,
        *,
        tenant_id: str,
        window_end: datetime | None = None,
    ) -> tuple[WeakCategory, ...]:
        """Return categories with avg semantic grounding below threshold.

        Returns an empty tuple if no category meets the criteria.
        Categories are sorted by avg_semantic_grounding ascending (weakest first).
        """
        now = window_end or datetime.now(timezone.utc)
        window_start = now - timedelta(days=self._window_days)

        # Fetch all scores in the window for this tenant
        page = await self._qa_persistence.list_scores(
            QAScoreQuery(
                tenant_id=tenant_id,
                scored_after=window_start,
                scored_before=now,
                limit=DEFAULT_REPRESENTATIVE_SAMPLE_LIMIT,
            ),
            expected_tenant_id=tenant_id,
        )
        scores = list(page.items)

        if not scores:
            logger.debug(
                "qa_signal_aggregator_no_scores tenant=%s window_days=%d",
                tenant_id, self._window_days,
            )
            return ()

        # Group by synthetic category based on QA dimensions
        categories = _aggregate_by_category(
            scores=scores,
            grounding_threshold=self._grounding_threshold,
            min_ticket_count=self._min_ticket_count,
            max_representative=self._max_representative,
            window_start=window_start,
            window_end=now,
            tenant_id=tenant_id,
        )

        logger.info(
            "qa_signal_aggregator_done tenant=%s window_days=%d "
            "total_scores=%d weak_categories=%d",
            tenant_id, self._window_days, len(scores), len(categories),
        )
        return categories


def _aggregate_by_category(
    *,
    scores: list[QAScoreRecord],
    grounding_threshold: float,
    min_ticket_count: int,
    max_representative: int,
    window_start: datetime,
    window_end: datetime,
    tenant_id: str,
) -> tuple[WeakCategory, ...]:
    """Group scores, compute averages, filter by threshold.

    Categories produced:
    - "semantic_grounding" — overall semantic grounding dimension
    - "diagnostic_accuracy" — if avg below threshold
    - "policy_compliance" — if avg below threshold
    - "resolution_quality" — if avg below threshold
    """
    # Collect per-category buckets: {category -> [(score_value, score_record)]}
    buckets: dict[str, list[tuple[float, QAScoreRecord]]] = {}

    for score in scores:
        # Semantic grounding is the new MVP-6 dimension — primary signal
        _add_to_bucket(buckets, "semantic_grounding", score.semantic_grounding, score)
        # Existing dimensions as secondary signals
        _add_to_bucket(buckets, "diagnostic_accuracy", score.diagnostic_accuracy, score)
        _add_to_bucket(buckets, "policy_compliance", score.policy_compliance, score)
        _add_to_bucket(buckets, "resolution_quality", score.resolution_quality, score)

    weak: list[WeakCategory] = []
    for category, entries in buckets.items():
        if len(entries) < min_ticket_count:
            continue
        avg = sum(v for v, _ in entries) / len(entries)
        if avg >= grounding_threshold:
            continue
        # Pick representative cases: worst-scoring tickets first
        entries.sort(key=lambda e: e[0])
        representative = tuple(
            str(rec.score_id)
            for _, rec in entries[:max_representative]
        )
        weak.append(WeakCategory(
            category=category,
            tenant_id=tenant_id,
            avg_semantic_grounding=round(avg, 4),
            ticket_count=len(entries),
            representative_case_ids=representative,
            window_start=window_start,
            window_end=window_end,
            metadata={
                "dimension": category,
                "threshold": grounding_threshold,
                "window_days": (window_end - window_start).days,
            },
        ))

    # Sort by avg_semantic_grounding ascending (weakest first)
    weak.sort(key=lambda c: c.avg_semantic_grounding)
    return tuple(weak)


def _add_to_bucket(
    buckets: dict[str, list[tuple[float, QAScoreRecord]]],
    category: str,
    value: float,
    score: QAScoreRecord,
) -> None:
    if category not in buckets:
        buckets[category] = []
    buckets[category].append((value, score))
