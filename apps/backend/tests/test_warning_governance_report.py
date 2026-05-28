"""Focused tests for the warning governance reporter."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any


def _load_reporter() -> ModuleType:
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "warning_governance_report.py"
    )
    spec = importlib.util.spec_from_file_location(
        "warning_governance_report",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reporter = _load_reporter()


def test_risk_plane_classification_covers_governed_planes() -> None:
    assert (
        reporter.classify_risk_plane("apps/backend/app/db/session.py")
        == reporter.RISK_PLANE_AUTH_SECURITY
    )
    assert (
        reporter.classify_risk_plane("apps/backend/app/db/tenant_context.py")
        == reporter.RISK_PLANE_AUTH_SECURITY
    )
    assert (
        reporter.classify_risk_plane("apps/backend/app/db/rls_session.py")
        == reporter.RISK_PLANE_AUTH_SECURITY
    )
    assert (
        reporter.classify_risk_plane(
            "apps/backend/app/resolution/persistence/postgres.py"
        )
        == reporter.RISK_PLANE_CUSTOMER_RESOLUTION
    )
    assert (
        reporter.classify_risk_plane("apps/backend/app/resolution/refunds/runtime.py")
        == reporter.RISK_PLANE_FINANCIAL_ACTION
    )
    assert (
        reporter.classify_risk_plane("apps/backend/migrations/versions/001_init.py")
        == reporter.RISK_PLANE_MIGRATIONS
    )
    assert (
        reporter.classify_risk_plane("apps/backend/app/_deprecated/rag/runtime.py")
        == reporter.RISK_PLANE_PROTOTYPES
    )


def test_clean_file_coverage_math() -> None:
    assert reporter.compute_clean_file_coverage(total_files=10, warning_files=3) == 70.0
    assert reporter.compute_clean_file_coverage(total_files=0, warning_files=0) == 100.0


def test_warning_free_high_risk_plane_coverage_uses_classified_files() -> None:
    files = [
        "apps/backend/app/db/session.py",
        "apps/backend/app/boundary/adapters/channel_webhooks.py",
        "apps/backend/app/resolution/persistence/postgres.py",
        "apps/backend/app/db/url.py",
        "apps/backend/app/api/v1/router.py",
        "apps/backend/app/_deprecated/rag/runtime.py",
    ]
    coverage = reporter.compute_warning_free_high_risk_plane_percent(
        files=files,
        warning_files={
            "apps/backend/app/db/session.py",
            "apps/backend/app/db/url.py",
        },
    )

    assert coverage == {
        "total_files": 3,
        "warning_files": 1,
        "clean_files": 2,
        "percent": 66.67,
    }


def test_baseline_delta_math_uses_stable_warning_fingerprints() -> None:
    shared = _diagnostic("apps/backend/app/governance/runtime.py", 10)
    resolved = _diagnostic("apps/backend/app/execution/runtime.py", 20)
    introduced = _diagnostic("apps/backend/app/boundary/adapters/webhook.py", 30)
    introduced_again = _diagnostic("apps/backend/app/session/runtime.py", 40)

    delta = reporter.compute_baseline_delta(
        current_report={
            "summary": {"warning_count": 3, "error_count": 0},
            "diagnostics": [shared, introduced, introduced_again],
        },
        baseline_report={
            "summary": {"warning_count": 2, "error_count": 0},
            "diagnostics": [shared, resolved],
        },
        baseline_path=Path("/tmp/baseline.json"),
    )

    assert delta["warning_delta"] == 1
    assert delta["high_risk_warning_delta"] == 1
    assert delta["new_warning_count"] == 2
    assert delta["new_high_risk_warning_count"] == 2
    assert delta["resolved_warning_count"] == 1
    assert {item["fingerprint"] for item in delta["new_warnings"]} == {
        introduced["fingerprint"],
        introduced_again["fingerprint"],
    }
    assert {item["fingerprint"] for item in delta["new_high_risk_warnings"]} == {
        introduced["fingerprint"],
        introduced_again["fingerprint"],
    }
    assert delta["resolved_warnings"][0]["fingerprint"] == resolved["fingerprint"]


def test_regression_gate_catches_enterprise_governance_cases() -> None:
    low_risk = _diagnostic("apps/backend/app/db/url.py", 10)
    high_risk = _diagnostic("apps/backend/app/governance/runtime.py", 20)

    high_risk_delta = reporter.compute_baseline_delta(
        current_report={
            "summary": {"warning_count": 1, "error_count": 0},
            "diagnostics": [high_risk],
        },
        baseline_report={
            "summary": {"warning_count": 1, "error_count": 0},
            "diagnostics": [low_risk],
        },
        baseline_path=Path("/tmp/baseline.json"),
    )

    assert high_risk_delta["warning_delta"] == 0
    assert high_risk_delta["high_risk_warning_delta"] == 1
    assert high_risk_delta["new_high_risk_warning_count"] == 1
    assert "high_risk_warning_count_increased" in high_risk_delta[
        "regression_reasons"
    ]
    assert "new_high_risk_warnings" in high_risk_delta["regression_reasons"]
    assert reporter._warning_regressed({"baseline_delta": high_risk_delta})

    replaced_high_risk = _diagnostic("apps/backend/app/execution/runtime.py", 30)
    flat_high_risk_delta = reporter.compute_baseline_delta(
        current_report={
            "summary": {"warning_count": 1, "error_count": 0},
            "diagnostics": [high_risk],
        },
        baseline_report={
            "summary": {"warning_count": 1, "error_count": 0},
            "diagnostics": [replaced_high_risk],
        },
        baseline_path=Path("/tmp/baseline.json"),
    )

    assert flat_high_risk_delta["warning_delta"] == 0
    assert flat_high_risk_delta["high_risk_warning_delta"] == 0
    assert flat_high_risk_delta["new_high_risk_warning_count"] == 1
    assert flat_high_risk_delta["regression_reasons"] == ["new_high_risk_warnings"]
    assert reporter._warning_regressed({"baseline_delta": flat_high_risk_delta})

    error_delta = reporter.compute_baseline_delta(
        current_report={
            "summary": {"warning_count": 0, "error_count": 1},
            "diagnostics": [],
        },
        baseline_report={
            "summary": {"warning_count": 0, "error_count": 0},
            "diagnostics": [],
        },
        baseline_path=Path("/tmp/baseline.json"),
    )

    assert error_delta["regression_reasons"] == ["error_count_increased"]
    assert reporter._warning_regressed({"baseline_delta": error_delta})


def test_any_unknown_propagation_counters() -> None:
    indicators = reporter.count_any_unknown_indicators(
        [
            {
                "file": "apps/backend/app/governance/runtime.py",
                "rule": "reportUnknownVariableType",
                "message": (
                    'Type of "metadata" is partially Unknown\n'
                    '  Type of "metadata" is "dict[Unknown, Unknown]"'
                ),
            },
            {
                "file": "apps/backend/app/api/v1/schemas/session.py",
                "rule": "reportUnknownVariableType",
                "message": 'Type of "items" is "list[Unknown]"',
            },
            {
                "file": "apps/backend/app/workers/celery_app.py",
                "rule": "reportUnknownMemberType",
                "message": 'Type of "update" is Unknown | Any',
            },
            {
                "file": "apps/backend/app/tenant/chronology.py",
                "rule": "reportUnknownArgumentType",
                "message": "Argument type is Unknown",
            },
            {
                "file": "apps/backend/app/workers/agent_tasks.py",
                "rule": "reportUntypedFunctionDecorator",
                "message": "Untyped function decorator obscures type of function",
            },
        ]
    )

    assert indicators["diagnostics_mentioning_unknown"] == 4
    assert indicators["diagnostics_mentioning_any"] == 1
    assert indicators["dict_unknown_unknown"] == 1
    assert indicators["list_unknown"] == 1
    assert indicators["unknown_member_type"] == 1
    assert indicators["unknown_argument_type"] == 1


def _diagnostic(file_path: str, line: int) -> dict[str, Any]:
    diagnostic: dict[str, Any] = {
        "file": file_path,
        "severity": "warning",
        "rule": "reportUnknownVariableType",
        "message": 'Type of "payload" is "dict[Unknown, Unknown]"',
        "line": line,
        "character": 1,
        "risk_plane": reporter.classify_risk_plane(file_path),
    }
    diagnostic["fingerprint"] = reporter.warning_fingerprint(diagnostic)
    return diagnostic
