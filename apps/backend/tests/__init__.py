"""Deterministic infrastructure test suite.

Tests in this package validate runtime stability, replayability,
ordering guarantees, and envelope semantics. They are NOT happy-path
smoke tests — each test exists because if it ever fails, a deeply
relied-upon platform invariant has drifted and downstream behaviour
cannot be trusted.

Constitutional substrate coverage (Phase 2.1+):

* `test_session_*`                 — session substrate (lifecycle, persistence, replay).
* `test_supervisor_*`              — supervisor substrate (decisions, evaluators, replay).
* `test_governance_*`              — governance substrate (decisions, subjects, replay).
* `test_arbitration_*`             — arbitration substrate.
* `test_boundary_*`                — boundary substrate (idempotency, envelopes).
* `test_coordination_*`            — coordination topology / federation.
* `test_hardening_*`               — hardening / containment substrate.
* `test_intelligence_*`            — organizational intelligence substrate.
* `test_voice_*` / `test_translation_*` — multilingual / voice substrates.
* `test_agents_*`                  — agent execution substrate.

Phase 2 invariants:

* `test_legacy_module_quarantine.py`       — Phase 2.1 quarantine boundaries.
* `test_forbidden_dependencies.py`         — Phase 2.2 manifest contract.
* `test_transitional_vendor_isolation.py`  — Phase 2.2 import-graph contract.

Pre-constitution legacy tests (chunk determinism, retrieval ordering,
envelope consistency, replay behavior, dependency audit) live under
`tests/_deprecated/` and are excluded from collection by
`pytest.ini::norecursedirs`.

Run with:

    pytest tests/

Every test in this suite is deterministic. Flakes are bugs.
"""
