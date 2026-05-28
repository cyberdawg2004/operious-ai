"""Build a deterministic warning governance report from Pyright JSON output."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
APP_ROOT = Path("apps/backend/app")
MIGRATIONS_ROOT = Path("apps/backend/migrations")
PYRIGHT_COMMAND = ("venv/bin/pyright", "apps/backend/app", "--outputjson")

RISK_PLANE_PROTOTYPES = "Prototypes"
RISK_PLANE_MIGRATIONS = "Migrations"
RISK_PLANE_AUTH_SECURITY = "Auth/security"
RISK_PLANE_QUEUES = "Queues/core pressure controls"
RISK_PLANE_APIS = "APIs"
RISK_PLANE_ADAPTERS = "Adapters"
RISK_PLANE_POLICY = "Policy evaluator"
RISK_PLANE_GOVERNANCE = "Governance engine"
RISK_PLANE_EXECUTION = "Execution plane"
RISK_PLANE_MEMORY = "Memory consistency layer"
RISK_PLANE_ORCHESTRATION = "Orchestration kernel"
RISK_PLANE_CUSTOMER_RESOLUTION = "Customer resolution/orchestration"
RISK_PLANE_FINANCIAL_ACTION = "Financial/action systems"
RISK_PLANE_OBSERVABILITY = "Observability/hardening"
RISK_PLANE_INTEGRATION = "Integration services"
RISK_PLANE_OTHER = "Other"

HIGH_RISK_PLANES = frozenset(
    {
        RISK_PLANE_ADAPTERS,
        RISK_PLANE_AUTH_SECURITY,
        RISK_PLANE_CUSTOMER_RESOLUTION,
        RISK_PLANE_EXECUTION,
        RISK_PLANE_FINANCIAL_ACTION,
        RISK_PLANE_GOVERNANCE,
        RISK_PLANE_MEMORY,
        RISK_PLANE_POLICY,
        RISK_PLANE_QUEUES,
    }
)

FINANCIAL_ACTION_KEYWORDS = frozenset(
    {
        "cancellation",
        "cancellations",
        "claim",
        "claims",
        "credit",
        "credits",
        "external_mutation",
        "refund",
        "refunds",
        "replacement",
        "replacements",
        "return",
        "returns",
        "warehouse",
        "warranty",
    }
)

AUTH_SECURITY_DB_FILES = frozenset(
    {
        "apps/backend/app/db/session.py",
        "apps/backend/app/db/tenant_context.py",
    }
)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = _repo_root()

    pyright_payload = _run_pyright(repo_root)
    report = build_report(
        pyright_payload=pyright_payload,
        repo_root=repo_root,
        baseline_path=args.baseline_json,
    )

    if args.json_output is not None:
        _write_json(args.json_output, report)
    if args.markdown_output is not None:
        _write_text(args.markdown_output, render_markdown(report))
    if args.json_output is None and args.markdown_output is None:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")

    if args.fail_on_regression and _warning_regressed(report):
        return 1
    return 0


def build_report(
    *,
    pyright_payload: Mapping[str, Any],
    repo_root: Path,
    baseline_path: Path | None = None,
) -> dict[str, Any]:
    diagnostics = [
        normalize_diagnostic(raw, repo_root=repo_root)
        for raw in pyright_payload.get("generalDiagnostics", [])
        if isinstance(raw, Mapping)
    ]
    warning_diagnostics = [
        diagnostic
        for diagnostic in diagnostics
        if diagnostic["severity"] == "warning"
    ]

    app_files = _python_files(repo_root / APP_ROOT, repo_root=repo_root)
    analyzed_count = _int_from_mapping(
        pyright_payload.get("summary", {}),
        "filesAnalyzed",
        default=len(app_files),
    )
    files_with_warnings = {diagnostic["file"] for diagnostic in warning_diagnostics}
    clean_file_coverage = compute_clean_file_coverage(
        total_files=len(app_files),
        warning_files=len(files_with_warnings),
    )
    high_risk_coverage = compute_warning_free_high_risk_plane_percent(
        files=app_files,
        warning_files=files_with_warnings,
    )

    by_file_counter = Counter(diagnostic["file"] for diagnostic in warning_diagnostics)
    by_module_counter = Counter(
        _module_for_path(diagnostic["file"]) for diagnostic in warning_diagnostics
    )
    by_risk_plane_counter = Counter(
        diagnostic["risk_plane"] for diagnostic in warning_diagnostics
    )
    by_rule_counter = Counter(diagnostic["rule"] for diagnostic in warning_diagnostics)

    summary_payload = pyright_payload.get("summary", {})
    summary = {
        "files_total": len(app_files),
        "files_analyzed": analyzed_count,
        "error_count": _int_from_mapping(summary_payload, "errorCount"),
        "warning_count": _int_from_mapping(summary_payload, "warningCount"),
        "information_count": _int_from_mapping(summary_payload, "informationCount"),
        "diagnostic_count": len(diagnostics),
        "files_with_warnings": len(files_with_warnings),
        "clean_files": max(len(app_files) - len(files_with_warnings), 0),
        "clean_file_coverage_percent": clean_file_coverage,
        "high_risk_files_total": high_risk_coverage["total_files"],
        "high_risk_files_with_warnings": high_risk_coverage["warning_files"],
        "warning_free_high_risk_files": high_risk_coverage["clean_files"],
        "warning_free_high_risk_plane_percent": high_risk_coverage["percent"],
    }

    baseline_delta = None
    if baseline_path is not None:
        baseline_delta = compute_baseline_delta(
            current_report={
                "summary": summary,
                "diagnostics": diagnostics,
            },
            baseline_report=_load_baseline_report(baseline_path, repo_root=repo_root),
            baseline_path=baseline_path,
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "command": list(PYRIGHT_COMMAND),
        "pyright": {
            "version": str(pyright_payload.get("version", "")),
        },
        "paths": {
            "repo_root": str(repo_root),
            "app_root": APP_ROOT.as_posix(),
            "migrations_root": MIGRATIONS_ROOT.as_posix(),
            "pyright_config": "pyrightconfig.json",
        },
        "summary": summary,
        "high_risk_planes": sorted(HIGH_RISK_PLANES),
        "by_rule": _counter_rows(by_rule_counter, key_name="rule"),
        "by_module": _counter_rows(by_module_counter, key_name="module"),
        "by_risk_plane": _counter_rows(
            by_risk_plane_counter,
            key_name="risk_plane",
        ),
        "by_file": _counter_rows(by_file_counter, key_name="file"),
        "top_files": _counter_rows(by_file_counter, key_name="file")[:10],
        "any_unknown_indicators": count_any_unknown_indicators(warning_diagnostics),
        "warnings_per_kloc": warnings_per_kloc(
            app_files=app_files,
            warning_diagnostics=warning_diagnostics,
            repo_root=repo_root,
        ),
        "baseline_delta": baseline_delta,
        "diagnostics": diagnostics,
    }


def normalize_diagnostic(
    diagnostic: Mapping[str, Any],
    *,
    repo_root: Path,
) -> dict[str, Any]:
    file_path = _relative_path(str(diagnostic.get("file", "")), repo_root=repo_root)
    start = _range_position(diagnostic, "start")
    end = _range_position(diagnostic, "end")
    message = str(diagnostic.get("message", ""))
    severity = str(diagnostic.get("severity", "unknown"))
    rule = str(diagnostic.get("rule") or "unknown")
    line = start["line"]
    character = start["character"]

    normalized = {
        "file": file_path,
        "severity": severity,
        "rule": rule,
        "message": message,
        "line": line,
        "character": character,
        "end_line": end["line"],
        "end_character": end["character"],
        "module": _module_for_path(file_path),
        "risk_plane": classify_risk_plane(file_path),
    }
    normalized["fingerprint"] = warning_fingerprint(normalized)
    return normalized


def warning_fingerprint(diagnostic: Mapping[str, Any]) -> str:
    material = "\x1f".join(
        (
            str(diagnostic.get("file", "")),
            str(diagnostic.get("severity", "")),
            str(diagnostic.get("rule", "")),
            str(diagnostic.get("line", "")),
            str(diagnostic.get("character", "")),
            _normalize_message(str(diagnostic.get("message", ""))),
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def classify_risk_plane(path: str | Path) -> str:
    normalized = _normalize_rel_path(path)
    parts = tuple(part for part in normalized.split("/") if part)
    lowered_parts = frozenset(part.lower() for part in parts)

    if "_deprecated" in lowered_parts or lowered_parts.intersection(
        {"demo", "demos", "playground", "playgrounds", "prototype", "prototypes"}
    ):
        return RISK_PLANE_PROTOTYPES
    if normalized.startswith(f"{MIGRATIONS_ROOT.as_posix()}/"):
        return RISK_PLANE_MIGRATIONS
    if _is_financial_action_path(parts):
        return RISK_PLANE_FINANCIAL_ACTION
    if _is_queue_or_core_path(normalized, parts):
        return RISK_PLANE_QUEUES
    if _is_auth_security_path(normalized, parts):
        return RISK_PLANE_AUTH_SECURITY
    if normalized.startswith("apps/backend/app/api/"):
        return RISK_PLANE_APIS
    if normalized.startswith("apps/backend/app/boundary/"):
        return RISK_PLANE_ADAPTERS
    if _is_policy_path(parts):
        return RISK_PLANE_POLICY
    if normalized.startswith("apps/backend/app/governance/"):
        return RISK_PLANE_GOVERNANCE
    if normalized.startswith("apps/backend/app/execution/") or normalized.startswith(
        "apps/backend/app/workers/"
    ):
        return RISK_PLANE_EXECUTION
    if _starts_with_any(
        normalized,
        (
            "apps/backend/app/cognition/",
            "apps/backend/app/events/",
            "apps/backend/app/knowledge/",
            "apps/backend/app/organizational_intelligence/",
            "apps/backend/app/session/",
            "apps/backend/app/sop_intelligence/",
        ),
    ):
        return RISK_PLANE_MEMORY
    if _starts_with_any(
        normalized,
        (
            "apps/backend/app/agents/",
            "apps/backend/app/arbitration/",
            "apps/backend/app/coordination/",
            "apps/backend/app/qa/",
            "apps/backend/app/runtime/",
            "apps/backend/app/services/",
            "apps/backend/app/supervisor/",
        ),
    ):
        return RISK_PLANE_ORCHESTRATION
    if normalized.startswith("apps/backend/app/resolution/"):
        return RISK_PLANE_CUSTOMER_RESOLUTION
    if _starts_with_any(
        normalized,
        (
            "apps/backend/app/hardening/",
            "apps/backend/app/observability/",
            "apps/backend/app/survivability/",
        ),
    ):
        return RISK_PLANE_OBSERVABILITY
    if normalized.startswith("apps/backend/app/dependencies/"):
        return RISK_PLANE_INTEGRATION
    return RISK_PLANE_OTHER


def compute_clean_file_coverage(*, total_files: int, warning_files: int) -> float:
    if total_files <= 0:
        return 100.0
    clean_files = max(total_files - warning_files, 0)
    return _percent(clean_files, total_files)


def compute_warning_free_high_risk_plane_percent(
    *,
    files: Iterable[str],
    warning_files: set[str],
) -> dict[str, Any]:
    high_risk_files = [
        file_path
        for file_path in files
        if classify_risk_plane(file_path) in HIGH_RISK_PLANES
    ]
    high_risk_file_set = set(high_risk_files)
    high_risk_warning_files = {
        file_path for file_path in warning_files if file_path in high_risk_file_set
    }
    clean_files = len(high_risk_files) - len(high_risk_warning_files)
    return {
        "total_files": len(high_risk_files),
        "warning_files": len(high_risk_warning_files),
        "clean_files": clean_files,
        "percent": _percent(clean_files, len(high_risk_files)),
    }


def compute_baseline_delta(
    *,
    current_report: Mapping[str, Any],
    baseline_report: Mapping[str, Any],
    baseline_path: Path,
) -> dict[str, Any]:
    current_warnings = _warning_diagnostics_from_report(current_report)
    baseline_warnings = _warning_diagnostics_from_report(baseline_report)
    current_by_fingerprint = {
        str(diagnostic["fingerprint"]): diagnostic
        for diagnostic in current_warnings
        if "fingerprint" in diagnostic
    }
    baseline_by_fingerprint = {
        str(diagnostic["fingerprint"]): diagnostic
        for diagnostic in baseline_warnings
        if "fingerprint" in diagnostic
    }
    current_fingerprints = set(current_by_fingerprint)
    baseline_fingerprints = set(baseline_by_fingerprint)
    new_fingerprints = current_fingerprints - baseline_fingerprints
    resolved_fingerprints = baseline_fingerprints - current_fingerprints

    current_warning_count = _summary_count(current_report, "warning_count")
    baseline_warning_count = _summary_count(baseline_report, "warning_count")
    current_error_count = _summary_count(current_report, "error_count")
    baseline_error_count = _summary_count(baseline_report, "error_count")

    return {
        "baseline_path": str(baseline_path),
        "baseline_warning_count": baseline_warning_count,
        "current_warning_count": current_warning_count,
        "warning_delta": current_warning_count - baseline_warning_count,
        "baseline_error_count": baseline_error_count,
        "current_error_count": current_error_count,
        "error_delta": current_error_count - baseline_error_count,
        "new_warning_count": len(new_fingerprints),
        "resolved_warning_count": len(resolved_fingerprints),
        "new_warnings": [
            _delta_diagnostic(current_by_fingerprint[fingerprint])
            for fingerprint in sorted(new_fingerprints)
        ],
        "resolved_warnings": [
            _delta_diagnostic(baseline_by_fingerprint[fingerprint])
            for fingerprint in sorted(resolved_fingerprints)
        ],
        "by_rule_delta": _delta_rows(current_warnings, baseline_warnings, "rule"),
        "by_risk_plane_delta": _delta_rows(
            current_warnings,
            baseline_warnings,
            "risk_plane",
        ),
    }


def count_any_unknown_indicators(
    diagnostics: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    diagnostics_list = list(diagnostics)
    counters = {
        "diagnostics_mentioning_unknown": 0,
        "diagnostics_mentioning_any": 0,
        "dict_unknown_unknown": 0,
        "list_unknown": 0,
        "unknown_member_type": 0,
        "unknown_argument_type": 0,
    }
    by_file: Counter[str] = Counter()
    by_rule: Counter[str] = Counter()

    for diagnostic in diagnostics_list:
        message = str(diagnostic.get("message", ""))
        rule = str(diagnostic.get("rule", "unknown"))
        file_path = str(diagnostic.get("file", ""))
        indicator_counted = False

        if "Unknown" in message:
            counters["diagnostics_mentioning_unknown"] += 1
            indicator_counted = True
        if "Any" in message:
            counters["diagnostics_mentioning_any"] += 1
            indicator_counted = True
        if "dict[Unknown, Unknown]" in message:
            counters["dict_unknown_unknown"] += 1
            indicator_counted = True
        if "list[Unknown]" in message:
            counters["list_unknown"] += 1
            indicator_counted = True
        if rule == "reportUnknownMemberType":
            counters["unknown_member_type"] += 1
            indicator_counted = True
        if rule == "reportUnknownArgumentType":
            counters["unknown_argument_type"] += 1
            indicator_counted = True

        if indicator_counted:
            by_file[file_path] += 1
            by_rule[rule] += 1

    return {
        **counters,
        "by_file": _counter_rows(by_file, key_name="file"),
        "by_rule": _counter_rows(by_rule, key_name="rule"),
    }


def warnings_per_kloc(
    *,
    app_files: Iterable[str],
    warning_diagnostics: Iterable[Mapping[str, Any]],
    repo_root: Path,
) -> list[dict[str, Any]]:
    lines_by_module: Counter[str] = Counter()
    warnings_by_module = Counter(
        _module_for_path(str(diagnostic.get("file", "")))
        for diagnostic in warning_diagnostics
    )

    for file_path in app_files:
        module = _module_for_path(file_path)
        lines_by_module[module] += _line_count(repo_root / file_path)

    rows: list[dict[str, Any]] = []
    for module in sorted(set(lines_by_module) | set(warnings_by_module)):
        lines = lines_by_module[module]
        warning_count = warnings_by_module[module]
        rows.append(
            {
                "module": module,
                "warnings": warning_count,
                "lines": lines,
                "warnings_per_kloc": round(
                    (warning_count / lines) * 1000,
                    2,
                )
                if lines
                else 0.0,
            }
        )
    return sorted(rows, key=lambda row: (-row["warnings_per_kloc"], row["module"]))


def render_markdown(report: Mapping[str, Any]) -> str:
    summary = _mapping(report.get("summary", {}))
    lines = [
        "# Warning Governance Report",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Pyright errors | {summary.get('error_count', 0)} |",
        f"| Pyright warnings | {summary.get('warning_count', 0)} |",
        f"| Pyright information | {summary.get('information_count', 0)} |",
        f"| App Python files scanned | {summary.get('files_total', 0)} |",
        f"| Files analyzed | {summary.get('files_analyzed', 0)} |",
        f"| Files with warnings | {summary.get('files_with_warnings', 0)} |",
        f"| Clean app files | {summary.get('clean_files', 0)} |",
        (
            "| Clean-file coverage | "
            f"{summary.get('clean_file_coverage_percent', 0.0):.2f}% |"
        ),
        (
            "| Warning-free high-risk-plane files | "
            f"{summary.get('warning_free_high_risk_files', 0)} / "
            f"{summary.get('high_risk_files_total', 0)} |"
        ),
        (
            "| Warning-free high-risk-plane coverage | "
            f"{summary.get('warning_free_high_risk_plane_percent', 0.0):.2f}% |"
        ),
    ]

    _append_table(lines, "Warning Count By Rule", report.get("by_rule", []), "rule")
    _append_table(
        lines,
        "Warning Count By Module",
        report.get("by_module", []),
        "module",
    )
    _append_table(
        lines,
        "Warning Count By Risk Plane",
        report.get("by_risk_plane", []),
        "risk_plane",
    )
    _append_table(lines, "Top Warning Files", report.get("top_files", []), "file")
    _append_any_unknown(lines, _mapping(report.get("any_unknown_indicators", {})))
    _append_baseline_delta(lines, report.get("baseline_delta"))
    lines.append("")
    return "\n".join(lines)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate warning governance metrics from Pyright JSON output.",
    )
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--baseline-json", type=Path)
    parser.add_argument("--fail-on-regression", action="store_true")
    return parser.parse_args(argv)


def _run_pyright(repo_root: Path) -> Mapping[str, Any]:
    completed = subprocess.run(
        PYRIGHT_COMMAND,
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        stderr = completed.stderr.strip()
        raise RuntimeError(f"Pyright did not return valid JSON: {stderr}") from exc
    if not isinstance(payload, Mapping):
        raise RuntimeError("Pyright JSON output was not an object")
    return payload


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _python_files(root: Path, *, repo_root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(
        _relative_path(str(path), repo_root=repo_root)
        for path in root.rglob("*.py")
        if path.is_file()
    )


def _relative_path(path: str, *, repo_root: Path) -> str:
    raw_path = Path(path)
    try:
        return raw_path.resolve().relative_to(repo_root).as_posix()
    except (OSError, ValueError):
        return _normalize_rel_path(path)


def _normalize_rel_path(path: str | Path) -> str:
    return str(path).replace("\\", "/").lstrip("./")


def _range_position(diagnostic: Mapping[str, Any], key: str) -> dict[str, int]:
    range_payload = diagnostic.get("range", {})
    if not isinstance(range_payload, Mapping):
        return {"line": 0, "character": 0}
    position = range_payload.get(key, {})
    if not isinstance(position, Mapping):
        return {"line": 0, "character": 0}
    return {
        "line": int(position.get("line", 0)) + 1,
        "character": int(position.get("character", 0)) + 1,
    }


def _module_for_path(path: str) -> str:
    normalized = _normalize_rel_path(path)
    app_prefix = f"{APP_ROOT.as_posix()}/"
    if normalized.startswith(app_prefix):
        remainder = normalized.removeprefix(app_prefix)
        return remainder.split("/", 1)[0] if "/" in remainder else "app"
    backend_prefix = "apps/backend/"
    if normalized.startswith(backend_prefix):
        remainder = normalized.removeprefix(backend_prefix)
        return remainder.split("/", 1)[0]
    return normalized.split("/", 1)[0] if normalized else "unknown"


def _is_financial_action_path(parts: Sequence[str]) -> bool:
    lowered_parts = {part.lower() for part in parts}
    if lowered_parts.intersection(FINANCIAL_ACTION_KEYWORDS):
        return True
    path_text = "/".join(part.lower() for part in parts)
    return any(f"/{keyword}_" in path_text for keyword in FINANCIAL_ACTION_KEYWORDS)


def _is_queue_or_core_path(normalized: str, parts: Sequence[str]) -> bool:
    del parts
    return normalized == "apps/backend/app/queues.py" or _starts_with_any(
        normalized,
        (
            "apps/backend/app/core/",
            "apps/backend/app/queue_operations/",
            "apps/backend/app/hardening/admission/",
        ),
    )


def _is_auth_security_path(normalized: str, parts: Sequence[str]) -> bool:
    if normalized in AUTH_SECURITY_DB_FILES:
        return True
    if normalized.startswith("apps/backend/app/db/") and (
        "rls" in normalized
        or "tenant_context" in normalized
        or "session_factory" in normalized
    ):
        return True
    if _starts_with_any(
        normalized,
        (
            "apps/backend/app/auth/",
            "apps/backend/app/identity/",
            "apps/backend/app/middleware/",
            "apps/backend/app/tenant/",
        ),
    ):
        return True
    lowered_parts = {part.lower() for part in parts}
    return normalized.startswith("apps/backend/app/hardening/") and bool(
        lowered_parts.intersection(
            {
                "identity",
                "integrity",
                "isolation",
                "survivability",
                "validation",
            }
        )
    )


def _is_policy_path(parts: Sequence[str]) -> bool:
    lowered_parts = {part.lower() for part in parts}
    return bool(lowered_parts.intersection({"policies", "policy"}))


def _starts_with_any(value: str, prefixes: Sequence[str]) -> bool:
    return any(value.startswith(prefix) for prefix in prefixes)


def _counter_rows(counter: Counter[str], *, key_name: str) -> list[dict[str, Any]]:
    return [
        {key_name: key, "count": count}
        for key, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]


def _delta_rows(
    current: Iterable[Mapping[str, Any]],
    baseline: Iterable[Mapping[str, Any]],
    key: str,
) -> list[dict[str, Any]]:
    current_counter = Counter(str(diagnostic.get(key, "unknown")) for diagnostic in current)
    baseline_counter = Counter(
        str(diagnostic.get(key, "unknown")) for diagnostic in baseline
    )
    rows = []
    for item_key in sorted(set(current_counter) | set(baseline_counter)):
        baseline_count = baseline_counter[item_key]
        current_count = current_counter[item_key]
        rows.append(
            {
                key: item_key,
                "baseline_count": baseline_count,
                "current_count": current_count,
                "delta": current_count - baseline_count,
            }
        )
    return sorted(rows, key=lambda row: (-abs(row["delta"]), row[key]))


def _delta_diagnostic(diagnostic: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "fingerprint": str(diagnostic.get("fingerprint", "")),
        "file": str(diagnostic.get("file", "")),
        "line": int(diagnostic.get("line", 0)),
        "character": int(diagnostic.get("character", 0)),
        "rule": str(diagnostic.get("rule", "unknown")),
        "risk_plane": str(diagnostic.get("risk_plane", RISK_PLANE_OTHER)),
        "message": str(diagnostic.get("message", "")),
    }


def _warning_diagnostics_from_report(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    diagnostics = report.get("diagnostics")
    if not isinstance(diagnostics, list):
        diagnostics = report.get("generalDiagnostics")
    if not isinstance(diagnostics, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in diagnostics:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("severity", "warning")) != "warning":
            continue
        diagnostic = dict(item)
        diagnostic.setdefault("rule", "unknown")
        diagnostic.setdefault("risk_plane", classify_risk_plane(str(item.get("file", ""))))
        if "line" not in diagnostic or "character" not in diagnostic:
            start = _range_position(item, "start")
            diagnostic["line"] = start["line"]
            diagnostic["character"] = start["character"]
        if "fingerprint" not in diagnostic:
            diagnostic["fingerprint"] = warning_fingerprint(diagnostic)
        normalized.append(diagnostic)
    return normalized


def _summary_count(report: Mapping[str, Any], key: str) -> int:
    summary = report.get("summary", {})
    if not isinstance(summary, Mapping):
        return 0
    if key in summary:
        return int(summary[key])
    pyright_key = {
        "warning_count": "warningCount",
        "error_count": "errorCount",
        "information_count": "informationCount",
    }.get(key)
    if pyright_key is not None and pyright_key in summary:
        return int(summary[pyright_key])
    return 0


def _load_baseline_report(path: Path, *, repo_root: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise RuntimeError(f"baseline JSON must be an object: {path}")
    if "generalDiagnostics" in payload and "diagnostics" not in payload:
        diagnostics = [
            normalize_diagnostic(diagnostic, repo_root=repo_root)
            for diagnostic in payload.get("generalDiagnostics", [])
            if isinstance(diagnostic, Mapping)
        ]
        return {
            "summary": payload.get("summary", {}),
            "diagnostics": diagnostics,
        }
    return payload


def _warning_regressed(report: Mapping[str, Any]) -> bool:
    delta = report.get("baseline_delta")
    if not isinstance(delta, Mapping):
        return False
    return int(delta.get("warning_delta", 0)) > 0


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _int_from_mapping(
    value: Any,
    key: str,
    *,
    default: int = 0,
) -> int:
    if not isinstance(value, Mapping):
        return default
    try:
        return int(value.get(key, default))
    except (TypeError, ValueError):
        return default


def _percent(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 100.0
    return round((numerator / denominator) * 100, 2)


def _line_count(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 0
    if text == "":
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _normalize_message(message: str) -> str:
    return "\n".join(line.rstrip() for line in message.replace("\r\n", "\n").split("\n"))


def _append_table(
    lines: list[str],
    title: str,
    rows_value: Any,
    key_name: str,
) -> None:
    rows = rows_value if isinstance(rows_value, list) else []
    lines.extend(["", f"## {title}", "", f"| {key_name.replace('_', ' ').title()} | Count |", "| --- | ---: |"])
    for row in rows:
        if isinstance(row, Mapping):
            lines.append(f"| {row.get(key_name, '')} | {row.get('count', 0)} |")


def _append_any_unknown(lines: list[str], indicators: Mapping[str, Any]) -> None:
    rows = [
        ("Diagnostics mentioning Unknown", indicators.get("diagnostics_mentioning_unknown", 0)),
        ("Diagnostics mentioning Any", indicators.get("diagnostics_mentioning_any", 0)),
        ("dict[Unknown, Unknown]", indicators.get("dict_unknown_unknown", 0)),
        ("list[Unknown]", indicators.get("list_unknown", 0)),
        ("reportUnknownMemberType", indicators.get("unknown_member_type", 0)),
        ("reportUnknownArgumentType", indicators.get("unknown_argument_type", 0)),
    ]
    lines.extend(["", "## Any/Unknown Propagation Indicators", "", "| Indicator | Count |", "| --- | ---: |"])
    for label, count in rows:
        lines.append(f"| {label} | {count} |")


def _append_baseline_delta(lines: list[str], delta_value: Any) -> None:
    if not isinstance(delta_value, Mapping):
        return
    lines.extend(
        [
            "",
            "## Baseline Delta",
            "",
            "| Metric | Value |",
            "| --- | ---: |",
            f"| Baseline warnings | {delta_value.get('baseline_warning_count', 0)} |",
            f"| Current warnings | {delta_value.get('current_warning_count', 0)} |",
            f"| Warning delta | {delta_value.get('warning_delta', 0)} |",
            f"| New warnings | {delta_value.get('new_warning_count', 0)} |",
            f"| Resolved warnings | {delta_value.get('resolved_warning_count', 0)} |",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
