# Import Laws

## Governance
Governance may not import:
- agents
- coordination
- runtime execution
- boundary adapters

## Boundary
Boundary may not directly invoke:
- governance internals
- orchestration runtime internals

## Replay
Replay systems must remain deterministic and side-effect free.

## Serialization
Serializers may not contain orchestration logic.

## Runtime
Runtime may not bypass envelopes/contracts.

## Coordination
Coordination must not mutate chronology directly.