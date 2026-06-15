"""Backfill at-rest encryption for sensitive fields written before the
``PostgresBoundaryPersistence`` / ``PostgresResolutionProposalPersistence``
composition-root wiring fix.

Touches only rows that are currently plaintext:

* ``boundary_ingress.canonical_payload['text']`` (JSONB ``__op_dp__`` envelope)
* ``resolution_proposals.proposed_customer_reply`` / ``evidence`` (TEXT ``opdp:v1:`` /
  JSONB envelope)
* ``resolution_outbound_drafts.draft_body`` / ``metadata`` (TEXT ``opdp:v1:`` /
  JSONB envelope)

Dry-run is the default. Use ``--apply`` to persist -- which additionally
requires ``--backup-path`` pointing at a fresh database backup; the script
refuses to run with ``--apply`` otherwise.

The whole run (all tenants) executes inside a single database transaction.
Each migrated row is immediately decrypted back via the same data-protection
service and compared against the captured plaintext; any mismatch aborts
the entire run with a rollback, so either every row verifies or nothing is
persisted.

The command never prints plaintext field contents.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.boundary.db.models import BoundaryIngressRow
from app.boundary.persistence.postgres import (
    PostgresBoundaryPersistence,
    _ingress_row_to_record,
)
from app.core.config import get_settings
from app.data_protection.crypto import DataProtectionService
from app.data_protection.kms import build_master_key_unwrap
from app.db.session import dispose_engine, get_owner_session_factory
from app.resolution.db.models import ResolutionOutboundDraftRow, ResolutionProposalRow
from app.resolution.persistence.postgres import (
    PostgresResolutionProposalPersistence,
    _draft_row_to_record,
    _row_to_record,
)

_BACKUP_MAX_AGE_SECONDS = 24 * 60 * 60


class _DryRunRollback(Exception):
    """Sentinel used to unwind the single transaction on a dry run."""


class BackfillVerificationError(RuntimeError):
    """Raised when a freshly-migrated row fails to decrypt back to its
    original plaintext. Aborts and rolls back the whole run."""


@dataclass(frozen=True, slots=True)
class TenantBackfillSummary:
    tenant_id: str
    ingress_candidates: int
    ingress_migrated: int
    proposal_candidates: int
    proposal_migrated: int
    draft_candidates: int
    draft_migrated: int


def _data_protection_service(session: AsyncSession) -> DataProtectionService:
    settings = get_settings()
    if (
        not settings.DATA_PROTECTION_MASTER_KEYS.strip()
        and not settings.TENANT_CREDENTIAL_MASTER_KEY.strip()
    ):
        raise SystemExit(
            "no data-protection master key configured "
            "(DATA_PROTECTION_MASTER_KEYS / TENANT_CREDENTIAL_MASTER_KEY) -- "
            "refusing to run: _protect_* would silently no-op and the "
            "round-trip verification would not catch it"
        )
    return DataProtectionService.from_settings(
        session,
        settings,
        master_key_unwrap=build_master_key_unwrap(settings),
        legacy_credential_key=settings.TENANT_CREDENTIAL_MASTER_KEY,
    )


async def _tenant_ids(session: AsyncSession) -> list[str]:
    rows = await session.execute(
        text(
            "select distinct tenant_id from boundary_ingress "
            "union "
            "select distinct tenant_id from resolution_proposals"
        )
    )
    return sorted({str(r[0]) for r in rows if r[0] is not None})


async def _set_tenant_scope(session: AsyncSession, tenant_id: str) -> None:
    # is_local=true (third arg) so the setting reverts automatically at the
    # end of the single overall transaction and can be re-set per tenant.
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
        {"tenant": tenant_id},
    )


async def backfill_tenant(
    session: AsyncSession,
    *,
    tenant_id: str,
    data_protection: DataProtectionService,
    apply: bool,
) -> TenantBackfillSummary:
    boundary_repo = PostgresBoundaryPersistence(session, data_protection=data_protection)
    resolution_repo = PostgresResolutionProposalPersistence(
        session, data_protection=data_protection
    )

    ingress_candidates = 0
    ingress_migrated = 0
    ingress_rows = (
        (
            await session.execute(
                select(BoundaryIngressRow).where(
                    BoundaryIngressRow.tenant_id == tenant_id,
                    func.jsonb_typeof(BoundaryIngressRow.canonical_payload["text"])
                    == "string",
                )
            )
        )
        .scalars()
        .all()
    )
    for row in ingress_rows:
        ingress_candidates += 1
        record = _ingress_row_to_record(row)
        original_payload = dict(record.canonical_payload)
        protected = await boundary_repo._protect_ingress(record)
        decrypted = await data_protection.decrypt_json_values(protected.canonical_payload)
        if decrypted != original_payload:
            raise BackfillVerificationError(
                f"boundary_ingress row {row.ingress_id} failed round-trip verification"
            )
        if apply:
            row.canonical_payload = dict(protected.canonical_payload)
            ingress_migrated += 1

    proposal_candidates = 0
    proposal_migrated = 0
    proposal_rows = (
        (
            await session.execute(
                select(ResolutionProposalRow).where(
                    ResolutionProposalRow.tenant_id == tenant_id,
                    ResolutionProposalRow.proposed_customer_reply.notlike("opdp:v1:%"),
                )
            )
        )
        .scalars()
        .all()
    )
    for row in proposal_rows:
        proposal_candidates += 1
        record = _row_to_record(row)
        original_reply = record.proposed_customer_reply
        original_evidence = [dict(item) for item in record.evidence]
        protected = await resolution_repo._protect_proposal(record)
        decrypted_reply = await data_protection.decrypt_text(protected.proposed_customer_reply)
        decrypted_evidence = [
            await data_protection.decrypt_json_values(item) for item in protected.evidence
        ]
        if decrypted_reply != original_reply or decrypted_evidence != original_evidence:
            raise BackfillVerificationError(
                f"resolution_proposals row {row.proposal_id} failed round-trip verification"
            )
        if apply:
            row.proposed_customer_reply = protected.proposed_customer_reply
            row.evidence = [dict(item) for item in protected.evidence]
            proposal_migrated += 1

    draft_candidates = 0
    draft_migrated = 0
    draft_rows = (
        (
            await session.execute(
                select(ResolutionOutboundDraftRow).where(
                    ResolutionOutboundDraftRow.tenant_id == tenant_id,
                    ResolutionOutboundDraftRow.draft_body.notlike("opdp:v1:%"),
                )
            )
        )
        .scalars()
        .all()
    )
    for row in draft_rows:
        draft_candidates += 1
        record = _draft_row_to_record(row)
        original_body = record.draft_body
        original_metadata = dict(record.metadata)
        protected = await resolution_repo._protect_draft(record)
        decrypted_body = await data_protection.decrypt_text(protected.draft_body)
        decrypted_metadata = await data_protection.decrypt_json_values(protected.metadata)
        if decrypted_body != original_body or decrypted_metadata != original_metadata:
            raise BackfillVerificationError(
                f"resolution_outbound_drafts row {row.draft_id} failed round-trip verification"
            )
        if apply:
            row.draft_body = protected.draft_body
            row.metadata_json = dict(protected.metadata)
            draft_migrated += 1

    return TenantBackfillSummary(
        tenant_id=tenant_id,
        ingress_candidates=ingress_candidates,
        ingress_migrated=ingress_migrated,
        proposal_candidates=proposal_candidates,
        proposal_migrated=proposal_migrated,
        draft_candidates=draft_candidates,
        draft_migrated=draft_migrated,
    )


def _check_backup_path(backup_path: str) -> None:
    if not os.path.isfile(backup_path):
        raise SystemExit(f"--backup-path {backup_path!r} does not exist or is not a file")
    size = os.path.getsize(backup_path)
    if size <= 0:
        raise SystemExit(f"--backup-path {backup_path!r} is empty -- refusing to --apply")
    age_seconds = time.time() - os.path.getmtime(backup_path)
    if age_seconds > _BACKUP_MAX_AGE_SECONDS:
        raise SystemExit(
            f"--backup-path {backup_path!r} is {age_seconds / 3600:.1f}h old "
            f"(> {_BACKUP_MAX_AGE_SECONDS / 3600:.0f}h) -- take a fresh backup before --apply"
        )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tenant-id",
        default=None,
        help="Restrict the backfill to one tenant id.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist the re-encryption. Omit for dry-run.",
    )
    parser.add_argument(
        "--backup-path",
        default=None,
        help=(
            "Path to a fresh database backup. Required with --apply; the "
            "script refuses to run otherwise."
        ),
    )
    return parser.parse_args(argv)


async def _main_async(args: argparse.Namespace) -> int:
    if args.apply:
        if not args.backup_path:
            raise SystemExit("--apply requires --backup-path pointing at a fresh database backup")
        _check_backup_path(args.backup_path)

    session_factory = get_owner_session_factory()
    summaries: list[TenantBackfillSummary] = []

    try:
        async with session_factory() as session:
            async with session.begin():
                tenant_ids = [args.tenant_id] if args.tenant_id else await _tenant_ids(session)
                for tenant_id in tenant_ids:
                    await _set_tenant_scope(session, tenant_id)
                    data_protection = _data_protection_service(session)
                    summary = await backfill_tenant(
                        session,
                        tenant_id=tenant_id,
                        data_protection=data_protection,
                        apply=args.apply,
                    )
                    summaries.append(summary)
                if not args.apply:
                    raise _DryRunRollback()
    except _DryRunRollback:
        pass

    for summary in summaries:
        print(
            "data-protection backfill "
            f"mode={'apply' if args.apply else 'dry-run'} "
            f"tenant={summary.tenant_id} "
            f"ingress_candidates={summary.ingress_candidates} "
            f"ingress_migrated={summary.ingress_migrated} "
            f"proposal_candidates={summary.proposal_candidates} "
            f"proposal_migrated={summary.proposal_migrated} "
            f"draft_candidates={summary.draft_candidates} "
            f"draft_migrated={summary.draft_migrated}"
        )

    await dispose_engine()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_main_async(_parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
