"""Coordination policy enum vocabulary — pinned wire-format values.

Four typed vocabularies the coordination-policy substrate speaks in.
All are `StrEnum` so JSON round-trips are transparent and the
persistence layer can store the string value verbatim.

Wire-format discipline: every value below is pinned. Renaming a value
is a breaking change to every previously persisted policy record;
the `tests/test_coordination_policy_invariants.py` catalogue
surfaces accidental drift at import time.

Semantic separation (Sprint L2 Rule 2):

* `CoordinationPolicyDecision` answers *topology authorization*
  ("is this sender→recipient pair authorised under the deployment
  topology?"). It is NOT a governance decision. The governance
  substrate retains its own `Decision` vocabulary; the two never
  cross.
* `CoordinationPolicyScope` classifies WHAT a policy / rule scopes
  over (sender identity, direction, tenant, etc.).
* `CoordinationRestrictionType` enumerates the kinds of operational
  restriction a `RESTRICT` decision can attach. They are *advisory*
  to the orchestration layer; the substrate records them but does
  NOT enforce delivery semantics (Rule 3 — no orchestration
  mutation).
* `CoordinationEscalationType` enumerates the kinds of escalation an
  `ESCALATE` decision can demand. Same advisory discipline.

The two restriction / escalation enums deliberately do NOT mirror
governance's `RestrictionKind`. Topology restrictions are a
different operational concern from governance restrictions; mixing
the vocabularies would erode the substrate-isolation invariant.
"""

from __future__ import annotations

from enum import StrEnum


class CoordinationPolicyDecision(StrEnum):
    """Apex topology-authorization verdict.

    Precedence (most-restrictive wins) is encoded in
    `coordination_policy_precedence` in `app.coordination.policy.taxonomy`;
    no other layer re-encodes the ordering.

    ALLOW    — topology is authorised; dispatch proceeds to governance.
    ANNOTATE — authorised, with one or more annotations recorded on
                the evaluation envelope. Dispatch proceeds to
                governance; the annotations surface in audit trails.
    RESTRICT — authorised, with one or more
                `CoordinationPolicyRestriction`s attached. Dispatch
                proceeds to governance; the restrictions are advisory
                and recorded for downstream orchestration to honour.
    ESCALATE — authorisation is conditional on an out-of-band
                escalation. Dispatch is BLOCKED until the escalation
                pathway resolves. Policy never executes the
                escalation — it merely records the requirement.
    DENY     — topology is NOT authorised. Dispatch is BLOCKED.
                Governance does NOT run.

    Operational note: ESCALATE and DENY are both blocking, but the
    semantic distinction matters for audit / supervisor consumption.
    `is_blocking_policy_decision` (see `taxonomy.py`) is the single
    authority on "does this verdict halt dispatch".
    """

    ALLOW = "allow"
    ANNOTATE = "annotate"
    RESTRICT = "restrict"
    ESCALATE = "escalate"
    DENY = "deny"


class CoordinationPolicyScope(StrEnum):
    """Classification of what a policy / rule scopes over.

    Used by evaluators to declare which dimension of the dispatch
    they inspect, and by audit dashboards to group findings by
    semantic axis.

    SENDER          — rule scopes over the sender identity.
    RECIPIENT       — rule scopes over the recipient identity.
    DIRECTION       — rule scopes over the `CoordinationDirection`.
    MESSAGE_TYPE    — rule scopes over the `CoordinationMessageType`.
    TOPOLOGY        — rule scopes over the (sender, recipient) pair.
    TENANT          — rule scopes over tenant boundaries.
    ESCALATION      — rule emits an escalation requirement.
    GLOBAL          — applies to every dispatch regardless of axis.
    """

    SENDER = "sender"
    RECIPIENT = "recipient"
    DIRECTION = "direction"
    MESSAGE_TYPE = "message_type"
    TOPOLOGY = "topology"
    TENANT = "tenant"
    ESCALATION = "escalation"
    GLOBAL = "global"


class CoordinationRestrictionType(StrEnum):
    """Kinds of operational restriction a `RESTRICT` decision attaches.

    Advisory only — the coordination substrate records them; the
    orchestration layer (or recipient agent's own runtime) is
    responsible for honouring them. Policy MUST NOT mutate dispatch
    behaviour (Rule 3).

    SENDER_RESTRICTION       — sender identity has constrained
                                authority for THIS dispatch class.
    RECIPIENT_RESTRICTION    — recipient has constrained acceptance
                                authority.
    DIRECTION_RESTRICTION    — direction may be enabled only under
                                certain conditions captured in the
                                restriction metadata.
    TENANT_RESTRICTION       — cross-tenant boundary applies.
    MESSAGE_TYPE_RESTRICTION — only specific message types are
                                authorised for this topology.
    PRIORITY_CAP             — priority is capped to a maximum value.
    METADATA_REDACTION       — recipient must observe redacted
                                metadata fields.
    AUDIT_AMPLIFICATION      — this dispatch requires elevated audit
                                visibility downstream.
    """

    SENDER_RESTRICTION = "sender_restriction"
    RECIPIENT_RESTRICTION = "recipient_restriction"
    DIRECTION_RESTRICTION = "direction_restriction"
    TENANT_RESTRICTION = "tenant_restriction"
    MESSAGE_TYPE_RESTRICTION = "message_type_restriction"
    PRIORITY_CAP = "priority_cap"
    METADATA_REDACTION = "metadata_redaction"
    AUDIT_AMPLIFICATION = "audit_amplification"


class CoordinationEscalationType(StrEnum):
    """Kinds of escalation an `ESCALATE` decision can demand.

    Advisory only — policy never invokes an escalation; it merely
    records that the dispatch is conditional on one. The
    orchestration layer + escalation runtimes (future sprints) act
    on the demand.

    HUMAN_REVIEW             — out-of-band human review required.
    TENANT_OWNER_APPROVAL    — tenant owner must approve.
    CROSS_TENANT_AUTHORITY   — cross-tenant authority must approve.
    SUPERVISOR_NOTIFICATION  — supervisor runtime must be notified
                                (read-only — supervisor remains a
                                read-only evaluator; Rule 7).
    GOVERNANCE_ESCALATION    — escalate to the governance substrate
                                for further enforcement evaluation.
    OPERATIONAL_REVIEW       — operational on-call review required.
    """

    HUMAN_REVIEW = "human_review"
    TENANT_OWNER_APPROVAL = "tenant_owner_approval"
    CROSS_TENANT_AUTHORITY = "cross_tenant_authority"
    SUPERVISOR_NOTIFICATION = "supervisor_notification"
    GOVERNANCE_ESCALATION = "governance_escalation"
    OPERATIONAL_REVIEW = "operational_review"


__all__ = [
    "CoordinationPolicyDecision",
    "CoordinationPolicyScope",
    "CoordinationRestrictionType",
    "CoordinationEscalationType",
]
