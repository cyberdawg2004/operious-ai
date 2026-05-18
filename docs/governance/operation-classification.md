# Operational Classification Doctrine

Purpose:
Define constitutional operational categories for governance visibility.

---

# Operation Categories

## Informational
Read-only operational requests.

Examples:
- inspection
- replay viewing
- audit reading

Risk:
Low

---

## Operational
Normal operational execution.

Examples:
- ticket updates
- routing
- coordination
- escalation handling

Risk:
Medium

---

## Governance-Sensitive
Operations affecting authority, policy, escalation, compliance, or replay.

Examples:
- escalation overrides
- supervisor intervention
- chronology mutation
- replay corrections

Risk:
High

---

## Constitutional
Operations affecting substrate integrity.

Examples:
- runtime law modification
- governance modification
- replay doctrine modification
- chronology doctrine modification

Risk:
Critical

---

# Constitutional Principle

Future governance routing should classify operations BEFORE execution.

---

# Code anchor (Phase 2.5-H)

The doctrinal categories above are *risk-tier* classifications.
The closed wire-vocabulary substrates stamp on boundary traces is
defined separately in `app.governance.classification` —
`OperationClassification` (e.g. `conversation.turn`,
`data.retrieval`, `governance.evaluation`). The risk-tier in this
doc and the wire vocabulary in code are intentionally separate
axes: a single wire classification (e.g. `tool.invocation`) may
land in different risk tiers depending on the substrate routing
decision, which is exactly why the wire vocabulary is closed and
the risk-tier mapping is policy-driven.