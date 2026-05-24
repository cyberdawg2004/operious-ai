"""Decision ID generation + deterministic derivation.

`generate_decision_id` is the emergency runtime fallback — UUID5
over a per-process boot nonce plus a monotonic counter. Normal
persisted governance paths should supply `governance.decision_seed`
so the decision ID is derived from domain lineage instead of the
fallback.

`derive_decision_id(seed=...)` is the **replay / deterministic path**
— UUID5 keyed against `DECISION_NAMESPACE`. Same seed → same UUID.
Used by:

* replay tools that need byte-identical reconstruction,
* tests that assert decision identity stability.

The substrate is explicit about which path live lineage should use
(stable UUID5 seeds) and which path remains only as a collision-safe
fallback. There is no implicit ID stability in the fallback — see
`docs/architecture/governance-replay-semantics.md`.
"""

from __future__ import annotations

import itertools
import secrets
import uuid

# Fixed namespace for the governance substrate. Generated once,
# pinned forever. Changing this would invalidate every previously
# derived UUID — treat it as a permanent constant.
DECISION_NAMESPACE: uuid.UUID = uuid.UUID("4d2c10a2-6c00-4f7c-8b3a-1f8d0c7e0001")
_RUNTIME_BOOT_ID = secrets.token_urlsafe(32)
_RUNTIME_COUNTER = itertools.count()


def generate_decision_id() -> uuid.UUID:
    """Return a fresh UUID5 fallback ID for unseeded runtime callers.

    The seed is boot-scoped so a worker restart cannot replay
    ``runtime|decision|0`` into an existing production decision row.
    Persisted governance paths should still prefer
    ``derive_decision_id(seed=...)`` with a domain-specific seed.
    """
    return uuid.uuid5(
        DECISION_NAMESPACE,
        f"runtime|decision|{_RUNTIME_BOOT_ID}|{next(_RUNTIME_COUNTER)}",
    )


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
