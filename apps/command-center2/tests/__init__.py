"""Deterministic infrastructure test suite.

Tests in this package validate runtime stability, replayability, ordering
guarantees, and envelope semantics. They are NOT happy-path smoke tests —
each test exists because if it ever fails, a deeply-relied-upon platform
invariant has drifted and downstream behaviour cannot be trusted.

Layout:

* `test_chunk_determinism.py`     — Group B: chunker is a pure function.
* `test_retrieval_ordering.py`    — Group A: vector ordering is stable.
* `test_envelope_consistency.py`  — Group C: gateway envelopes are uniform.
* `test_replay_behavior.py`       — Group D: ingestion is idempotent.
* `test_dependency_audit.py`      — Phase 5: import discipline is enforced.

Run with:

    pytest tests/

Every test in this suite is deterministic. Flakes are bugs.
"""
