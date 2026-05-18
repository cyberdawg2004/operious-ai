# pyright: reportArgumentType=false
"""P2-E regression tests — production survivability primitives.

Pins the leaf operational shell. No primitive in
``app/survivability/`` may mutate ontology established in
P2-A...P2-D, and the sub-package must remain leaf-positioned.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.survivability import (
    PROBLEM_DETAILS_MEDIA_TYPE,
    IdempotencyKey,
    IdempotencyPolicy,
    IdempotencyRecord,
    InMemoryIdempotencyStore,
    ProblemDetails,
    ReadinessGate,
    ReadinessRegistry,
    SurvivabilityHook,
    coerce_idempotency_key,
    problem_details_response,
)
from app.survivability.idempotency import IdempotencyKeyError
from app.survivability.readiness import (
    ReadinessGateRegistrationError,
)


_NOW = datetime(2025, 1, 1, tzinfo=timezone.utc)


# ─── idempotency key coercion ───────────────────────────────────────


def test_coerce_idempotency_key_accepts_valid_formats() -> None:
    coerce_idempotency_key("abc123")
    coerce_idempotency_key("550e8400-e29b-41d4-a716-446655440000")
    coerce_idempotency_key("client.event:7")
    coerce_idempotency_key("a" * 255)


def test_coerce_idempotency_key_rejects_empty_string() -> None:
    with pytest.raises(IdempotencyKeyError):
        coerce_idempotency_key("")


def test_coerce_idempotency_key_rejects_oversize() -> None:
    with pytest.raises(IdempotencyKeyError):
        coerce_idempotency_key("a" * 256)


def test_coerce_idempotency_key_rejects_special_chars() -> None:
    with pytest.raises(IdempotencyKeyError):
        coerce_idempotency_key("with space")
    with pytest.raises(IdempotencyKeyError):
        coerce_idempotency_key("with/slash")


def test_coerce_idempotency_key_rejects_non_str() -> None:
    with pytest.raises(IdempotencyKeyError):
        coerce_idempotency_key(123)  # type: ignore[arg-type]


# ─── IdempotencyPolicy invariants ──────────────────────────────────


def test_idempotency_policy_rejects_non_positive_ttl() -> None:
    with pytest.raises(ValueError):
        IdempotencyPolicy(ttl=timedelta(seconds=0))
    with pytest.raises(ValueError):
        IdempotencyPolicy(ttl=timedelta(seconds=-1))


def test_idempotency_policy_rejects_zero_max_records() -> None:
    with pytest.raises(ValueError):
        IdempotencyPolicy(max_records=0)


def test_idempotency_policy_defaults() -> None:
    policy = IdempotencyPolicy()
    assert policy.ttl == timedelta(hours=24)
    assert policy.max_records is None


# ─── InMemoryIdempotencyStore ──────────────────────────────────────


def test_store_returns_none_for_unseen_key() -> None:
    store = InMemoryIdempotencyStore()
    record = asyncio.run(
        store.get(
            idempotency_key=coerce_idempotency_key("k1"),
            tenant_id="acme",
        )
    )
    assert record is None


def test_store_records_first_observation() -> None:
    store = InMemoryIdempotencyStore()
    key = coerce_idempotency_key("k1")
    record = asyncio.run(
        store.record_first(
            idempotency_key=key,
            tenant_id="acme",
            request_fingerprint="abc",
            response_status=201,
            response_body={"id": "session-1"},
            now=_NOW,
        )
    )
    assert record.idempotency_key == "k1"
    assert record.tenant_id == "acme"
    assert record.response_status == 201
    assert dict(record.response_body) == {"id": "session-1"}
    assert record.observation_count == 1


def test_store_rejects_duplicate_first_within_ttl() -> None:
    store = InMemoryIdempotencyStore()
    key = coerce_idempotency_key("k1")
    asyncio.run(
        store.record_first(
            idempotency_key=key,
            tenant_id="acme",
            request_fingerprint="abc",
            response_status=201,
            response_body={},
            now=_NOW,
        )
    )
    with pytest.raises(KeyError):
        asyncio.run(
            store.record_first(
                idempotency_key=key,
                tenant_id="acme",
                request_fingerprint="abc",
                response_status=201,
                response_body={},
                now=_NOW,
            )
        )


def test_store_partitions_by_tenant() -> None:
    store = InMemoryIdempotencyStore()
    key = coerce_idempotency_key("k1")
    asyncio.run(
        store.record_first(
            idempotency_key=key,
            tenant_id="acme",
            request_fingerprint="abc",
            response_status=201,
            response_body={},
            now=_NOW,
        )
    )
    # Same key under a different tenant must NOT collide.
    other = asyncio.run(
        store.record_first(
            idempotency_key=key,
            tenant_id="globex",
            request_fingerprint="def",
            response_status=200,
            response_body={},
            now=_NOW,
        )
    )
    assert other.tenant_id == "globex"


def test_store_evicts_expired_records_on_get() -> None:
    policy = IdempotencyPolicy(ttl=timedelta(seconds=10))
    store = InMemoryIdempotencyStore(policy=policy)
    key = coerce_idempotency_key("k1")
    asyncio.run(
        store.record_first(
            idempotency_key=key,
            tenant_id="acme",
            request_fingerprint="abc",
            response_status=201,
            response_body={},
            now=_NOW,
        )
    )
    later = _NOW + timedelta(seconds=11)
    result = asyncio.run(
        store.get(
            idempotency_key=key, tenant_id="acme", now=later
        )
    )
    assert result is None


def test_store_record_observation_bumps_count() -> None:
    store = InMemoryIdempotencyStore()
    key = coerce_idempotency_key("k1")
    asyncio.run(
        store.record_first(
            idempotency_key=key,
            tenant_id="acme",
            request_fingerprint="abc",
            response_status=201,
            response_body={"id": "x"},
            now=_NOW,
        )
    )
    later = _NOW + timedelta(seconds=5)
    updated = asyncio.run(
        store.record_observation(
            idempotency_key=key, tenant_id="acme", now=later
        )
    )
    assert updated.observation_count == 2
    assert updated.first_seen_at == _NOW
    assert updated.last_seen_at == later
    # Original response data must NOT change on observation.
    assert updated.response_status == 201


def test_store_record_observation_missing_raises() -> None:
    store = InMemoryIdempotencyStore()
    with pytest.raises(KeyError):
        asyncio.run(
            store.record_observation(
                idempotency_key=coerce_idempotency_key("absent"),
                tenant_id="acme",
            )
        )


def test_store_respects_max_records_cap() -> None:
    policy = IdempotencyPolicy(max_records=2)
    store = InMemoryIdempotencyStore(policy=policy)
    for i in range(3):
        asyncio.run(
            store.record_first(
                idempotency_key=coerce_idempotency_key(f"k{i}"),
                tenant_id="acme",
                request_fingerprint="abc",
                response_status=201,
                response_body={},
                now=_NOW,
            )
        )
    # First record (k0) should have been evicted.
    assert (
        asyncio.run(
            store.get(
                idempotency_key=coerce_idempotency_key("k0"),
                tenant_id="acme",
                now=_NOW,
            )
        )
        is None
    )
    assert (
        asyncio.run(
            store.get(
                idempotency_key=coerce_idempotency_key("k2"),
                tenant_id="acme",
                now=_NOW,
            )
        )
        is not None
    )


def test_idempotency_record_is_frozen() -> None:
    import dataclasses

    record = IdempotencyRecord(
        idempotency_key=IdempotencyKey("k1"),
        tenant_id="acme",
        request_fingerprint="abc",
        response_status=200,
        response_body={"k": "v"},
        first_seen_at=_NOW,
        last_seen_at=_NOW,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.observation_count = 99  # type: ignore[misc]


# ─── ProblemDetails (RFC 9457) ─────────────────────────────────────


def test_problem_details_minimum_shape() -> None:
    p = ProblemDetails(title="Conflict", status=409)
    assert p.type == "about:blank"
    assert p.status == 409
    assert p.title == "Conflict"


def test_problem_details_supports_extension_members() -> None:
    p = ProblemDetails(
        title="Conflict",
        status=409,
        detail="duplicate idempotency key",
        # Extension members allowed (RFC 9457 §3.2)
        idempotency_key="abc",  # type: ignore[call-arg]
    )
    dumped = p.model_dump(exclude_none=True)
    assert dumped["idempotency_key"] == "abc"


def test_problem_details_status_bounded() -> None:
    with pytest.raises(Exception):
        ProblemDetails(title="bad", status=99)
    with pytest.raises(Exception):
        ProblemDetails(title="bad", status=600)


def test_problem_details_response_uses_canonical_media_type() -> None:
    p = ProblemDetails(title="Bad", status=400, detail="oops")
    response = problem_details_response(p)
    assert response.status_code == 400
    assert response.media_type == PROBLEM_DETAILS_MEDIA_TYPE


def test_problem_details_response_respects_headers() -> None:
    p = ProblemDetails(title="Bad", status=400)
    response = problem_details_response(
        p, headers={"X-Trace-Id": "tr-1"}
    )
    assert response.headers["X-Trace-Id"] == "tr-1"


def test_problem_details_is_frozen() -> None:
    p = ProblemDetails(title="x", status=400)
    with pytest.raises(Exception):
        p.title = "y"  # type: ignore[misc]


# ─── ReadinessRegistry ─────────────────────────────────────────────


class _StubGate:
    def __init__(self, name: str, healthy: bool = True) -> None:
        self.name = name
        self._healthy = healthy

    async def check(self) -> bool:
        return self._healthy


def test_readiness_registry_runtime_checkable_protocol() -> None:
    gate = _StubGate("postgres")
    assert isinstance(gate, ReadinessGate)


def test_readiness_registry_register_and_iterate() -> None:
    registry = ReadinessRegistry()
    g1 = _StubGate("postgres")
    g2 = _StubGate("redis")
    registry.register(g1)
    registry.register(g2)
    assert len(registry) == 2
    assert registry.gates() == (g1, g2)


def test_readiness_registry_rejects_empty_name() -> None:
    registry = ReadinessRegistry()
    with pytest.raises(ReadinessGateRegistrationError):
        registry.register(_StubGate(""))


def test_readiness_registry_rejects_duplicate_name() -> None:
    registry = ReadinessRegistry()
    registry.register(_StubGate("postgres"))
    with pytest.raises(ReadinessGateRegistrationError):
        registry.register(_StubGate("postgres"))


# ─── SurvivabilityHook vocabulary ──────────────────────────────────


_HOOK_VALUE_RE = re.compile(r"^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$")


def test_every_hook_value_is_namespaced() -> None:
    for hook in SurvivabilityHook:
        assert _HOOK_VALUE_RE.match(hook.value), (
            f"{hook.name} = {hook.value!r} not in <phase>:<event> form"
        )


def test_hook_values_unique() -> None:
    values = [h.value for h in SurvivabilityHook]
    assert len(values) == len(set(values))


# ─── leaf substrate invariants ─────────────────────────────────────


def _repo_app_root() -> Path:
    return Path(__file__).resolve().parents[1] / "app"


def _imports_from_module(source: str, prefix: str) -> bool:
    pat = re.compile(
        rf"^\s*from\s+{re.escape(prefix)}(\.[\w]+)*\s+import\b",
        re.M,
    )
    return bool(pat.search(source))


def test_survivability_substrate_is_a_leaf() -> None:
    """``app/survivability/`` MUST NOT import from any sibling
    orchestration / event substrate. P2-E is leaf operational
    hardening; pulling in business substrates is ontology mutation."""
    forbidden_prefixes = (
        "app.agents",
        "app.arbitration",
        "app.boundary",
        "app.coordination",
        "app.events",
        "app.hardening",
        "app.organizational_intelligence",
        "app.session",
        "app.supervisor",
        "app.middleware",
        "app.auth",
        "app.observability",
        "app.identity",
        "app.governance",
    )
    surv_root = _repo_app_root() / "survivability"
    offenders: list[tuple[str, str]] = []
    for py in surv_root.rglob("*.py"):
        src = py.read_text(encoding="utf-8")
        for prefix in forbidden_prefixes:
            if _imports_from_module(src, prefix):
                offenders.append(
                    (str(py.relative_to(_repo_app_root())), prefix)
                )
    assert not offenders, (
        f"app/survivability/ leaked non-leaf imports: {offenders}"
    )


def test_survivability_module_public_surface() -> None:
    import app.survivability as surv

    assert set(surv.__all__) == {
        "IdempotencyKey",
        "IdempotencyPolicy",
        "IdempotencyRecord",
        "InMemoryIdempotencyStore",
        "PROBLEM_DETAILS_MEDIA_TYPE",
        "ProblemDetails",
        "ReadinessGate",
        "ReadinessRegistry",
        "SurvivabilityHook",
        "coerce_idempotency_key",
        "problem_details_response",
    }


def test_no_ontology_mutation() -> None:
    """P2-E MUST NOT redefine any ontology established in
    P2-A...P2-D. Source-scan for type / enum names that already
    exist elsewhere."""
    forbidden_symbols = (
        "OperationalAct",
        "OperationalEvent",
        "OperationalSubstrate",
        "AuthorityContext",
        "AuthorityResolution",
        "EventCausality",
        "EventChronology",
        "EventId",
        "CapabilityGovernanceSubject",
        "RBACPolicy",
        "Decision",
        "SubjectKind",
    )
    surv_root = _repo_app_root() / "survivability"
    offenders: list[tuple[str, str]] = []
    for py in surv_root.rglob("*.py"):
        src = py.read_text(encoding="utf-8")
        # Skip docstring-only mentions: look for `class <Symbol>` or
        # bare assignment forms ``<Symbol> =``.
        for sym in forbidden_symbols:
            class_def = re.compile(
                rf"^\s*class\s+{re.escape(sym)}\b", re.M
            )
            assignment = re.compile(
                rf"^\s*{re.escape(sym)}\s*=", re.M
            )
            if class_def.search(src) or assignment.search(src):
                offenders.append(
                    (str(py.relative_to(_repo_app_root())), sym)
                )
    assert not offenders, (
        f"app/survivability/ redefined kernel ontology: {offenders}"
    )


def test_settings_carry_survivability_section() -> None:
    """The configuration substrate exposes the survivability knobs."""
    from app.core.config import Settings

    s = Settings()
    assert s.SURVIVABILITY_IDEMPOTENCY_TTL_SECONDS == 86_400
    assert s.SURVIVABILITY_IDEMPOTENCY_MAX_RECORDS is None
    assert s.SURVIVABILITY_REQUEST_BODY_MAX_BYTES == 1_000_000
    assert s.SURVIVABILITY_READINESS_PROBE_TIMEOUT_SECONDS == 2.0
