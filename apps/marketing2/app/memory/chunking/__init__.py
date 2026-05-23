"""Chunking subsystem.

A chunker is a deterministic pure function: same input text + same
configuration → same chunk sequence, byte-for-byte. That property is
what makes ingestion replayable, idempotent, and cacheable.

What lives here:

* `models`           — `Chunk` DTO + `ChunkerConfig`.
* `base`             — `BaseChunker` abstract contract.
* `recursive`        — `RecursiveCharacterChunker` (the Sprint G default).
"""
