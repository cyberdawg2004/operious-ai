#!/usr/bin/env python3
"""Dry-run-first S-10 job for Anker legacy knowledge ciphertext rewrap."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.data_protection.crypto import DataProtectionService  # noqa: E402
from app.db.url import build_database_engine_config  # noqa: E402
from app.tenant.chronology import canonical_sha256  # noqa: E402
from app.tenant.db.models import (  # noqa: E402
    TenantKnowledgeDocumentRow,
    TenantKnowledgeDocumentVersionRow,
)

ANKER_TENANT_ID: Final[str] = "anker-pilot"
ANKER_DOCUMENT_TITLES: Final[tuple[str, ...]] = (
    "Anker Pilot Demo - Charging Issue Policy",
    "Anker Pilot Demo - Returns And Refund Policy",
    "Anker Pilot Demo - Warranty Terms",
    "Anker Pilot Demo - Escalation Matrix",
    "Anker Pilot Demo - Product Defect Classification Guide",
)
ENVELOPE_TEXT_PREFIX: Final[str] = "opdp:v1:"
LEGACY_DIRECT: Final[str] = "legacy-direct"
ENVELOPE: Final[str] = "envelope"


@dataclass(frozen=True, slots=True)
class RewrapRecordReport:
    table: str
    document_id: str
    title: str
    before_scheme: str
    after_scheme: str
    changed: bool
    version: int | None = None
    content_sha256: str | None = None
    hash_verified: bool | None = None


@dataclass(frozen=True, slots=True)
class RewrapSummary:
    tenant_id: str
    dry_run: bool
    scanned_documents: int
    scanned_versions: int
    legacy_documents: int
    legacy_versions: int
    changed_documents: int
    changed_versions: int
    hash_verified_versions: int
    records: tuple[RewrapRecordReport, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["records"] = [asdict(record) for record in self.records]
        return payload


async def run_rewrap(
    session: AsyncSession,
    *,
    data_protection: DataProtectionService,
    tenant_id: str = ANKER_TENANT_ID,
    titles: tuple[str, ...] = ANKER_DOCUMENT_TITLES,
    execute: bool = False,
) -> RewrapSummary:
    """Inspect or rewrap matching Anker knowledge rows.

    Dry-run uses a nested transaction so simulated data-key creation is
    rolled back before the function returns.
    """

    if execute:
        return await _run_rewrap_once(
            session,
            data_protection=data_protection,
            tenant_id=tenant_id,
            titles=titles,
            execute=True,
        )

    nested = await session.begin_nested()
    try:
        summary = await _run_rewrap_once(
            session,
            data_protection=data_protection,
            tenant_id=tenant_id,
            titles=titles,
            execute=False,
        )
    finally:
        await nested.rollback()
    return summary


async def _run_rewrap_once(
    session: AsyncSession,
    *,
    data_protection: DataProtectionService,
    tenant_id: str,
    titles: tuple[str, ...],
    execute: bool,
) -> RewrapSummary:
    documents = tuple(
        (
            await session.execute(
                select(TenantKnowledgeDocumentRow)
                .where(
                    TenantKnowledgeDocumentRow.tenant_id == tenant_id,
                    TenantKnowledgeDocumentRow.title.in_(titles),
                )
                .order_by(TenantKnowledgeDocumentRow.title)
            )
        ).scalars()
    )
    versions = tuple(
        (
            await session.execute(
                select(TenantKnowledgeDocumentVersionRow)
                .where(
                    TenantKnowledgeDocumentVersionRow.tenant_id == tenant_id,
                    TenantKnowledgeDocumentVersionRow.title.in_(titles),
                )
                .order_by(
                    TenantKnowledgeDocumentVersionRow.title,
                    TenantKnowledgeDocumentVersionRow.version,
                )
            )
        ).scalars()
    )

    reports: list[RewrapRecordReport] = []
    for row in documents:
        reports.append(
            await _process_document_row(
                row,
                data_protection=data_protection,
                execute=execute,
            )
        )
    for row in versions:
        reports.append(
            await _process_version_row(
                row,
                data_protection=data_protection,
                execute=execute,
            )
        )

    if execute:
        await session.flush()

    return RewrapSummary(
        tenant_id=tenant_id,
        dry_run=not execute,
        scanned_documents=len(documents),
        scanned_versions=len(versions),
        legacy_documents=sum(
            1
            for report in reports
            if report.table == "tenant_knowledge_documents"
            and report.before_scheme == LEGACY_DIRECT
        ),
        legacy_versions=sum(
            1
            for report in reports
            if report.table == "tenant_knowledge_document_versions"
            and report.before_scheme == LEGACY_DIRECT
        ),
        changed_documents=sum(
            1
            for report in reports
            if report.table == "tenant_knowledge_documents" and report.changed
        ),
        changed_versions=sum(
            1
            for report in reports
            if report.table == "tenant_knowledge_document_versions" and report.changed
        ),
        hash_verified_versions=sum(
            1 for report in reports if report.hash_verified is True
        ),
        records=tuple(reports),
    )


async def _process_document_row(
    row: TenantKnowledgeDocumentRow,
    *,
    data_protection: DataProtectionService,
    execute: bool,
) -> RewrapRecordReport:
    before_scheme = content_scheme(row.content)
    plaintext = await data_protection.decrypt_text(row.content)
    encrypted = await _simulate_or_apply_envelope(
        row.content,
        plaintext=plaintext,
        tenant_id=row.tenant_id,
        field="tenant_knowledge_documents.content",
        data_protection=data_protection,
    )
    if execute and encrypted is not None:
        row.content = encrypted
    after_content = row.content if execute else encrypted or row.content
    roundtrip = await data_protection.decrypt_text(after_content)
    if roundtrip != plaintext:
        raise RuntimeError(
            f"document {row.document_id} failed read-back after simulated rewrap"
        )
    return RewrapRecordReport(
        table="tenant_knowledge_documents",
        document_id=str(row.document_id),
        title=row.title,
        before_scheme=before_scheme,
        after_scheme=content_scheme(after_content),
        changed=encrypted is not None,
    )


async def _process_version_row(
    row: TenantKnowledgeDocumentVersionRow,
    *,
    data_protection: DataProtectionService,
    execute: bool,
) -> RewrapRecordReport:
    before_scheme = content_scheme(row.content)
    plaintext = await data_protection.decrypt_text(row.content)
    _verify_version_hash(row, plaintext)
    encrypted = await _simulate_or_apply_envelope(
        row.content,
        plaintext=plaintext,
        tenant_id=row.tenant_id,
        field="tenant_knowledge_document_versions.content",
        data_protection=data_protection,
    )
    if execute and encrypted is not None:
        row.content = encrypted
    after_content = row.content if execute else encrypted or row.content
    roundtrip = await data_protection.decrypt_text(after_content)
    _verify_version_hash(row, roundtrip)
    return RewrapRecordReport(
        table="tenant_knowledge_document_versions",
        document_id=str(row.document_id),
        title=row.title,
        version=row.version,
        before_scheme=before_scheme,
        after_scheme=content_scheme(after_content),
        changed=encrypted is not None,
        content_sha256=row.content_sha256,
        hash_verified=True,
    )


async def _simulate_or_apply_envelope(
    current_content: str,
    *,
    plaintext: str,
    tenant_id: str,
    field: str,
    data_protection: DataProtectionService,
) -> str | None:
    if content_scheme(current_content) == ENVELOPE:
        return None
    encrypted = await data_protection.encrypt_text(
        plaintext,
        tenant_id=tenant_id,
        subject_id=None,
        field=field,
        tenant_scoped=True,
    )
    roundtrip = await data_protection.decrypt_text(encrypted)
    if roundtrip != plaintext:
        raise RuntimeError(f"{field} failed read-back after simulated rewrap")
    return encrypted


def content_scheme(content: str) -> str:
    return ENVELOPE if content.startswith(ENVELOPE_TEXT_PREFIX) else LEGACY_DIRECT


def _verify_version_hash(
    row: TenantKnowledgeDocumentVersionRow,
    plaintext: str,
) -> None:
    expected = canonical_sha256(
        {
            "tenant_id": row.tenant_id,
            "document_id": str(row.document_id),
            "version": row.version,
            "title": row.title,
            "content": plaintext,
            "document_type": row.document_type,
            "status": row.status,
            "uploaded_by": row.uploaded_by,
            "source_approval_id": row.source_approval_id,
            "metadata": dict(row.metadata_json),
        }
    )
    if row.content_sha256 != expected:
        raise RuntimeError(
            "knowledge version content_sha256 mismatch "
            f"document_id={row.document_id} version={row.version} "
            f"stored={row.content_sha256} expected={expected}"
        )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Report and verify what would change without persisting anything.",
    )
    mode.add_argument(
        "--execute",
        action="store_true",
        help="Persist the legacy-direct to envelope rewrap.",
    )
    parser.add_argument("--tenant-id", default=ANKER_TENANT_ID)
    parser.add_argument(
        "--title",
        dest="titles",
        action="append",
        help="Restrict to one title; may be provided multiple times.",
    )
    parser.add_argument(
        "--expect-documents",
        type=int,
        default=5,
        help="Fail unless this many current document rows are found. Use -1 to disable.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON only.")
    return parser.parse_args(argv)


async def _main_async(args: argparse.Namespace) -> int:
    settings = get_settings()
    engine_config = build_database_engine_config(
        settings.database_url,
        connect_timeout=settings.DB_CONNECT_TIMEOUT_SECONDS,
    )
    engine = create_async_engine(
        engine_config.async_url,
        connect_args=engine_config.connect_args,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    titles = tuple(args.titles or ANKER_DOCUMENT_TITLES)
    async with session_factory() as session:
        data_protection = DataProtectionService.from_settings(session, settings)
        if args.execute:
            async with session.begin():
                summary = await run_rewrap(
                    session,
                    data_protection=data_protection,
                    tenant_id=args.tenant_id,
                    titles=titles,
                    execute=True,
                )
        else:
            summary = await run_rewrap(
                session,
                data_protection=data_protection,
                tenant_id=args.tenant_id,
                titles=titles,
                execute=False,
            )
            await session.rollback()
    await engine.dispose()

    if args.expect_documents >= 0 and summary.scanned_documents != args.expect_documents:
        print(
            "FAIL rewrap expected "
            f"{args.expect_documents} documents, found {summary.scanned_documents}",
            file=sys.stderr,
        )
        print(json.dumps(summary.to_dict(), indent=2, sort_keys=True), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(summary.to_dict(), indent=2, sort_keys=True))
    else:
        action = "would_rewrap" if summary.dry_run else "rewrapped"
        print(
            "PASS rewrap "
            f"mode={'dry-run' if summary.dry_run else 'execute'} "
            f"tenant={summary.tenant_id} "
            f"documents={summary.scanned_documents} "
            f"versions={summary.scanned_versions} "
            f"{action}_documents={summary.changed_documents} "
            f"{action}_versions={summary.changed_versions} "
            f"hash_verified_versions={summary.hash_verified_versions}"
        )
        print(json.dumps(summary.to_dict(), indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
