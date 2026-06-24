"""Backfill resolution delivery for cases approved before the
``reconcile_stale_case_approvals`` delivery fix landed.

Before the fix, the reconciler drove a case's own status to ``approved``
but never flipped its bound resolution proposal/draft to
``send_eligible``/``ready`` -- so the case looked resolved while its
customer-facing reply silently never reached ``outbound.send``. The fix
closes this for every FUTURE divergence, but a case already marked
``approved`` is never re-scanned by the reconciler (its candidate query is
``WHERE status = 'awaiting_approval'``), so the historical backlog needs
this one-time pass.

SENDS A REAL REPLY TO A REAL CUSTOMER for every case it backfills. Some of
these replies are now days old -- sending a warranty reply that late may
be unwanted. Dry-run is the default; review the listed candidates and get
explicit sign-off before passing ``--apply``.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.approvals.exceptions import CaseApprovalRuntimeError
from app.approvals.persistence import PostgresCaseApprovalPersistence
from app.core.config import get_settings
from app.data_protection.crypto import DataProtectionService
from app.data_protection.kms import build_master_key_unwrap
from app.db.session import get_owner_session_factory
from app.governance.persistence import PostgresGovernanceRepository
from app.resolution.persistence import PostgresResolutionProposalPersistence
from app.runtime import ResolutionGovernanceGate, build_resolution_governance_runtime
from app.runtime.grounding import CitationCoverageGroundingChecker
from app.services.case_approval_service import CaseApprovalService
from app.sme import build_sme_review_runtime
from app.tenant.persistence import PostgresTenantConfigurationRepository

_CANDIDATES_SQL = text(
    """
    SELECT car.approval_case_id, car.tenant_id, car.resolved_by,
           car.resolution_note, rp.status AS proposal_status
    FROM case_approval_records car
    JOIN resolution_proposals rp
        ON rp.proposal_id = car.resolution_proposal_id
    WHERE car.status = 'approved'
      AND car.resolution_proposal_id IS NOT NULL
      AND rp.status = 'pending_human_approval'
      AND (
        CAST(:case_id AS uuid) IS NULL
        OR car.approval_case_id = CAST(:case_id AS uuid)
      )
    ORDER BY car.resolved_at ASC
    LIMIT :limit
    """
)


@dataclass(frozen=True, slots=True)
class BackfillResult:
    dry_run: bool
    scanned: int
    delivered: int
    cases: tuple[str, ...]
    denied: tuple[tuple[str, str], ...] = ()


def _data_protection_service(session: AsyncSession) -> DataProtectionService | None:
    settings = get_settings()
    if (
        not settings.DATA_PROTECTION_MASTER_KEYS.strip()
        and not settings.TENANT_CREDENTIAL_MASTER_KEY.strip()
    ):
        return None
    return DataProtectionService.from_settings(
        session,
        settings,
        master_key_unwrap=build_master_key_unwrap(settings),
        legacy_credential_key=settings.TENANT_CREDENTIAL_MASTER_KEY,
    )


def _build_case_approval_service(session: AsyncSession) -> CaseApprovalService:
    # resolution_governance_gate is wired (matching get_case_approval_service):
    # _deliver_resolution's revision branch fires whenever the case's
    # embedded sme_recommendation differs from the proposal's stored reply,
    # which is the norm for warranty/refund cases, not a rare edge case.
    data_protection = _data_protection_service(session)
    governance_repository = PostgresGovernanceRepository(session)
    return CaseApprovalService(
        persistence=PostgresCaseApprovalPersistence(
            session, data_protection=data_protection
        ),
        sme_runtime=build_sme_review_runtime(),
        resolution_repository=PostgresResolutionProposalPersistence(
            session, data_protection=data_protection
        ),
        governance_repository=governance_repository,
        resolution_governance_gate=ResolutionGovernanceGate(
            governance_runtime=build_resolution_governance_runtime(
                persistence=governance_repository,
                grounding_checker=CitationCoverageGroundingChecker(
                    document_repository=PostgresTenantConfigurationRepository(
                        session, data_protection=data_protection
                    ),
                ),
            )
        ),
        session=session,
    )


async def backfill_undelivered_case_resolutions(
    *,
    session: AsyncSession,
    limit: int,
    apply: bool = False,
    case_id: str | None = None,
) -> BackfillResult:
    if limit < 1:
        raise ValueError("limit must be positive")
    candidates = (
        (
            await session.execute(
                _CANDIDATES_SQL, {"limit": limit, "case_id": case_id}
            )
        )
        .mappings()
        .all()
    )
    delivered_cases: list[str] = []
    denied_cases: list[tuple[str, str]] = []
    service = _build_case_approval_service(session)
    for row in candidates:
        approval_case_id = str(row["approval_case_id"])
        tenant_id = str(row["tenant_id"])
        if not apply:
            continue
        try:
            delivered = await service.complete_reconciled_resolution(
                approval_case_id=approval_case_id,
                tenant_id=tenant_id,
                resolved_by=str(row["resolved_by"] or "unknown"),
                note=row["resolution_note"],
            )
        except CaseApprovalRuntimeError as exc:
            # A clean governance denial (e.g. ungrounded claim) -- the
            # reply is correctly held, not a script failure. Roll back
            # so this case's row is untouched and report it distinctly
            # from a delivered case.
            await session.rollback()
            denied_cases.append((approval_case_id, str(exc)))
            continue
        if delivered:
            await session.commit()
            delivered_cases.append(approval_case_id)
        else:
            await session.rollback()
    return BackfillResult(
        dry_run=not apply,
        scanned=len(candidates),
        delivered=len(delivered_cases),
        cases=tuple(
            str(row["approval_case_id"]) for row in candidates
        ) if not apply else tuple(delivered_cases),
        denied=tuple(denied_cases),
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument(
        "--case-id",
        default=None,
        help="restrict to a single approval_case_id instead of the full backlog",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually deliver (sends a real reply) instead of just listing candidates",
    )
    return parser.parse_args(argv)


async def _amain(argv: Sequence[str] | None = None) -> BackfillResult:
    args = _parse_args(argv)
    session_factory = get_owner_session_factory()
    async with session_factory() as session:
        result = await backfill_undelivered_case_resolutions(
            session=session,
            limit=args.limit,
            apply=args.apply,
            case_id=args.case_id,
        )
        print(
            {
                "dry_run": result.dry_run,
                "scanned": result.scanned,
                "delivered": result.delivered,
                "cases": list(result.cases),
                "denied": list(result.denied),
            }
        )
        return result


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
