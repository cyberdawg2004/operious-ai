"""Safe operator interface for the Northstar synthetic demo fixture."""

from __future__ import annotations

import argparse
import asyncio
import os
from collections.abc import Sequence
from typing import NoReturn

from app.db.session import get_session_factory

from .commit_reconciliation import (
    NorthstarCommitReconciliationOutcome,
    NorthstarCommitReconciliationResult,
    NorthstarSeedCommitCoordinator,
)
from .manifest import MANIFEST, TENANT_ID
from .seed import (
    NorthstarConcurrentExecutionBusy,
    NorthstarPreDurableCommitRejected,
    NorthstarSeedSafetyError,
)
from .verifier import (
    NorthstarVerificationClassification,
    verify_northstar_fixture_read_only,
)

PRODUCTION_INTERLOCK = "NORTHSTAR_DEMO_PRODUCTION_EXECUTION_AUTHORIZED"
_TEST_SEAM_ENVIRONMENT_VARIABLES = frozenset(
    {
        "NORTHSTAR_DEMO_FAILURE_INJECTOR",
        "NORTHSTAR_DEMO_PRE_DURABLE_COMMIT_REJECTION",
    }
)


class _NorthstarArgumentParser(argparse.ArgumentParser):
    """Keep parser failures independent of user-provided argument values."""

    def error(self, message: str) -> NoReturn:
        del message
        self.print_usage()
        self.exit(2, "northstar_demo_error=invalid_arguments\n")
        raise AssertionError("argparse exit returned unexpectedly")


def build_parser() -> argparse.ArgumentParser:
    parser = _NorthstarArgumentParser(description="Northstar synthetic demo seed")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="inspect only")
    mode.add_argument("--verify", action="store_true", help="inspect exact fixture state")
    mode.add_argument("--execute", action="store_true", help="write the immutable fixture")
    parser.add_argument("--tenant-id", default=TENANT_ID, choices=(TENANT_ID,))
    parser.add_argument("--confirm-tenant-id")
    parser.add_argument("--production-interlock")
    return parser


async def _run(args: argparse.Namespace) -> int:
    if any(os.environ.get(name) for name in _TEST_SEAM_ENVIRONMENT_VARIABLES):
        raise NorthstarSeedSafetyError("test seam environment configuration is rejected")
    if args.execute:
        if args.confirm_tenant_id != TENANT_ID:
            raise NorthstarSeedSafetyError("exact tenant confirmation is required")
        if args.production_interlock != PRODUCTION_INTERLOCK:
            raise NorthstarSeedSafetyError("production execution interlock is required")
        # A second independently supplied, non-secret process guard makes an
        # accidental copy/paste execution impossible.
        if os.environ.get(PRODUCTION_INTERLOCK) != "true":
            raise NorthstarSeedSafetyError("production execution environment guard is absent")
    session_factory = get_session_factory()
    if args.execute:
        result = await NorthstarSeedCommitCoordinator(session_factory).seed_once()
        if isinstance(result, NorthstarCommitReconciliationResult):
            return _print_reconciliation_outcome(result)
        print(f"northstar_demo_seed=complete tenant_id={result.tenant_id}")
        return 0
    async with session_factory() as session:
        result = await verify_northstar_fixture_read_only(session, manifest=MANIFEST)
        mode = "verify" if args.verify else "dry_run"
        reasons = ",".join(result.reason_codes) if result.reason_codes else "none"
        print(f"northstar_demo_{mode}={result.classification} reasons={reasons}")
        if result.classification is NorthstarVerificationClassification.COMPLETE_MATCH:
            return 0
        if not args.verify and result.classification is NorthstarVerificationClassification.ABSENT:
            return 0
        return 2


def _print_reconciliation_outcome(
    result: NorthstarCommitReconciliationResult,
) -> int:
    if result.outcome is NorthstarCommitReconciliationOutcome.VERIFIED_COMMITTED_COMPLETE:
        print(
            "northstar_demo_seed=complete_verified_after_commit_uncertainty "
            f"tenant_id={result.tenant_id}"
        )
        return 0
    if result.outcome is NorthstarCommitReconciliationOutcome.VERIFIED_NOT_COMMITTED:
        print(
            "northstar_demo_commit_outcome=VERIFIED_NOT_COMMITTED "
            f"durable_fixture=absent tenant_id={result.tenant_id}"
        )
        return 2
    print(
        f"northstar_demo_commit_outcome={result.outcome} "
        "manual_review_required=true "
        f"tenant_id={result.tenant_id}"
    )
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return asyncio.run(_run(args))
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    except NorthstarPreDurableCommitRejected:
        print("northstar_demo_error=PRECOMMIT_FAILURE")
        return 2
    except NorthstarConcurrentExecutionBusy:
        print("northstar_demo_error=CONCURRENT_EXECUTION_BUSY")
        return 2
    except NorthstarSeedSafetyError:
        print("northstar_demo_error=precondition_rejected")
        return 2
    except Exception:  # noqa: BLE001 - command output must stay sanitized
        print("northstar_demo_error=unexpected_failure")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
