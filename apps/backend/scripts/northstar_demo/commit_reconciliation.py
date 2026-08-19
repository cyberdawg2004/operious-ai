"""One-shot, read-only reconciliation for an ambiguous Northstar commit."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from .manifest import MANIFEST, NorthstarDemoManifest
from .seed import (
    NorthstarCommitOutcomeUnknown,
    NorthstarDemoSeedService,
    NorthstarSeedVerification,
)
from .verifier import (
    NorthstarVerificationClassification,
    NorthstarVerificationResult,
    verify_northstar_fixture_read_only,
)

SessionFactory = Callable[[], AsyncSession]
SeedOperation = Callable[[AsyncSession], Awaitable[NorthstarSeedVerification]]
ReadOnlyVerifier = Callable[
    [AsyncSession, NorthstarDemoManifest], Awaitable[NorthstarVerificationResult]
]


class NorthstarCommitReconciliationOutcome(StrEnum):
    """Sanitized outcomes after exactly one fresh read-only verification."""

    VERIFIED_NOT_COMMITTED = "VERIFIED_NOT_COMMITTED"
    VERIFIED_COMMITTED_COMPLETE = "VERIFIED_COMMITTED_COMPLETE"
    VERIFIED_UNSAFE_STATE = "VERIFIED_UNSAFE_STATE"
    OUTCOME_UNVERIFIABLE = "OUTCOME_UNVERIFIABLE"


@dataclass(frozen=True, slots=True)
class NorthstarCommitReconciliationResult:
    """Contains only the fixed fixture identifier and a stable outcome enum."""

    outcome: NorthstarCommitReconciliationOutcome
    tenant_id: str


class NorthstarSeedCommitCoordinator:
    """Run the seed once; reconcile only an explicitly ambiguous commit outcome."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        manifest: NorthstarDemoManifest = MANIFEST,
        seed_operation: SeedOperation | None = None,
        read_only_verifier: ReadOnlyVerifier | None = None,
        verification_timeout_seconds: float = 5.0,
    ) -> None:
        if verification_timeout_seconds <= 0:
            raise ValueError("verification timeout must be positive")
        self._session_factory = session_factory
        self._manifest = manifest
        self._seed_operation = seed_operation or self._default_seed_operation
        self._read_only_verifier = read_only_verifier or self._default_read_only_verifier
        self._verification_timeout_seconds = verification_timeout_seconds

    async def seed_once(
        self,
    ) -> NorthstarSeedVerification | NorthstarCommitReconciliationResult:
        """Never retry a seed after any error, including commit ambiguity."""

        failed_session = self._session_factory()
        try:
            return await self._seed_operation(failed_session)
        except NorthstarCommitOutcomeUnknown:
            # The session which attempted commit is permanently discarded.  It
            # is never rolled back, reused, or passed to the verifier.
            pass
        finally:
            await failed_session.close()
        return await self._reconcile_once()

    async def _reconcile_once(self) -> NorthstarCommitReconciliationResult:
        """Classify one fresh read-only observation without repair or retry."""

        fresh_session = self._session_factory()
        try:
            async with asyncio.timeout(self._verification_timeout_seconds):
                result = await self._read_only_verifier(fresh_session, self._manifest)
        except Exception:  # noqa: BLE001 - ambiguity must fail closed
            return self._result(
                NorthstarCommitReconciliationOutcome.OUTCOME_UNVERIFIABLE
            )
        finally:
            await fresh_session.close()

        if result.classification is NorthstarVerificationClassification.ABSENT:
            return self._result(
                NorthstarCommitReconciliationOutcome.VERIFIED_NOT_COMMITTED
            )
        if result.classification is NorthstarVerificationClassification.COMPLETE_MATCH:
            return self._result(
                NorthstarCommitReconciliationOutcome.VERIFIED_COMMITTED_COMPLETE
            )
        return self._result(NorthstarCommitReconciliationOutcome.VERIFIED_UNSAFE_STATE)

    def _result(
        self, outcome: NorthstarCommitReconciliationOutcome
    ) -> NorthstarCommitReconciliationResult:
        return NorthstarCommitReconciliationResult(
            outcome=outcome,
            tenant_id=self._manifest.tenant_id,
        )

    async def _default_seed_operation(
        self, session: AsyncSession
    ) -> NorthstarSeedVerification:
        # This is the only production execution path.  Read-only CLI modes
        # use the verifier directly and direct service tests retain control of
        # their transaction setup.
        return await NorthstarDemoSeedService(
            session,
            manifest=self._manifest,
            serialize_execution=True,
        ).seed()

    async def _default_read_only_verifier(
        self,
        session: AsyncSession,
        manifest: NorthstarDemoManifest,
    ) -> NorthstarVerificationResult:
        return await verify_northstar_fixture_read_only(session, manifest=manifest)


__all__ = [
    "NorthstarCommitReconciliationOutcome",
    "NorthstarCommitReconciliationResult",
    "NorthstarSeedCommitCoordinator",
]
