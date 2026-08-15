"""CLI-only failure and output-sanitization proofs for Northstar seeding."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import scripts.northstar_demo.__main__ as cli
from scripts.northstar_demo.commit_reconciliation import (
    NorthstarCommitReconciliationOutcome,
    NorthstarCommitReconciliationResult,
)
from scripts.northstar_demo.manifest import TENANT_ID
from scripts.northstar_demo.seed import (
    NorthstarConcurrentExecutionBusy,
    NorthstarDemoSeedService,
    NorthstarPreDurableCommitRejected,
    NorthstarSeedVerification,
)
from scripts.northstar_demo.verifier import (
    NorthstarVerificationClassification,
    NorthstarVerificationResult,
)


class _NoSessionFactory:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> AsyncSession:
        self.calls += 1
        raise AssertionError("a pre-session rejection opened a session")


class _ReadOnlySession:
    async def __aenter__(self) -> "_ReadOnlySession":
        return self

    async def __aexit__(
        self, _type: object, _value: object, _traceback: object
    ) -> None:
        return None


@pytest.mark.parametrize(
    "argv",
    (
        (),
        ("--dry-run", "--verify"),
        ("--unsupported-argument", "sentinel-password"),
        ("--tenant-id", "unrelated-tenant", "--dry-run"),
    ),
)
def test_parser_rejections_are_sanitized_before_session_factory(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: tuple[str, ...],
) -> None:
    factory = _NoSessionFactory()
    monkeypatch.setattr(cli, "get_session_factory", lambda: factory)

    assert cli.main(argv) == 2
    captured = capsys.readouterr()
    assert "sentinel-password" not in captured.out + captured.err
    assert "unrelated-tenant" not in captured.out + captured.err
    assert factory.calls == 0


@pytest.mark.parametrize(
    "argv, environment",
    (
        (("--execute",), {}),
        (("--execute", "--confirm-tenant-id", TENANT_ID), {}),
        (
            (
                "--execute",
                "--confirm-tenant-id",
                TENANT_ID,
                "--production-interlock",
                "wrong-interlock",
            ),
            {cli.PRODUCTION_INTERLOCK: "true"},
        ),
        (
            (
                "--execute",
                "--confirm-tenant-id",
                "unrelated-tenant",
                "--production-interlock",
                cli.PRODUCTION_INTERLOCK,
            ),
            {cli.PRODUCTION_INTERLOCK: "true"},
        ),
        (
            ("--dry-run",),
            {"NORTHSTAR_DEMO_FAILURE_INJECTOR": "final_flush"},
        ),
        (
            ("--dry-run",),
            {"NORTHSTAR_DEMO_PRE_DURABLE_COMMIT_REJECTION": "true"},
        ),
    ),
)
def test_interlock_and_test_seam_rejections_precede_session_creation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: tuple[str, ...],
    environment: dict[str, str],
) -> None:
    factory = _NoSessionFactory()
    monkeypatch.setattr(cli, "get_session_factory", lambda: factory)
    monkeypatch.delenv(cli.PRODUCTION_INTERLOCK, raising=False)
    monkeypatch.delenv("NORTHSTAR_DEMO_FAILURE_INJECTOR", raising=False)
    monkeypatch.delenv("NORTHSTAR_DEMO_PRE_DURABLE_COMMIT_REJECTION", raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    assert cli.main(argv) == 2
    assert factory.calls == 0
    assert "northstar_demo_error=" in capsys.readouterr().out


class _CoordinatorDouble:
    def __init__(self, result: object) -> None:
        self._result = result
        self.calls = 0

    async def seed_once(self) -> object:
        self.calls += 1
        if isinstance(self._result, BaseException):
            raise self._result
        return self._result


def _execute_argv() -> tuple[str, ...]:
    return (
        "--execute",
        "--confirm-tenant-id",
        TENANT_ID,
        "--production-interlock",
        cli.PRODUCTION_INTERLOCK,
    )


@pytest.mark.parametrize(
    "result, expected_exit, required_text",
    (
        (
            NorthstarPreDurableCommitRejected(),
            2,
            "northstar_demo_error=PRECOMMIT_FAILURE",
        ),
        (
            NorthstarConcurrentExecutionBusy(),
            2,
            "northstar_demo_error=CONCURRENT_EXECUTION_BUSY",
        ),
        (
            NorthstarCommitReconciliationResult(
                NorthstarCommitReconciliationOutcome.VERIFIED_NOT_COMMITTED,
                TENANT_ID,
            ),
            2,
            "durable_fixture=absent",
        ),
        (
            NorthstarCommitReconciliationResult(
                NorthstarCommitReconciliationOutcome.VERIFIED_COMMITTED_COMPLETE,
                TENANT_ID,
            ),
            0,
            "northstar_demo_seed=complete_verified_after_commit_uncertainty",
        ),
        (
            NorthstarCommitReconciliationResult(
                NorthstarCommitReconciliationOutcome.VERIFIED_UNSAFE_STATE,
                TENANT_ID,
            ),
            2,
            "manual_review_required=true",
        ),
        (
            NorthstarCommitReconciliationResult(
                NorthstarCommitReconciliationOutcome.OUTCOME_UNVERIFIABLE,
                TENANT_ID,
            ),
            2,
            "manual_review_required=true",
        ),
    ),
)
def test_execute_outcome_exit_codes_are_fixed_and_never_retry(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    result: object,
    expected_exit: int,
    required_text: str,
) -> None:
    session_factory = _NoSessionFactory()
    coordinator = _CoordinatorDouble(result)

    def coordinator_factory(_factory: object) -> _CoordinatorDouble:
        return coordinator

    monkeypatch.setenv(cli.PRODUCTION_INTERLOCK, "true")
    monkeypatch.setattr(cli, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(cli, "NorthstarSeedCommitCoordinator", coordinator_factory)

    assert cli.main(_execute_argv()) == expected_exit
    output = capsys.readouterr().out
    assert required_text in output
    assert coordinator.calls == 1
    assert session_factory.calls == 0


def test_cli_never_leaks_exception_or_log_sentinels(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    sentinels = (
        "postgresql://user:password@database.example/operious",
        "token=secret-token-value",
        "SELECT * FROM private_customer_data",
        "parameters={'secret': 'value'}",
        "stored-payload:customer-record",
        "unrelated-tenant-id",
        "traceback-local-secret",
    )
    coordinator = _CoordinatorDouble(RuntimeError(" | ".join(sentinels)))

    def coordinator_factory(_factory: object) -> _CoordinatorDouble:
        return coordinator

    monkeypatch.setenv(cli.PRODUCTION_INTERLOCK, "true")
    monkeypatch.setattr(cli, "get_session_factory", lambda: _NoSessionFactory())
    monkeypatch.setattr(cli, "NorthstarSeedCommitCoordinator", coordinator_factory)
    caplog.set_level(logging.DEBUG)

    assert cli.main(_execute_argv()) == 2
    captured = capsys.readouterr()
    emitted = captured.out + captured.err + caplog.text
    assert "northstar_demo_error=unexpected_failure" in emitted
    assert all(sentinel not in emitted for sentinel in sentinels)


@pytest.mark.parametrize(
    "argv, classification, expected_exit, label",
    (
        (
            ("--dry-run",),
            NorthstarVerificationClassification.ABSENT,
            0,
            "northstar_demo_dry_run=ABSENT",
        ),
        (
            ("--verify",),
            NorthstarVerificationClassification.COMPLETE_MATCH,
            0,
            "northstar_demo_verify=COMPLETE_MATCH",
        ),
    ),
)
def test_read_only_modes_preserve_their_verified_behavior(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: tuple[str, ...],
    classification: NorthstarVerificationClassification,
    expected_exit: int,
    label: str,
) -> None:
    session_calls = 0

    def session_factory() -> _ReadOnlySession:
        nonlocal session_calls
        session_calls += 1
        return _ReadOnlySession()

    async def verifier(
        _session: AsyncSession, manifest: object
    ) -> NorthstarVerificationResult:
        del manifest
        return NorthstarVerificationResult(classification, (), (), ())

    monkeypatch.delenv("NORTHSTAR_DEMO_FAILURE_INJECTOR", raising=False)
    monkeypatch.delenv("NORTHSTAR_DEMO_PRE_DURABLE_COMMIT_REJECTION", raising=False)
    monkeypatch.setattr(cli, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(cli, "verify_northstar_fixture_read_only", verifier)
    assert cli.main(argv) == expected_exit
    assert label in capsys.readouterr().out
    assert session_calls == 1


def test_test_seams_have_no_cli_or_environment_activation_path() -> None:
    parser = cli.build_parser()
    options = {
        action.option_strings[0]
        for action in parser._actions
        if action.option_strings
    }
    assert "--failure-injector" not in options
    assert "--pre-durable-commit-hook" not in options
    source = Path(cli.__file__).read_text()
    assert "failure_injector=" not in source
    assert "pre_durable_commit_hook=" not in source


@pytest.mark.asyncio
async def test_production_coordinator_default_constructs_seed_without_test_seams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.northstar_demo.commit_reconciliation as reconciliation

    captured: dict[str, object] = {}

    class _SeedServiceDouble:
        def __init__(self, session: AsyncSession, **kwargs: object) -> None:
            captured["session"] = session
            captured.update(kwargs)

        async def seed(self) -> NorthstarSeedVerification:
            return NorthstarSeedVerification("absent", TENANT_ID, "fixed-session")

    monkeypatch.setattr(reconciliation, "NorthstarDemoSeedService", _SeedServiceDouble)
    session = _ReadOnlySession()
    coordinator = reconciliation.NorthstarSeedCommitCoordinator(
        lambda: session  # type: ignore[return-value]
    )
    result = await coordinator._default_seed_operation(session)  # type: ignore[arg-type]
    assert result.state == "absent"
    assert captured == {
        "session": session,
        "manifest": reconciliation.MANIFEST,
        "serialize_execution": True,
    }
    assert NorthstarDemoSeedService is not _SeedServiceDouble
