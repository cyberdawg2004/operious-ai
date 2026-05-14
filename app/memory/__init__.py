"""Operational memory subsystem.

The memory subsystem is split into three sub-packages, each with a
single, narrow responsibility:

* `chunking/`  — pure-function transformation of document text into a
                deterministic sequence of `Chunk` DTOs.
* `indexing/`  — `DocumentIngestionService`: the explicit pipeline
                that runs document → chunk → embed → vector-index →
                persist → trace.
* `retrieval/` — `RetrievalService`: query embedding + vector query +
                hit normalisation + envelope construction.

What MUST NOT live under `app/memory/`:

* vendor SDK imports — those live in `app.providers.*`,
* the embedding execution gateway — that's `app/embeddings/`,
* persistence access — those live in `app.repositories`.

Memory services consume the embedding gateway and the vector provider;
they do not reach into vendor SDKs or own retry semantics.
"""
