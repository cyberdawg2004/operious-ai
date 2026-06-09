"""Backfill durable ingress dispatch outbox intents.

Dry-run is the default. Use ``--apply`` to insert idempotent pending
outbox rows for eligible captured ingress records that have neither an
existing dispatch outbox row nor a dispatch session.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.boundary.identity import BoundaryIngressId
from app.boundary.ingress_dispatch_outbox import (
    PostgresIngressDispatchOutboxPersistence,
    is_dispatch_outbox_eligible,
)
from app.boundary.persistence import BoundaryIngressRecord, PostgresBoundaryPersistence
from app.db.session import get_owner_session_factory


@dataclass(frozen=True, slots=True)
class BackfillResult:
    dry_run: bool
    scanned: int
    eligible: int
    inserted: int
    ingress_ids: tuple[str, ...]


async def backfill_ingress_dispatch_outbox(
    *,
    session: AsyncSession,
    tenant_id: str | None,
    since: datetime,
    limit: int,
    apply: bool = False,
) -> BackfillResult:
    if since.tzinfo is None:
        raise ValueError("since must be timezone-aware")
    if limit < 1:
        raise ValueError("limit must be positive")
    ids = await _candidate_ingress_ids(
        session=session,
        tenant_id=tenant_id,
        since=since,
        limit=limit,
    )
    repo = PostgresBoundaryPersistence(session)
    records: list[BoundaryIngressRecord] = []
    for ingress_id in ids:
        record = await repo.get_ingress(
            BoundaryIngressId(ingress_id),
            expected_tenant_id=tenant_id,
        )
        if record is None:
            continue
        if is_dispatch_outbox_eligible(record):
            records.append(record)
    inserted = ()
    if apply and records:
        inserted = await PostgresIngressDispatchOutboxPersistence(
            session
        ).bulk_create_outbox_for_ingress(tuple(records))
        await session.commit()
    return BackfillResult(
        dry_run=not apply,
        scanned=len(ids),
        eligible=len(records),
        inserted=len(inserted),
        ingress_ids=tuple(str(record.ingress_id) for record in records),
    )


async def _candidate_ingress_ids(
    *,
    session: AsyncSession,
    tenant_id: str | None,
    since: datetime,
    limit: int,
) -> tuple[BoundaryIngressId, ...]:
    params: dict[str, object] = {
        "since": since,
        "limit": limit,
    }
    tenant_filter = ""
    if tenant_id is not None:
        tenant_filter = "AND b.tenant_id = :tenant_id"
        params["tenant_id"] = tenant_id
    result = await session.execute(
        text(f"""
            SELECT b.ingress_id
            FROM boundary_ingress b
            WHERE b.received_at >= :since
              {tenant_filter}
              AND b.tenant_id IS NOT NULL
              AND b.normalization_status = 'ok'
              AND b.replay_disposition = 'new'
              AND b.event_id IS NOT NULL
              AND COALESCE(
                    b.metadata->>'tenant_channel.channel_type',
                    b.metadata->>'batch.channel_type',
                    b.metadata->>'ticket.channel',
                    b.canonical_payload->>'channel_type',
                    b.source_type
                  ) IN ('email', 'whatsapp', 'shopify')
              AND NOT EXISTS (
                    SELECT 1
                    FROM ingress_dispatch_outbox ido
                    WHERE ido.ingress_id = b.ingress_id
                  )
              AND NOT EXISTS (
                    SELECT 1
                    FROM operational_sessions s
                    WHERE s.tenant_id = b.tenant_id
                      AND s.metadata->>'boundary.ingress_id' = b.ingress_id::text
                  )
            ORDER BY b.received_at ASC, b.ingress_id ASC
            LIMIT :limit
            """),
        params,
    )
    return tuple(BoundaryIngressId(value) for value in result.scalars())


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill ingress dispatch outbox rows.",
    )
    parser.add_argument("--tenant-id", default=None)
    parser.add_argument(
        "--since-hours",
        type=int,
        default=24,
        help="Bound the scan to ingress received within this many hours.",
    )
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args(argv)


async def _amain(argv: Sequence[str] | None = None) -> BackfillResult:
    args = _parse_args(argv)
    if args.since_hours < 1:
        raise ValueError("--since-hours must be positive")
    since = datetime.now(tz=timezone.utc) - timedelta(hours=args.since_hours)
    session_factory = get_owner_session_factory()
    async with session_factory() as session:
        result = await backfill_ingress_dispatch_outbox(
            session=session,
            tenant_id=args.tenant_id,
            since=since,
            limit=args.limit,
            apply=args.apply,
        )
        print(
            {
                "dry_run": result.dry_run,
                "scanned": result.scanned,
                "eligible": result.eligible,
                "inserted": result.inserted,
                "ingress_ids": list(result.ingress_ids),
            }
        )
        return result


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
