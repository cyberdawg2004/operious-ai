# Constitutional Merge Review Rules

Before merging operational changes:

## Replay
- Does this preserve replay reconstruction?

## Chronology
- Does this preserve chronology continuity?

## Lineage
- Does this preserve lineage continuity?

## Governance
- Does this bypass governance visibility?

## Authority
- Does this weaken authority propagation?

## Determinism
- Does this introduce nondeterministic execution?

## Boundaries
- Does this weaken bounded context integrity?

## Runtime
- Does this introduce hidden orchestration?

If these questions cannot be answered clearly:
DO NOT MERGE.