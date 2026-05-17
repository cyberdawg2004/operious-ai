"""Group B — chunk determinism.

Verifies the foundational contract of the chunking subsystem:

    same `(text, config)` → byte-identical `Sequence[Chunk]`.

If this contract breaks, the entire memory pipeline becomes
non-replayable: re-ingesting the same document would produce different
chunks, different content hashes, different chunk rows, and different
vector records.

Failure condition: chunk drift between executions.
"""

from __future__ import annotations

import pytest

from app.memory.chunking.models import ChunkerConfig
from app.memory.chunking.recursive import RecursiveCharacterChunker


_SAMPLE = (
    "Operious AI provides enterprise operational intelligence systems.\n\n"
    "Refund requests must be processed within 5 business days. "
    "Customer escalations require supervisor review. "
    "Escalations of escalations require executive approval.\n\n"
    "SOP-A: when a customer reports a payment failure, the agent must "
    "verify the transaction reference, check the gateway logs, and either "
    "issue a credit or escalate to the payments team within one business "
    "day.\n\n"
    "SOP-B: when a customer requests data deletion, the agent must "
    "confirm identity, file a deletion ticket, and acknowledge the request "
    "within 24 hours.\n"
)


@pytest.mark.asyncio
async def test_chunk_output_is_byte_identical_across_runs(chunker) -> None:
    """Same input + same config → same chunks, ten times in a row."""

    first = await chunker.chunk(_SAMPLE)
    for _ in range(9):
        again = await chunker.chunk(_SAMPLE)
        assert len(again) == len(first), "chunk count drifted"
        for a, b in zip(first, again):
            assert a.ordinal == b.ordinal
            assert a.content == b.content
            assert a.byte_start == b.byte_start
            assert a.byte_end == b.byte_end


@pytest.mark.asyncio
async def test_chunk_ordinals_are_strictly_increasing(chunker) -> None:
    """`ordinal` is contiguous from 0 and never repeats."""

    chunks = await chunker.chunk(_SAMPLE)
    assert chunks  # not empty
    expected = list(range(len(chunks)))
    actual = [c.ordinal for c in chunks]
    assert actual == expected


@pytest.mark.asyncio
async def test_chunk_byte_offsets_advance_monotonically(chunker) -> None:
    """`byte_start` of chunk N+1 is >= `byte_start` of chunk N."""

    chunks = await chunker.chunk(_SAMPLE)
    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt.byte_start >= prev.byte_start


@pytest.mark.asyncio
async def test_overlap_is_stable(chunker) -> None:
    """When overlap is non-zero, chunk N+1 starts with the tail of chunk N.

    This is the determinism guarantee of the overlap mechanism: even
    though the byte offsets reflect the original span, the rendered
    content has a stable prefix relationship.
    """

    chunks = await chunker.chunk(_SAMPLE)
    if len(chunks) < 2:
        pytest.skip("sample text not large enough to produce overlap")
    overlap = chunker.config.overlap
    for prev, nxt in zip(chunks, chunks[1:]):
        tail = prev.content[-overlap:]
        # The next chunk's content is `overlap + raw_piece`. The tail of
        # the previous chunk must equal the head of the next chunk.
        assert nxt.content.startswith(tail), (
            f"overlap broken: prev tail '{tail!r}' not at head of next "
            f"'{nxt.content[:overlap]!r}'"
        )


@pytest.mark.asyncio
async def test_chunker_is_pure_under_metadata_change() -> None:
    """Metadata flows through but does NOT change chunk boundaries.

    The metadata mapping is part of the `Chunk` shape but it must not
    perturb where the chunker cuts the text.
    """

    cfg = ChunkerConfig(target_size=120, overlap=20, min_size=10)
    chunker = RecursiveCharacterChunker(cfg)

    a = await chunker.chunk(_SAMPLE, metadata={"tenant_id": "t1"})
    b = await chunker.chunk(_SAMPLE, metadata={"tenant_id": "t2"})

    assert len(a) == len(b)
    for x, y in zip(a, b):
        assert x.content == y.content
        assert x.byte_start == y.byte_start
        assert x.byte_end == y.byte_end
        assert x.ordinal == y.ordinal
        # And the metadata is propagated faithfully:
        assert x.metadata == {"tenant_id": "t1"}
        assert y.metadata == {"tenant_id": "t2"}


@pytest.mark.asyncio
async def test_chunker_returns_tuple_immutable() -> None:
    """Returned sequence is an immutable tuple — callers cannot mutate."""

    chunker = RecursiveCharacterChunker(
        ChunkerConfig(target_size=120, overlap=20, min_size=10)
    )
    chunks = await chunker.chunk(_SAMPLE)
    assert isinstance(chunks, tuple)


@pytest.mark.asyncio
async def test_chunker_handles_empty_input() -> None:
    """Empty input is a deterministic no-op, not an exception."""

    chunker = RecursiveCharacterChunker(
        ChunkerConfig(target_size=120, overlap=20, min_size=10)
    )
    result = await chunker.chunk("")
    assert result == ()


def test_chunker_config_validates_invariants() -> None:
    """`ChunkerConfig.validate()` enforces structural invariants."""

    with pytest.raises(ValueError):
        ChunkerConfig(target_size=0, overlap=10, min_size=5).validate()
    with pytest.raises(ValueError):
        ChunkerConfig(target_size=100, overlap=-1, min_size=5).validate()
    with pytest.raises(ValueError):
        ChunkerConfig(target_size=100, overlap=100, min_size=5).validate()
    with pytest.raises(ValueError):
        ChunkerConfig(target_size=100, overlap=20, min_size=-1).validate()
