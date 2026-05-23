"""Retrieval subsystem.

`RetrievalService` runs:

    query → embed → vector-query → load-chunks → normalise → envelope

Always returns a `RetrievalEnvelope` (never raises). The envelope
exposes the embedding sub-trace + the retrieval timing + the
normalised hits.
"""
