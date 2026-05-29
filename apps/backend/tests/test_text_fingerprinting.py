from __future__ import annotations

import time
import uuid
from typing import Any, cast

import pytest

from app.boundary.identity import as_ingress_id
from app.boundary.persistence import InMemoryBoundaryPersistence
from app.semantic import (
    FINGERPRINT_VERSION,
    NUM_HASH_FUNCTIONS,
    TextFingerprinter,
)
from app.services.ticket_ingress_service import TicketIngressService


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class _ExplodingFingerprinter(TextFingerprinter):
    def fingerprint(self, text: str) -> tuple[int, ...]:
        raise RuntimeError("fingerprint boom")


def _zeros() -> tuple[int, ...]:
    return tuple(0 for _ in range(NUM_HASH_FUNCTIONS))


def test_fingerprint_is_deterministic() -> None:
    fp = TextFingerprinter()
    text = "the charger stopped working after one week of use"

    signatures = [fp.fingerprint(text) for _ in range(3)]

    assert signatures[0] == signatures[1] == signatures[2]


def test_fingerprint_returns_128_elements() -> None:
    fp = TextFingerprinter()

    assert len(fp.fingerprint("charger stopped working")) == NUM_HASH_FUNCTIONS


def test_similar_texts_high_jaccard() -> None:
    fp = TextFingerprinter()
    text_a = (
        "the charger stopped working after one week of use "
        "i need a replacement or refund"
    )
    text_b = (
        "the charger stopped working after one week of use "
        "i need a replacement or refund please"
    )

    similarity = fp.jaccard_similarity(
        fp.fingerprint(text_a),
        fp.fingerprint(text_b),
    )

    assert similarity > 0.5


def test_different_texts_low_jaccard() -> None:
    fp = TextFingerprinter()
    charger = (
        "the charger stopped working after one week of use "
        "i need a replacement or refund"
    )
    shipping = (
        "when will my shipment arrive because tracking has not updated "
        "since monday morning"
    )

    similarity = fp.jaccard_similarity(
        fp.fingerprint(charger),
        fp.fingerprint(shipping),
    )

    assert similarity < 0.3


def test_empty_text_returns_zeros() -> None:
    fp = TextFingerprinter()

    assert fp.fingerprint("") == _zeros()
    assert fp.fingerprint("  ") == _zeros()


def test_short_text_below_ngram_threshold() -> None:
    fp = TextFingerprinter()

    assert fp.fingerprint("hi") == _zeros()
    assert fp.fingerprint("hi there") == _zeros()


def test_fingerprint_performance() -> None:
    """Average must be < 5ms per call."""
    fp = TextFingerprinter()
    sample = (
        "the charger stopped working after one week of use "
        "i need a replacement or refund for order number 12345"
    )
    iterations = 200
    start = time.perf_counter()
    for _ in range(iterations):
        fp.fingerprint(sample)
    elapsed_ms = (time.perf_counter() - start) * 1000
    avg_ms = elapsed_ms / iterations
    print(f"fingerprint avg {avg_ms:.4f}ms")
    assert avg_ms < 5.0, f"fingerprint avg {avg_ms:.2f}ms >= 5ms"


@pytest.mark.asyncio
async def test_ingress_fingerprint_stored_in_metadata() -> None:
    persistence = InMemoryBoundaryPersistence()
    service = TicketIngressService(
        persistence=persistence,
        session=cast(Any, _FakeSession()),
    )

    result = await service.process(
        external_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "scb1-fingerprint")),
        channel="whatsapp",
        raw_content=(
            "the charger stopped working after one week of use "
            "i need a replacement or refund"
        ),
        language_code="en",
        expected_tenant_id="tenant-scb1",
    )
    record = await persistence.get_ingress(
        as_ingress_id(result.ingress_id),
        expected_tenant_id="tenant-scb1",
    )

    assert record is not None
    fingerprint = record.metadata["text_fingerprint"]
    assert isinstance(fingerprint, list)
    assert len(fingerprint) == NUM_HASH_FUNCTIONS
    assert all(isinstance(value, int) for value in fingerprint)
    assert record.metadata["fingerprint_version"] == FINGERPRINT_VERSION


@pytest.mark.asyncio
async def test_fingerprint_exception_does_not_block_ingress() -> None:
    persistence = InMemoryBoundaryPersistence()
    service = TicketIngressService(
        persistence=persistence,
        session=cast(Any, _FakeSession()),
        fingerprinter=_ExplodingFingerprinter(),
    )

    result = await service.process(
        external_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "scb1-fingerprint-fail-open")),
        channel="whatsapp",
        raw_content="the charger stopped working after one week of use",
        language_code="en",
        expected_tenant_id="tenant-scb1",
    )
    record = await persistence.get_ingress(
        as_ingress_id(result.ingress_id),
        expected_tenant_id="tenant-scb1",
    )

    assert result.ingress_id
    assert record is not None
    assert "text_fingerprint" not in record.metadata
