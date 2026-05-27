"""Fly process group invariants for PR_T2."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

FLY_TOML = Path(__file__).resolve().parents[1] / "fly.toml"

EXPECTED_PROCESS_QUEUES = {
    "worker_diagnostic": (
        "diagnostic.high",
        "diagnostic.normal",
        "diagnostic.retry",
    ),
    "worker_escalation": ("escalation",),
    "worker_supervisor": ("supervisor", "qa"),
    "worker_sop": ("sop_intelligence", "knowledge_indexing"),
    "worker_maintenance": ("webhook_maintenance", "dead_letter"),
}

EXPECTED_CONCURRENCY = {
    "worker_diagnostic": 4,
    "worker_escalation": 4,
    "worker_supervisor": 4,
    "worker_sop": 4,
    "worker_maintenance": 2,
}

EXPECTED_VM_PROFILES = {
    "web": ("512mb", "shared", 1),
    "worker_diagnostic": ("1024mb", "shared", 2),
    "worker_escalation": ("256mb", "shared", 1),
    "worker_supervisor": ("256mb", "shared", 1),
    "worker_sop": ("256mb", "shared", 1),
    "worker_maintenance": ("256mb", "shared", 1),
}


def test_fly_declares_required_process_groups() -> None:
    config = _fly_config()
    processes = config["processes"]

    assert set(processes) == {
        "web",
        "worker_diagnostic",
        "worker_escalation",
        "worker_supervisor",
        "worker_sop",
        "worker_maintenance",
    }
    assert processes["web"] == "uvicorn app.main:app --host 0.0.0.0 --port 8000"


def test_fly_worker_processes_consume_only_declared_queues() -> None:
    processes = _fly_config()["processes"]

    for process_name, expected_queues in EXPECTED_PROCESS_QUEUES.items():
        command = processes[process_name]
        assert _worker_command(command).startswith(
            "celery -A app.workers.celery_app worker "
        )
        assert _command_queues(command) == expected_queues


def test_fly_worker_concurrency_is_explicit() -> None:
    processes = _fly_config()["processes"]

    for process_name, expected_concurrency in EXPECTED_CONCURRENCY.items():
        assert _command_concurrency(processes[process_name]) == expected_concurrency


def test_http_service_targets_web_process_only() -> None:
    assert _fly_config()["http_service"]["processes"] == ["web"]


def test_vm_profiles_match_process_groups() -> None:
    vm_profiles = {
        vm["processes"][0]: (
            vm["memory"],
            vm["cpu_kind"],
            vm["cpus"],
        )
        for vm in _fly_config()["vm"]
    }

    assert vm_profiles == EXPECTED_VM_PROFILES


def _fly_config() -> dict[str, object]:
    return tomllib.loads(FLY_TOML.read_text(encoding="utf-8"))


def _command_queues(command: str) -> tuple[str, ...]:
    match = re.search(r"\s-Q\s+([^\s]+)", command)
    assert match is not None, f"missing -Q flag in {command}"
    return tuple(match.group(1).split(","))


def _command_concurrency(command: str) -> int:
    match = re.search(r"--concurrency=(\d+)", command)
    assert match is not None, f"missing --concurrency flag in {command}"
    return int(match.group(1))


def _worker_command(command: str) -> str:
    return command.removeprefix("env DB_USE_NULLPOOL=true ").strip()


def test_fly_workers_use_nullpool() -> None:
    processes = _fly_config()["processes"]

    for process_name in EXPECTED_PROCESS_QUEUES:
        assert processes[process_name].startswith("env DB_USE_NULLPOOL=true "), (
            f"{process_name} must run workers with DB_USE_NULLPOOL=true"
        )
