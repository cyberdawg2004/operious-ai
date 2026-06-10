"""Re-encrypt tenant channel credentials into OPCRED2 envelopes.

Dry-run is the default. Use ``--apply`` to persist changes. The command never
prints plaintext credentials, DEKs, or wrapped DEKs.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import dispose_engine, get_owner_session_factory
from app.tenant.credentials import (
    TenantCredentialCodec,
    build_tenant_credential_encryptor_from_settings,
    is_opcred2,
)
from app.tenant.db.models import TenantChannelConfigurationRow
from app.tenant.enums import TenantChannelType


@dataclass(frozen=True, slots=True)
class TenantCredentialReencryptSummary:
    dry_run: bool
    rows_seen: int
    current_candidates: int
    previous_candidates: int
    current_migrated: int
    previous_migrated: int


async def reencrypt_tenant_credentials(
    session: AsyncSession,
    *,
    credential_codec: TenantCredentialCodec,
    apply: bool,
    tenant_id: str | None = None,
) -> TenantCredentialReencryptSummary:
    stmt = select(TenantChannelConfigurationRow).order_by(
        TenantChannelConfigurationRow.tenant_id,
        TenantChannelConfigurationRow.channel_type,
    )
    if tenant_id is not None:
        stmt = stmt.where(TenantChannelConfigurationRow.tenant_id == tenant_id)
    rows = tuple((await session.execute(stmt)).scalars())
    return reencrypt_tenant_credential_rows(
        rows,
        credential_codec=credential_codec,
        apply=apply,
    )


def reencrypt_tenant_credential_rows(
    rows: Sequence[TenantChannelConfigurationRow],
    *,
    credential_codec: TenantCredentialCodec,
    apply: bool,
) -> TenantCredentialReencryptSummary:
    """Re-encrypt already-loaded ORM rows without logging plaintext."""

    current_candidates = 0
    previous_candidates = 0
    current_migrated = 0
    previous_migrated = 0

    for row in rows:
        channel_type = TenantChannelType(row.channel_type)
        if not is_opcred2(bytes(row.credentials_enc)):
            current_candidates += 1
            if apply:
                row.credentials_enc = _reencrypt_blob(
                    credential_codec,
                    tenant_id=row.tenant_id,
                    channel_type=channel_type,
                    encrypted_credentials=bytes(row.credentials_enc),
                )
                current_migrated += 1
        previous = row.previous_credentials_enc
        if previous is not None and not is_opcred2(bytes(previous)):
            previous_candidates += 1
            if apply:
                row.previous_credentials_enc = _reencrypt_blob(
                    credential_codec,
                    tenant_id=row.tenant_id,
                    channel_type=channel_type,
                    encrypted_credentials=bytes(previous),
                )
                previous_migrated += 1

    return TenantCredentialReencryptSummary(
        dry_run=not apply,
        rows_seen=len(rows),
        current_candidates=current_candidates,
        previous_candidates=previous_candidates,
        current_migrated=current_migrated,
        previous_migrated=previous_migrated,
    )


def _reencrypt_blob(
    credential_codec: TenantCredentialCodec,
    *,
    tenant_id: str,
    channel_type: TenantChannelType,
    encrypted_credentials: bytes,
) -> bytes:
    credentials = credential_codec.decrypt(
        tenant_id=tenant_id,
        channel_type=channel_type,
        encrypted_credentials=encrypted_credentials,
    )
    return credential_codec.encrypt(
        tenant_id=tenant_id,
        channel_type=channel_type,
        credentials=credentials,
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tenant-id",
        default=None,
        help="Restrict migration to one tenant id.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist the re-encryption. Omit for dry-run.",
    )
    return parser.parse_args(argv)


async def _main_async(args: argparse.Namespace) -> int:
    settings = get_settings()
    credential_codec = build_tenant_credential_encryptor_from_settings(settings)
    tenant_id = (args.tenant_id or "").strip() or None
    session_factory = get_owner_session_factory()
    async with session_factory() as session:
        summary = await reencrypt_tenant_credentials(
            session,
            credential_codec=credential_codec,
            apply=bool(args.apply),
            tenant_id=tenant_id,
        )
        if args.apply:
            await session.commit()
        else:
            await session.rollback()
    print(
        "tenant credential re-encrypt "
        f"mode={'apply' if args.apply else 'dry-run'} "
        f"tenant={tenant_id or '*'} "
        f"rows_seen={summary.rows_seen} "
        f"current_candidates={summary.current_candidates} "
        f"previous_candidates={summary.previous_candidates} "
        f"current_migrated={summary.current_migrated} "
        f"previous_migrated={summary.previous_migrated}"
    )
    await dispose_engine()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_main_async(_parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
