"""`CoordinationRuntime` — apex dispatch orchestrator.

One public method (`dispatch`) drives one coordination operation
end-to-end:

    CoordinationRuntime.dispatch(request)
        → validate request (sender + recipient against registry)
        → (Sprint L3) when composed, invoke
          `CoordinationTopologyRuntime.evaluate(...)` to obtain a
          structural-authority verdict. Any blocking verdict
          (DENIED / ESCALATED / DEPTH_EXCEEDED / BOUNDARY_VIOLATION)
          short-circuits dispatch with the matching
          `TOPOLOGY_*` outcome and status `TOPOLOGY_DENIED`.
          ALLOWED continues.
        → (Sprint L2) when composed, invoke
          `CoordinationPolicyRuntime.evaluate(...)` to obtain a
          topology-authorisation-rule verdict. DENY / ESCALATE
          short-circuit dispatch with `POLICY_DENIED` /
          `POLICY_ESCALATED` outcomes; ALLOW / ANNOTATE / RESTRICT
          continue.
        → build governance context (deterministic from message)
        → invoke `GovernanceRuntime.evaluate(context)`
        → build `CoordinationEnvelope` (assign deterministic sequence)
        → persist via `CoordinationPersistenceProtocol`
        → return `CoordinationDispatchResult`

Sprint L3 added a coordination-topology phase BEFORE policy
(topology constrains structure; policy then applies rule-level
authorisation; governance then applies operational restrictions).
**Topology denial, policy denial, and governance denial remain
DISTINCT semantics** across the dispatch outcome enum and the
envelope status enum.

The runtime is the **single** producer of `CoordinationEnvelope`. It
NEVER raises — every failure mode lands on the returned
`CoordinationDispatchResult`.

Architectural disciplines preserved (sprint L1 rules):

* Rule 1 — agents MUST NOT communicate directly. The runtime is the
  only mediator; it validates both endpoints against the registry.
* Rule 2 — envelopes are immutable runtime artifacts.
* Rule 3 — coordination is replay-safe. Identical inputs (with a
  pinned `coordination_id_override` + pinned `created_at` on the
  message) produce byte-identical envelopes modulo the substrate's
  wall-clock `dispatched_at` field, which callers may override via
  test fixtures.
* Rule 4 — no asynchronous orchestration explosions. The dispatch
  loop is sequential. Sequence numbers are assigned under a lock so
  concurrent dispatchers still receive a deterministic total order.
* Rule 5 — `dispatch()` ONLY validates, invokes governance, builds
  the envelope, persists the artifact, and returns the result. It
  does NOT execute the recipient, invoke tools, mutate runtime state
  elsewhere, retry, or schedule.
* Rule 6 — governance composition is explicit; `GovernanceRuntime`
  is injected and called once per dispatch. The runtime does NOT
  absorb governance semantics — the apex verdict is preserved
  verbatim on the envelope (`governance_decision_id`).
* Rule 7 — supervisors are unaffected; this runtime emits no
  supervisor mutations.

What the runtime DOES NOT do (also pinned by the architectural
contract):

* execute recipient agents,
* invoke tools,
* mutate registries / governance / agent runtimes,
* retry,
* spawn background tasks,
* schedule asynchronous fanout,
* perform autonomous routing.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from app.coordination.contracts.requests import CoordinationDispatchRequest
from app.coordination.contracts.results import (
    CoordinationDispatchOutcome,
    CoordinationDispatchResult,
)
from app.coordination.envelopes import CoordinationEnvelope
from app.coordination.enums import (
    CoordinationDirection,
    CoordinationMessageType,
    CoordinationPriority,
    CoordinationStatus,
)
from app.coordination.exceptions import (
    CoordinationGovernanceDeniedError,
    CoordinationPersistenceError,
    CoordinationValidationError,
)
from app.coordination.identity import (
    CoordinationCorrelationId,
    CoordinationId,
    CoordinationMessageId,
    generate_coordination_id,
)
from app.coordination.models.payload import CoordinationPayload
from app.coordination.persistence.models import (
    CoordinationQuery,
    RecordPage,
)
from app.coordination.persistence.records import CoordinationRecord
from app.coordination.persistence.repository import (
    CoordinationPersistenceProtocol,
)
from app.coordination.persistence.serializers import (
    envelope_to_record,
    record_to_envelope,
)
from app.coordination.policy.contracts.requests import (
    CoordinationPolicyEvaluationRequest,
)
from app.coordination.policy.enums import CoordinationPolicyDecision
from app.coordination.policy.envelopes import (
    CoordinationPolicyEnvelope,
)
from app.coordination.policy.runtime.runtime import (
    CoordinationPolicyRuntime,
)
from app.coordination.policy.taxonomy import (
    CoordinationPolicyMetadataKey,
    is_blocking_policy_decision,
)
from app.coordination.registry.registry import CoordinationRegistry
from app.coordination.taxonomy import (
    CoordinationGovernanceAction,
    CoordinationMetadataKey,
)
from app.coordination.topology.contracts.requests import (
    CoordinationTopologyEvaluationRequest,
)
from app.coordination.topology.enums import (
    CoordinationTopologyDecision,
)
from app.coordination.topology.envelopes import (
    CoordinationTopologyEnvelope,
)
from app.coordination.topology.runtime.runtime import (
    CoordinationTopologyRuntime,
)
from app.coordination.topology.taxonomy import (
    CoordinationTopologyMetadataKey,
    is_blocking_topology_decision,
)
from app.coordination.tracing import CoordinationTrace
from app.governance.capability import (
    OperationalAct,
    gate_or_deny,
)
from app.governance.context import GovernanceContext
from app.governance.decisions import is_blocking_decision
from app.governance.enforcement.runtime import GovernanceRuntime
from app.governance.enums import Decision
from app.governance.subjects.communication import (
    CommunicationGovernanceSubject,
)
from app.identity import AuthorityResolution, TenantId, resolve_authority
from app.observability.context import get_request_id


class CoordinationRuntime:
    """Apex coordination dispatcher. Produces one result per call."""

    def __init__(
        self,
        *,
        governance_runtime: GovernanceRuntime,
        persistence: CoordinationPersistenceProtocol,
        registry: CoordinationRegistry,
        policy_runtime: CoordinationPolicyRuntime | None = None,
        topology_runtime: CoordinationTopologyRuntime | None = None,
        capability_governance: GovernanceRuntime | None = None,
    ) -> None:
        self._governance = governance_runtime
        self._persistence = persistence
        self._registry = registry
        # Sprint L3 — coordination-topology substrate. SEPARATE
        # substrate composed by injection. Evaluated BEFORE policy.
        # Optional for backward-compat; when None, dispatch skips the
        # topology phase entirely (no implicit-allow assumption — the
        # absence of topology means no structural constraints are
        # evaluated). Topology denial, policy denial, and governance
        # denial are distinct semantic authorities.
        self._topology_runtime = topology_runtime
        # Sprint L2 — coordination-policy substrate. SEPARATE substrate
        # composed by injection. Evaluated AFTER topology and BEFORE
        # governance. Optional for backward-compat.
        self._policy_runtime = policy_runtime
        # 2.75-\u03b1: capability legality gate. Separate from
        # ``governance_runtime`` so the policy chain that handles
        # ``CommunicationGovernanceSubject`` and the one that handles
        # ``CapabilityGovernanceSubject`` can be composed
        # independently. ``None`` keeps the gate inert; production
        # composition root wires a configured runtime so every
        # dispatch is evaluated against
        # ``OperationalAct.COORDINATION_DISPATCH``.
        self._capability_governance = capability_governance
        self._instance_id: uuid.UUID = uuid.uuid4()
        self._sequence: int = 0
        # The sequence assignment + envelope construction happen under
        # a single lock so that concurrent dispatch() callers still
        # observe a deterministic total order on (instance_id, sequence).
        self._lock = asyncio.Lock()

    # ─── Inspection helpers ──────────────────────────────────────────

    @property
    def runtime_instance_id(self) -> uuid.UUID:
        return self._instance_id

    @property
    def policy_runtime(self) -> CoordinationPolicyRuntime | None:
        """Injected coordination-policy substrate, or ``None``.

        Exposed for audit / supervisor introspection. The
        coordination runtime does NOT delegate dispatch decisions
        through this accessor — it invokes the policy runtime
        directly inside `dispatch()`.
        """
        return self._policy_runtime

    @property
    def topology_runtime(self) -> CoordinationTopologyRuntime | None:
        """Injected coordination-topology substrate, or ``None``.

        Exposed for audit / supervisor introspection. The
        coordination runtime does NOT delegate dispatch decisions
        through this accessor — it invokes the topology runtime
        directly inside `dispatch()`.
        """
        return self._topology_runtime

    def known_participants(self) -> tuple[str, ...]:
        return self._registry.names()

    # ─── Public API ───────────────────────────────────────────────────

    async def dispatch(
        self, request: CoordinationDispatchRequest
    ) -> CoordinationDispatchResult:
        """Run one coordination dispatch end-to-end. Never raises."""
        loop = asyncio.get_event_loop()
        started_at = datetime.now(timezone.utc)
        loop_start = loop.time()
        coordination_id = (
            request.coordination_id_override or generate_coordination_id()
        )
        request_id = request.request_id or get_request_id()

        # Wedge B7: SINGULAR authority resolution.
        # Audit defect DR-4 was that six internal sites coalesced
        # ``request.tenant_id or msg.recipient.tenant_id`` independently
        # (topology subrequest, policy subrequest, governance subject,
        # governance context, envelope, fail-fast trace) — with the
        # falsy-string bug from B4 (``""`` silently falling back to
        # recipient) and zero attribution. We resolve authority ONCE
        # here and thread the resolution through every downstream
        # site. Every envelope, every trace, every persisted record
        # records WHICH source produced the effective ``tenant_id``.
        resolution = resolve_authority(
            typed=request.authority,
            legacy_tenant_id=request.tenant_id,
            observed_tenant_id=request.message.recipient.tenant_id,
        )

        # 2.75-\u03b1: capability legality gate. Independent of the
        # required ``governance_runtime`` so tests can pin only the
        # communication policy chain; production wires both.
        denial = await gate_or_deny(
            self._capability_governance,
            act=OperationalAct.COORDINATION_DISPATCH,
            authority=request.authority,
            resolution=resolution,
            actor="coordination_runtime",
        )
        if denial is not None:
            return self._fail_fast_result(
                coordination_id=coordination_id,
                request=request,
                request_id=request_id,
                started_at=started_at,
                loop_start=loop_start,
                outcome=CoordinationDispatchOutcome.GOVERNANCE_DENIED,
                error=denial,
                status=CoordinationStatus.FAILED,
                envelope=None,
                resolution=resolution,
            )

        # 1. Validate.
        try:
            self._validate(request)
        except CoordinationValidationError as exc:
            return self._fail_fast_result(
                coordination_id=coordination_id,
                request=request,
                request_id=request_id,
                started_at=started_at,
                loop_start=loop_start,
                outcome=CoordinationDispatchOutcome.VALIDATION_ERROR,
                error=exc,
                status=CoordinationStatus.FAILED,
                envelope=None,
                resolution=resolution,
            )

        # 2. Invoke coordination-topology (structural authority) when
        # a topology runtime is composed. Sprint L3 — topology denial,
        # policy denial, and governance denial are DISTINCT semantics.
        topology_metadata: dict[str, object] = {}
        if self._topology_runtime is not None:
            topology_envelope = await self._topology_runtime.evaluate(
                self._build_topology_request(
                    request=request,
                    request_id=request_id,
                    coordination_id=coordination_id,
                    resolution=resolution,
                )
            )
            topology_metadata = self._topology_metadata_for(
                topology_envelope
            )
            if not topology_envelope.is_ok:
                # Topology substrate itself failed — TOPOLOGY_ERROR.
                return await self._build_and_persist(
                    request=request,
                    request_id=request_id,
                    coordination_id=coordination_id,
                    status=CoordinationStatus.FAILED,
                    outcome=CoordinationDispatchOutcome.TOPOLOGY_ERROR,
                    governance_decision_id=None,
                    governance_chain_id=None,
                    error=(
                        topology_envelope.trace.error
                        or "coordination-topology substrate failed"
                    ),
                    started_at=started_at,
                    loop_start=loop_start,
                    extra_metadata=topology_metadata,
                    resolution=resolution,
                )
            topology_result = topology_envelope.unwrap()
            topology_apex = topology_result.aggregate_decision
            if is_blocking_topology_decision(topology_apex):
                # Map each distinct topology blocking verdict to its
                # own coordination dispatch outcome so the audit trail
                # records WHICH structural failure mode tripped.
                outcome = self._map_topology_blocking(topology_apex)
                return await self._build_and_persist(
                    request=request,
                    request_id=request_id,
                    coordination_id=coordination_id,
                    status=CoordinationStatus.TOPOLOGY_DENIED,
                    outcome=outcome,
                    governance_decision_id=None,
                    governance_chain_id=None,
                    error=topology_result.reason
                    or f"coordination topology {topology_apex.value}",
                    started_at=started_at,
                    loop_start=loop_start,
                    extra_metadata=topology_metadata,
                    resolution=resolution,
                )
            # ALLOWED — continue to policy.

        # 3. Invoke coordination-policy (topology authorisation rules)
        # when a policy runtime is composed. Sprint L2 Rule 2 — policy
        # denial and governance denial remain DISTINCT semantics.
        policy_envelope: CoordinationPolicyEnvelope | None = None
        substrate_metadata: dict[str, object] = dict(topology_metadata)
        if self._policy_runtime is not None:
            policy_envelope = await self._policy_runtime.evaluate(
                self._build_policy_request(
                    request=request,
                    request_id=request_id,
                    coordination_id=coordination_id,
                    resolution=resolution,
                )
            )
            policy_metadata = self._policy_metadata_for(policy_envelope)
            substrate_metadata.update(policy_metadata)
            if not policy_envelope.is_ok:
                return await self._build_and_persist(
                    request=request,
                    request_id=request_id,
                    coordination_id=coordination_id,
                    status=CoordinationStatus.FAILED,
                    outcome=CoordinationDispatchOutcome.POLICY_ERROR,
                    governance_decision_id=None,
                    governance_chain_id=None,
                    error=(
                        policy_envelope.trace.error
                        or "coordination-policy substrate failed"
                    ),
                    started_at=started_at,
                    loop_start=loop_start,
                    extra_metadata=substrate_metadata,
                    resolution=resolution,
                )
            policy_result = policy_envelope.unwrap()
            policy_apex = policy_result.aggregate_decision
            if is_blocking_policy_decision(policy_apex):
                outcome = (
                    CoordinationDispatchOutcome.POLICY_DENIED
                    if policy_apex is CoordinationPolicyDecision.DENY
                    else CoordinationDispatchOutcome.POLICY_ESCALATED
                )
                return await self._build_and_persist(
                    request=request,
                    request_id=request_id,
                    coordination_id=coordination_id,
                    status=CoordinationStatus.POLICY_DENIED,
                    outcome=outcome,
                    governance_decision_id=None,
                    governance_chain_id=None,
                    error=policy_result.reason
                    or f"coordination policy {policy_apex.value}",
                    started_at=started_at,
                    loop_start=loop_start,
                    extra_metadata=substrate_metadata,
                    resolution=resolution,
                )

        # 4. Invoke governance.
        gov_context = self._build_governance_context(
            request=request,
            request_id=request_id,
            resolution=resolution,
        )
        gov_envelope = await self._governance.evaluate(gov_context)

        if not gov_envelope.is_ok:
            return await self._build_and_persist(
                request=request,
                request_id=request_id,
                coordination_id=coordination_id,
                status=CoordinationStatus.FAILED,
                outcome=CoordinationDispatchOutcome.GOVERNANCE_ERROR,
                governance_decision_id=gov_envelope.trace.decision_id,
                governance_chain_id=gov_envelope.trace.policy_chain_id or None,
                error=gov_envelope.trace.error or "governance evaluation failed",
                started_at=started_at,
                loop_start=loop_start,
                extra_metadata=substrate_metadata,
                resolution=resolution,
            )

        decision = gov_envelope.unwrap()

        # 5. Map governance verdict → coordination status / outcome.
        try:
            status, outcome = self._map_governance(decision.decision)
        except CoordinationGovernanceDeniedError:
            return await self._build_and_persist(
                request=request,
                request_id=request_id,
                coordination_id=coordination_id,
                status=CoordinationStatus.DENIED,
                outcome=CoordinationDispatchOutcome.DENIED,
                governance_decision_id=decision.decision_id,
                governance_chain_id=decision.policy_chain_id,
                error=decision.reason or "governance denied",
                started_at=started_at,
                loop_start=loop_start,
                extra_metadata=substrate_metadata,
                resolution=resolution,
            )

        # 6. Accepted (or DEGRADED) — persist DISPATCHED / DEGRADED envelope.
        return await self._build_and_persist(
            request=request,
            request_id=request_id,
            coordination_id=coordination_id,
            status=status,
            outcome=outcome,
            governance_decision_id=decision.decision_id,
            governance_chain_id=decision.policy_chain_id,
            error=None,
            started_at=started_at,
            loop_start=loop_start,
            extra_metadata=substrate_metadata,
            resolution=resolution,
        )

    async def get_message(
        self, coordination_id: CoordinationId | str
    ) -> CoordinationEnvelope | None:
        """Return the envelope for `coordination_id`, or ``None``."""
        record = await self._persistence.get_envelope(str(coordination_id))
        if record is None:
            return None
        return record_to_envelope(record)

    async def list_messages(
        self,
        *,
        correlation_id: CoordinationCorrelationId | str | None = None,
        sender_id: str | None = None,
        recipient_id: str | None = None,
        tenant_id: str | None = None,
        runtime_instance_id: uuid.UUID | str | None = None,
        direction: CoordinationDirection | None = None,
        message_type: CoordinationMessageType | None = None,
        status: CoordinationStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[CoordinationEnvelope, ...]:
        """List envelopes matching the supplied filters.

        Order: ``(runtime_instance_id, sequence)`` ascending. This is
        the canonical replay-safe global order.
        """
        query = CoordinationQuery(
            correlation_id=str(correlation_id)
            if correlation_id is not None
            else None,
            sender_id=sender_id,
            recipient_id=recipient_id,
            tenant_id=tenant_id,
            runtime_instance_id=str(runtime_instance_id)
            if runtime_instance_id is not None
            else None,
            direction=direction.value if direction is not None else None,
            message_type=message_type.value
            if message_type is not None
            else None,
            status=status.value if status is not None else None,
            limit=limit,
            offset=offset,
        )
        page: RecordPage[CoordinationRecord] = (
            await self._persistence.query_envelopes(query)
        )
        return tuple(record_to_envelope(r) for r in page.items)

    # ─── Internals ───────────────────────────────────────────────────

    def _build_topology_request(
        self,
        *,
        request: CoordinationDispatchRequest,
        request_id: str | None,
        coordination_id: CoordinationId,
        resolution: AuthorityResolution,
    ) -> CoordinationTopologyEvaluationRequest:
        """Compose a `CoordinationTopologyEvaluationRequest` from `request`.

        Deterministic mapping — every field is pulled straight from
        the dispatch request, the message, and the substrate-pinned
        `coordination_id`. The topology substrate never sees the
        dispatch payload; only the structural axes propagate.

        Wedge B7: the ``tenant_id`` field receives the SINGULAR
        ``resolution.tenant_id`` produced once at the top of
        ``dispatch``. The earlier ``request.tenant_id or
        msg.recipient.tenant_id`` coalesce is closed (audit defect
        DR-4 — site 1 of 6). The two axis-named fields
        ``sender_tenant_id`` / ``recipient_tenant_id`` keep their
        explicit semantics — they are NOT authority resolutions but
        structural axes the topology substrate evaluates against.
        """
        msg = request.message
        return CoordinationTopologyEvaluationRequest(
            sender_id=msg.sender_id,
            recipient_id=msg.recipient.recipient_id,
            recipient_kind=msg.recipient.kind,
            direction=request.direction,
            message_type=msg.message_type,
            priority=msg.priority,
            coordination_id=coordination_id,
            coordination_message_id=msg.message_id,
            tenant_id=resolution.tenant_id,
            sender_tenant_id=request.tenant_id,
            recipient_tenant_id=msg.recipient.tenant_id,
            correlation_id=request.correlation_id,
            parent_coordination_id=request.parent_coordination_id,
            parent_message_id=request.parent_message_id,
            request_id=request_id,
            chain_depth=request.chain_depth,
            metadata=dict(request.metadata),
        )

    @staticmethod
    def _topology_metadata_for(
        envelope: CoordinationTopologyEnvelope,
    ) -> dict[str, object]:
        """Extract topology lineage keys for embedding into the coordination envelope.

        Always produces a deterministic, JSON-coercible mapping —
        even when the topology envelope failed at the framework
        layer (still carries the trace metadata).
        """
        meta: dict[str, object] = {
            CoordinationTopologyMetadataKey.TOPOLOGY_ID.value: str(
                envelope.trace.topology_id
            ),
            CoordinationTopologyMetadataKey.TOPOLOGY_NAME.value: envelope.trace.topology_name,
            CoordinationTopologyMetadataKey.TOPOLOGY_VERSION.value: envelope.trace.topology_version,
            CoordinationTopologyMetadataKey.CHAIN_ID.value: str(
                envelope.trace.chain_id
            ),
            CoordinationTopologyMetadataKey.EVALUATION_ID.value: str(
                envelope.trace.evaluation_id
            ),
            CoordinationTopologyMetadataKey.AGGREGATE_DECISION.value: envelope.trace.aggregate_decision.value,
            CoordinationTopologyMetadataKey.FINDING_COUNT.value: envelope.trace.finding_count,
            CoordinationTopologyMetadataKey.EVALUATOR_NAMES.value: list(
                envelope.trace.evaluator_names
            ),
            CoordinationTopologyMetadataKey.CHAIN_DEPTH.value: envelope.trace.chain_depth,
            CoordinationTopologyMetadataKey.MAX_CHAIN_DEPTH.value: envelope.trace.max_chain_depth,
        }
        if envelope.trace.matched_edge_id is not None:
            meta[
                CoordinationTopologyMetadataKey.MATCHED_EDGE_ID.value
            ] = str(envelope.trace.matched_edge_id)
        if envelope.trace.matched_path_id is not None:
            meta[
                CoordinationTopologyMetadataKey.MATCHED_PATH_ID.value
            ] = envelope.trace.matched_path_id
        if envelope.result is not None and envelope.result.reason:
            meta["coordination.topology.reason"] = envelope.result.reason
        return meta

    @staticmethod
    def _map_topology_blocking(
        decision: CoordinationTopologyDecision,
    ) -> CoordinationDispatchOutcome:
        """Map a blocking topology verdict → coordination dispatch outcome.

        Each blocking verdict has its OWN dispatch outcome so that
        the audit trail records the precise structural failure mode
        (not just a generic "topology denied"). Caller must ensure
        the decision is in fact blocking (use
        `is_blocking_topology_decision` first).
        """
        return {
            CoordinationTopologyDecision.DENIED: CoordinationDispatchOutcome.TOPOLOGY_DENIED,
            CoordinationTopologyDecision.ESCALATED: CoordinationDispatchOutcome.TOPOLOGY_ESCALATED,
            CoordinationTopologyDecision.DEPTH_EXCEEDED: CoordinationDispatchOutcome.TOPOLOGY_DEPTH_EXCEEDED,
            CoordinationTopologyDecision.BOUNDARY_VIOLATION: CoordinationDispatchOutcome.TOPOLOGY_BOUNDARY_VIOLATION,
        }[decision]

    def _build_policy_request(
        self,
        *,
        request: CoordinationDispatchRequest,
        request_id: str | None,
        coordination_id: CoordinationId,
        resolution: AuthorityResolution,
    ) -> CoordinationPolicyEvaluationRequest:
        """Compose a `CoordinationPolicyEvaluationRequest` from `request`.

        Deterministic mapping — every field is pulled straight from
        the dispatch request, the message, and the substrate-pinned
        `coordination_id`. The policy substrate never sees the
        dispatch payload; only the topology axes are propagated.

        Wedge B7: receives the SINGULAR ``resolution.tenant_id`` —
        audit defect DR-4 site 2 of 6 closed.
        """
        msg = request.message
        return CoordinationPolicyEvaluationRequest(
            sender_id=msg.sender_id,
            recipient_id=msg.recipient.recipient_id,
            recipient_kind=msg.recipient.kind,
            direction=request.direction,
            message_type=msg.message_type,
            priority=msg.priority,
            coordination_id=coordination_id,
            coordination_message_id=msg.message_id,
            tenant_id=resolution.tenant_id,
            sender_tenant_id=request.tenant_id,
            recipient_tenant_id=msg.recipient.tenant_id,
            correlation_id=request.correlation_id,
            parent_coordination_id=request.parent_coordination_id,
            parent_message_id=request.parent_message_id,
            request_id=request_id,
            metadata=dict(request.metadata),
        )

    @staticmethod
    def _policy_metadata_for(
        envelope: CoordinationPolicyEnvelope,
    ) -> dict[str, object]:
        """Extract policy lineage keys for embedding into the coordination envelope.

        Always produces a deterministic, JSON-coercible mapping —
        empty when the policy envelope failed at the framework layer.
        """
        result = envelope.result
        meta: dict[str, object] = {
            CoordinationPolicyMetadataKey.CHAIN_ID.value: str(
                envelope.trace.chain_id
            ),
            CoordinationPolicyMetadataKey.EVALUATION_ID.value: str(
                envelope.trace.evaluation_id
            ),
            CoordinationPolicyMetadataKey.AGGREGATE_DECISION.value: (
                envelope.trace.aggregate_decision.value
            ),
            CoordinationPolicyMetadataKey.FINDING_COUNT.value: (
                envelope.trace.finding_count
            ),
            CoordinationPolicyMetadataKey.RESTRICTION_COUNT.value: (
                envelope.trace.restriction_count
            ),
            CoordinationPolicyMetadataKey.ESCALATION_COUNT.value: (
                envelope.trace.escalation_count
            ),
            CoordinationPolicyMetadataKey.EVALUATOR_NAMES.value: list(
                envelope.trace.evaluator_names
            ),
        }
        if result is not None and result.reason:
            meta["coordination.policy.reason"] = result.reason
        return meta

    def _validate(self, request: CoordinationDispatchRequest) -> None:
        """Pre-governance validation. Raises `CoordinationValidationError`."""
        msg = request.message
        if not msg.sender_id:
            raise CoordinationValidationError(
                "CoordinationMessage.sender_id must be a non-empty string"
            )
        if not msg.recipient.recipient_id:
            raise CoordinationValidationError(
                "CoordinationRecipient.recipient_id must be a non-empty string"
            )
        if not self._registry.has(msg.sender_id):
            raise CoordinationValidationError(
                f"unknown sender: {msg.sender_id!r}"
            )
        # Broadcast recipients (kind=broadcast) need NOT be registered —
        # they are scope identifiers, not addressable participants. All
        # other recipient kinds MUST be registered.
        recipient_kind = msg.recipient.kind
        if (
            recipient_kind != "broadcast"
            and not self._registry.has(msg.recipient.recipient_id)
        ):
            raise CoordinationValidationError(
                f"unknown recipient: {msg.recipient.recipient_id!r}"
            )
        # in_reply_to MUST NOT equal message_id (no self-reply).
        if msg.in_reply_to == msg.message_id:
            raise CoordinationValidationError(
                "CoordinationMessage.in_reply_to cannot equal message_id"
            )

    def _build_governance_context(
        self,
        *,
        request: CoordinationDispatchRequest,
        request_id: str | None,
        resolution: AuthorityResolution,
    ) -> GovernanceContext:
        """Compose a `GovernanceContext` from the dispatch request.

        Deterministic mapping:

        * stage         ← request.enforcement_stage
        * action        ← `CoordinationGovernanceAction[message_type]`
        * resource      ← ``f"recipient:{recipient_id}"``
        * actor         ← ``f"sender:{sender_id}"``
        * subject       ← `CommunicationGovernanceSubject` (typed)
        * correlation_id← request.correlation_id (NewType over UUID)
        * metadata      ← substrate-namespaced fields + caller override

        Wedge B7: BOTH the ``CommunicationGovernanceSubject.tenant_id``
        and the ``GovernanceContext.tenant_id`` receive the SAME
        SINGULAR ``resolution.tenant_id``. They cannot drift apart —
        audit defect DR-4 sites 3 and 4 of 6 closed.
        """
        msg = request.message
        action = _governance_action_for(msg.message_type)
        resource = f"recipient:{msg.recipient.recipient_id}"
        actor = f"sender:{msg.sender_id}"

        subject = CommunicationGovernanceSubject(
            channel=f"coordination/{request.direction.value}",
            recipient_scope=msg.recipient.recipient_id,
            content_summary=msg.payload.content_type,
            tenant_id=resolution.tenant_id,
            request_id=request_id,
        )

        substrate_metadata: dict[str, object] = {
            CoordinationMetadataKey.DIRECTION.value: request.direction.value,
            CoordinationMetadataKey.MESSAGE_TYPE.value: msg.message_type.value,
            CoordinationMetadataKey.PRIORITY.value: int(msg.priority),
            CoordinationMetadataKey.SENDER.value: msg.sender_id,
            CoordinationMetadataKey.RECIPIENT.value: msg.recipient.recipient_id,
            CoordinationMetadataKey.RECIPIENT_KIND.value: msg.recipient.kind,
        }
        if msg.in_reply_to is not None:
            substrate_metadata[
                CoordinationMetadataKey.IN_REPLY_TO.value
            ] = str(msg.in_reply_to)
        if request.parent_coordination_id is not None:
            substrate_metadata[
                CoordinationMetadataKey.PARENT_COORDINATION_ID.value
            ] = str(request.parent_coordination_id)
        if request.parent_message_id is not None:
            substrate_metadata[
                CoordinationMetadataKey.PARENT_MESSAGE_ID.value
            ] = str(request.parent_message_id)

        # Caller-provided metadata is merged in BENEATH substrate keys
        # so substrate keys are authoritative (avoids accidental
        # shadowing of substrate lineage by callers).
        merged: dict[str, object] = dict(request.governance_metadata)
        merged.update(substrate_metadata)

        # Wedge 2.75-γ: full authority axis. When ``request.authority``
        # is supplied (the constitutional Wedge-B2 path) project every
        # axis onto the governance context. The tenant-coexistence
        # invariant is enforced by ``GovernanceContext.__post_init__``;
        # the resolution path above already guarantees the tenant
        # axis is reconciled, so authority.tenant_id == resolved
        # tenant on every constitutional caller.
        authority = request.authority
        return GovernanceContext(
            stage=request.enforcement_stage,
            action=action,
            resource=resource,
            actor=actor,
            # 2.5-F follow-up: ``GovernanceContext.tenant_id`` is typed
            # as ``TenantId | None``; ``AuthorityResolution.tenant_id``
            # is still the wider ``str | None`` (legacy ingress axis).
            # Wrap without mutating bytes — ``TenantId`` is a NewType
            # alias, so this is purely a static-type projection.
            tenant_id=(
                TenantId(resolution.tenant_id)
                if resolution.tenant_id is not None
                else None
            ),
            request_id=request_id,
            principal_id=(
                authority.principal_id
                if authority is not None
                else None
            ),
            organization_id=(
                authority.organization_id
                if authority is not None
                else None
            ),
            environment_id=(
                authority.environment_id
                if authority is not None
                else None
            ),
            authority=authority,
            subject=subject,
            correlation_id=request.correlation_id,
            metadata=merged,
        )

    def _map_governance(
        self, decision: Decision
    ) -> tuple[CoordinationStatus, CoordinationDispatchOutcome]:
        """Translate a `Decision` → coordination status/outcome.

        Blocking decisions raise `CoordinationGovernanceDeniedError`
        (caught by `dispatch` and translated to a DENIED result).
        Non-blocking decisions return (status, outcome).
        """
        if is_blocking_decision(decision):
            raise CoordinationGovernanceDeniedError(
                f"governance returned blocking decision: {decision.value}"
            )
        if decision is Decision.ALLOW:
            return (
                CoordinationStatus.DISPATCHED,
                CoordinationDispatchOutcome.ACCEPTED,
            )
        # DEGRADE and REDACT — both non-blocking but restrictive.
        return (
            CoordinationStatus.DEGRADED,
            CoordinationDispatchOutcome.DEGRADED,
        )

    async def _build_and_persist(
        self,
        *,
        request: CoordinationDispatchRequest,
        request_id: str | None,
        coordination_id: CoordinationId,
        status: CoordinationStatus,
        outcome: CoordinationDispatchOutcome,
        governance_decision_id: uuid.UUID | None,
        governance_chain_id: str | None,
        error: str | None,
        started_at: datetime,
        loop_start: float,
        resolution: AuthorityResolution,
        extra_metadata: dict[str, object] | None = None,
    ) -> CoordinationDispatchResult:
        """Assign sequence, build envelope, persist, build trace + result.

        Sequence assignment + record write run under a single lock so
        concurrent dispatchers observe a deterministic total order.
        Persistence failures are caught and surfaced as a
        ``PERSISTENCE_ERROR`` outcome.

        `extra_metadata` (when supplied) is merged into the envelope
        metadata BENEATH caller metadata, so substrate-added keys
        (e.g. policy evaluation id, policy aggregate decision) are
        not silently overridden by callers.
        """
        loop = asyncio.get_event_loop()
        # 2.5-D: lock-split. Pre-2.5-D the runtime held ``self._lock``
        # across the persistence ``await``, capping throughput at the
        # disk-I/O latency of the slowest writer. The doctrine is now:
        #
        #   1. Assign sequence under the lock (atomic; preserves
        #      monotonic ordering across concurrent dispatchers).
        #   2. Build the envelope outside the lock (pure data
        #      construction, no shared mutable state).
        #   3. Persist outside the lock so concurrent dispatchers can
        #      overlap their I/O.
        #
        # Failure semantics: on persistence failure the assigned
        # ``sequence`` is "burnt" — the substrate accepts gaps in the
        # sequence space rather than holding the lock for compensating
        # writes. Coordination has no contiguous-sequence invariant
        # (verified pre-refactor); the envelope on the failed result
        # is ``None`` so callers know the assigned sequence never
        # became durable.
        async with self._lock:
            self._sequence += 1
            sequence = self._sequence
        dispatched_at = datetime.now(timezone.utc)

        # Caller metadata is merged in BENEATH substrate-added
        # keys so substrate lineage (policy evaluation id,
        # aggregate decision, …) is authoritative.
        envelope_metadata: dict[str, object] = dict(request.metadata)
        if extra_metadata:
            envelope_metadata.update(extra_metadata)

        # Wedge B7: stamp the singular resolved tenant_id AND
        # the AuthoritySource that produced it. Audit defect
        # DR-4 site 5 of 6 closed.
        envelope = CoordinationEnvelope(
            coordination_id=coordination_id,
            message=request.message,
            direction=request.direction,
            status=status,
            sequence=sequence,
            runtime_instance_id=self._instance_id,
            correlation_id=request.correlation_id,
            parent_coordination_id=request.parent_coordination_id,
            parent_message_id=request.parent_message_id,
            request_id=request_id,
            tenant_id=resolution.tenant_id,
            tenant_authority_source=resolution.source.value,
            governance_decision_id=governance_decision_id,
            governance_chain_id=governance_chain_id,
            created_at=request.message.created_at,
            dispatched_at=dispatched_at,
            metadata=envelope_metadata,
        )
        record = envelope_to_record(envelope)
        try:
            await self._persistence.record_envelope(record)
        except CoordinationPersistenceError as exc:
            ended_at = datetime.now(timezone.utc)
            latency_ms = round((loop.time() - loop_start) * 1000.0, 3)
            trace = self._build_trace(
                coordination_id=coordination_id,
                envelope=envelope,
                status=CoordinationStatus.FAILED,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=latency_ms,
                error=f"{type(exc).__name__}: {exc}",
            )
            return CoordinationDispatchResult(
                coordination_id=coordination_id,
                outcome=CoordinationDispatchOutcome.PERSISTENCE_ERROR,
                trace=trace,
                envelope=None,
                error=str(exc),
                metadata=dict(request.metadata),
            )
        except Exception as exc:  # noqa: BLE001 — substrate never re-raises
            ended_at = datetime.now(timezone.utc)
            latency_ms = round((loop.time() - loop_start) * 1000.0, 3)
            trace = self._build_trace(
                coordination_id=coordination_id,
                envelope=envelope,
                status=CoordinationStatus.FAILED,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=latency_ms,
                error=f"{type(exc).__name__}: {exc}",
            )
            return CoordinationDispatchResult(
                coordination_id=coordination_id,
                outcome=CoordinationDispatchOutcome.PERSISTENCE_ERROR,
                trace=trace,
                envelope=None,
                error=f"persistence failed: {type(exc).__name__}: {exc}",
                metadata=dict(request.metadata),
            )

        ended_at = datetime.now(timezone.utc)
        latency_ms = round((loop.time() - loop_start) * 1000.0, 3)
        trace = self._build_trace(
            coordination_id=coordination_id,
            envelope=envelope,
            status=status,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            error=error,
        )
        return CoordinationDispatchResult(
            coordination_id=coordination_id,
            outcome=outcome,
            trace=trace,
            envelope=envelope,
            error=error,
            metadata=dict(request.metadata),
        )

    def _build_trace(
        self,
        *,
        coordination_id: CoordinationId,
        envelope: CoordinationEnvelope,
        status: CoordinationStatus,
        started_at: datetime,
        ended_at: datetime,
        latency_ms: float,
        error: str | None,
    ) -> CoordinationTrace:
        # The trace mirrors the envelope's authority attribution —
        # ``tenant_authority_source`` is carried verbatim so the trace
        # and the envelope cannot disagree on which input produced the
        # effective tenant. There is no independent resolution here.
        msg = envelope.message
        return CoordinationTrace(
            coordination_id=coordination_id,
            message_id=msg.message_id,
            runtime_instance_id=envelope.runtime_instance_id,
            sequence=envelope.sequence,
            sender_id=msg.sender_id,
            recipient_id=msg.recipient.recipient_id,
            recipient_kind=msg.recipient.kind,
            message_type=msg.message_type,
            direction=envelope.direction,
            priority=msg.priority,
            status=status,
            correlation_id=envelope.correlation_id,
            parent_coordination_id=envelope.parent_coordination_id,
            parent_message_id=envelope.parent_message_id,
            in_reply_to=msg.in_reply_to,
            request_id=envelope.request_id,
            tenant_id=envelope.tenant_id,
            tenant_authority_source=envelope.tenant_authority_source,
            governance_decision_id=envelope.governance_decision_id,
            governance_chain_id=envelope.governance_chain_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            error=error,
            metadata=dict(envelope.metadata),
        )

    def _fail_fast_result(
        self,
        *,
        coordination_id: CoordinationId,
        request: CoordinationDispatchRequest,
        request_id: str | None,
        started_at: datetime,
        loop_start: float,
        outcome: CoordinationDispatchOutcome,
        error: BaseException,
        status: CoordinationStatus,
        envelope: CoordinationEnvelope | None,
        resolution: AuthorityResolution,
    ) -> CoordinationDispatchResult:
        """Build a trace + result for failures that occur before persistence.

        Used for validation failures (no envelope ever constructed).

        Wedge B7: the fail-fast trace consumes the SAME resolution
        produced once at the top of ``dispatch()`` — audit defect
        DR-4 site 6 of 6 closed. The trace and the (absent) envelope
        share the same authority attribution.
        """
        loop = asyncio.get_event_loop()
        ended_at = datetime.now(timezone.utc)
        latency_ms = round((loop.time() - loop_start) * 1000.0, 3)
        msg = request.message
        trace = CoordinationTrace(
            coordination_id=coordination_id,
            message_id=msg.message_id,
            runtime_instance_id=self._instance_id,
            sequence=0,
            sender_id=msg.sender_id,
            recipient_id=msg.recipient.recipient_id,
            recipient_kind=msg.recipient.kind,
            message_type=msg.message_type,
            direction=request.direction,
            priority=msg.priority,
            status=status,
            correlation_id=request.correlation_id,
            parent_coordination_id=request.parent_coordination_id,
            parent_message_id=request.parent_message_id,
            in_reply_to=msg.in_reply_to,
            request_id=request_id,
            tenant_id=resolution.tenant_id,
            tenant_authority_source=resolution.source.value,
            governance_decision_id=None,
            governance_chain_id=None,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            error=f"{type(error).__name__}: {error}",
            metadata=dict(request.metadata),
        )
        return CoordinationDispatchResult(
            coordination_id=coordination_id,
            outcome=outcome,
            trace=trace,
            envelope=envelope,
            error=str(error),
            metadata=dict(request.metadata),
        )


# ─── Pure helpers ────────────────────────────────────────────────────


def _governance_action_for(
    message_type: CoordinationMessageType,
) -> str:
    """Map a `CoordinationMessageType` to its governance action string."""
    return {
        CoordinationMessageType.REQUEST: CoordinationGovernanceAction.REQUEST,
        CoordinationMessageType.RESPONSE: CoordinationGovernanceAction.RESPONSE,
        CoordinationMessageType.NOTIFICATION: CoordinationGovernanceAction.NOTIFICATION,
        CoordinationMessageType.HANDOFF: CoordinationGovernanceAction.HANDOFF,
        CoordinationMessageType.SIGNAL: CoordinationGovernanceAction.SIGNAL,
    }[message_type].value


# Silence the unused-import warning for `CoordinationPayload` /
# `CoordinationMessageId` / `CoordinationPriority` — referenced by
# type-checker readers of the module surface.
_ = (CoordinationPayload, CoordinationMessageId, CoordinationPriority)


__all__ = ["CoordinationRuntime"]
