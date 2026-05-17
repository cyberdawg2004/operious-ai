"""Decision ID generation + deterministic derivation.

`generate_decision_id` is the **default runtime path** — UUID4,
unique across live execution. This is what `GovernanceRuntime.evaluate`
calls when constructing a decision.

`derive_decision_id(seed=...)` is the **replay / deterministic path**
— UUID5 keyed against `DECISION_NAMESPACE`. Same seed → same UUID.
Used by:

* replay tools that need byte-identical reconstruction,
* tests that assert decision identity stability.

The substrate is explicit about which path runtime uses (uuid4) and
which path replay uses (uuid5 with a stable seed). There is no
implicit ID stability in production — see
`docs/architecture/governance-replay-semantics.md`.
"""

from __future__ import annotations

import uuid

# Fixed namespace for the governance substrate. Generated once,
# pinned forever. Changing this would invalidate every previously
# derived UUID — treat it as a permanent constant.
DECISION_NAMESPACE: uuid.UUID = uuid.UUID("4d2c10a2-6c00-4f7c-8b3a-1f8d0c7e0001")


def generate_decision_id() -> uuid.UUID:
    """Return a fresh UUID4 — the runtime path.

    Unique across live runtime execution; never collides with prior
    decision IDs. Used by `GovernanceRuntime` when constructing a
    `GovernanceDecision` for live evaluation.
    """
    return uuid.uuid4()


def derive_decision_id(*, seed: str) -> uuid.UUID:
    """Deterministically derive a decision ID from a stable seed.

    Replay-safe: same seed → same UUID. Use this from:

    * replay tools that reconstruct historical decisions and need
      byte-identical IDs,
    * tests that assert ID stability,
    * audit-reconciliation tools that need to correlate live
      decisions against simulated ones (the tool seeds on a stable
      function of decision inputs).

    NEVER use this from `GovernanceRuntime` — runtime uses
    `generate_decision_id`. Mixing paths would silently re-derive
    IDs across requests with overlapping seeds, breaking the
    "every live decision has a unique ID" invariant.
    """
    if not seed:
        raise ValueError("derive_decision_id requires a non-empty seed")
    return uuid.uuid5(DECISION_NAMESPACE, seed)


__all__ = [
    "DECISION_NAMESPACE",
    "generate_decision_id",
    "derive_decision_id",
]
