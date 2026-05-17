"""`ChainDepthEvaluator` — recursive-delegation protection.

Compares the caller-declared `chain_depth` against the topology's
`max_chain_depth`. When the depth would exceed the topology's
limit, emits a single `DEPTH_EXCEEDED` finding.

`chain_depth` discipline:

* Top-level dispatches (no parent) MUST carry `chain_depth = 0`.
* Child dispatches MUST carry `chain_depth = parent.chain_depth + 1`.
* The substrate trusts the caller's reported value. Misreporting
  produces audit-visible misalignment between the trace and the
  parent_coordination_id lineage; the substrate does not validate
  it against persistence in the dispatch hot path.

The evaluator is silent when within the limit (the apex aggregator
defaults to `ALLOWED` in the absence of findings).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import ClassVar

from app.coordination.topology.contracts.requests import (
    CoordinationTopologyEvaluationRequest,
)
from app.coordination.topology.enums import (
    CoordinationTopologyDecision,
)
from app.coordination.topology.evaluators.base import (
    BaseCoordinationTopologyEvaluator,
)
from app.coordination.topology.identity import derive_finding_id
from app.coordination.topology.models.findings import (
    CoordinationTopologyFinding,
)
from app.coordination.topology.models.topology import (
    CoordinationTopology,
)
from app.coordination.topology.taxonomy import (
    CoordinationTopologyFindingCode,
)


class ChainDepthEvaluator(BaseCoordinationTopologyEvaluator):
    """Bound coordination chain depth against `topology.max_chain_depth`."""

    name: ClassVar[str] = "chain_depth"

    def __init__(self, topology: CoordinationTopology) -> None:
        self._topology = topology

    @property
    def topology(self) -> CoordinationTopology:
        return self._topology

    async def evaluate(
        self, request: CoordinationTopologyEvaluationRequest
    ) -> tuple[CoordinationTopologyFinding, ...]:
        max_depth = self._topology.max_chain_depth
        if request.chain_depth < max_depth:
            return ()
        seed_uuid = (
            request.evaluation_id_override
            if request.evaluation_id_override is not None
            else request.coordination_id
        )
        finding_id = derive_finding_id(
            evaluation_id=seed_uuid,
            evaluator_name=ChainDepthEvaluator.name,
            code=str(
                CoordinationTopologyFindingCode.CHAIN_DEPTH_EXCEEDED
            ),
            ordinal=0,
        )
        return (
            CoordinationTopologyFinding(
                finding_id=finding_id,
                evaluator_name=ChainDepthEvaluator.name,
                decision=CoordinationTopologyDecision.DEPTH_EXCEEDED,
                code=str(
                    CoordinationTopologyFindingCode.CHAIN_DEPTH_EXCEEDED
                ),
                message=(
                    f"chain depth {request.chain_depth} ≥ "
                    f"max_chain_depth {max_depth}"
                ),
                detected_at=datetime.now(timezone.utc),
                metadata={
                    "chain_depth": request.chain_depth,
                    "max_chain_depth": max_depth,
                },
            ),
        )


__all__ = ["ChainDepthEvaluator"]
