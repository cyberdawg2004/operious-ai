"""Fly process group invariants for PR_T2."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

FLY_TOML = Path(__file__).resolve().parents[1] / "fly.toml"
DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"

EXPECTED_PROCESS_QUEUES = {
    "worker_diagnostic": (
        "diagnostic.high",
        "diagnostic.normal",
        "diagnostic.retry",
    ),
    "worker_escalation": ("escalation",),
    "worker_supervisor": ("supervisor", "qa"),
    "worker_sme_approval": ("sme_approval",),
    "worker_sop": ("sop_intelligence", "knowledge_indexing"),
    "worker_maintenance": ("webhook_maintenance", "dead_letter"),
    "worker_ingress": ("ingress.email", "ingress.whatsapp", "ingress.shopify"),
    "worker_outbound_send": ("outbound.send",),
    "worker_voice_realtime": ("ingress.voice",),
}

EXPECTED_CONCURRENCY = {
    "worker_diagnostic": 4,
    "worker_escalation": 1,
    "worker_supervisor": 1,
    "worker_sme_approval": 1,
    "worker_sop": 1,
    "worker_maintenance": 1,
    "worker_ingress": 2,
    "worker_outbound_send": 1,
    "worker_voice_realtime": 2,
}

EXPECTED_VM_PROFILES = {
    "web": ("512mb", "shared", 1),
    "worker_diagnostic": ("1024mb", "shared", 2),
    "worker_escalation": ("512mb", "shared", 1),
    "worker_supervisor": ("512mb", "shared", 1),
    "worker_sme_approval": ("512mb", "shared", 1),
    "worker_sop": ("512mb", "shared", 1),
    "worker_maintenance": ("512mb", "shared", 1),
    "worker_beat": ("256mb", "shared", 1),
    "worker_ingress": ("512mb", "shared", 1),
    "worker_outbound_send": ("512mb", "shared", 1),
    "worker_voice_realtime": ("512mb", "shared", 2),
}


def test_fly_declares_required_process_groups() -> None:
    config = _fly_config()
    processes = config["processes"]

    assert set(processes) == {
        "web",
        "worker_diagnostic",
        "worker_escalation",
        "worker_supervisor",
        "worker_sme_approval",
        "worker_sop",
        "worker_maintenance",
        "worker_beat",
        "worker_ingress",
        "worker_outbound_send",
        "worker_voice_realtime",
    }
    assert _unwrap_startup_wrapper(processes["web"]) == (
        "uvicorn app.main:app --host 0.0.0.0 --port 8000"
    )


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


def test_fly_declares_exactly_one_dedicated_celery_beat_scheduler() -> None:
    processes = _fly_config()["processes"]

    beat_processes = [
        process_name
        for process_name, command in processes.items()
        if _celery_command(command).startswith("celery -A app.workers.celery_app beat ")
    ]

    assert beat_processes == ["worker_beat"]
    assert _celery_command(processes["worker_beat"]) == (
        "celery -A app.workers.celery_app beat "
        "--loglevel=info --schedule=/tmp/celerybeat-schedule"
    )


def test_fly_workers_do_not_embed_beat_scheduler() -> None:
    processes = _fly_config()["processes"]

    for process_name in EXPECTED_PROCESS_QUEUES:
        command = _celery_command(processes[process_name])
        assert " -B" not in command
        assert " --beat" not in command


def test_http_service_targets_web_process_only() -> None:
    assert _fly_config()["http_service"]["processes"] == ["web"]


def test_fly_health_check_uses_cheap_liveness_endpoint() -> None:
    checks = _fly_config()["http_service"]["checks"]

    assert len(checks) == 1
    assert checks[0]["path"] == "/api/v1/live"


def test_container_health_check_uses_cheap_liveness_endpoint() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert "/api/v1/live" in dockerfile
    assert "/api/v1/health" not in dockerfile


def test_voice_process_groups_are_pre_warmed() -> None:
    config = _fly_config()
    assert config["http_service"]["min_machines_running"] == 1
    vm_min_machines = {
        vm["processes"][0]: vm.get("min_machines_running", 0) for vm in config["vm"]
    }

    assert vm_min_machines["web"] == 1
    assert vm_min_machines["worker_beat"] == 1
    assert vm_min_machines["worker_voice_realtime"] == 1


def test_celery_beat_process_runs_as_a_single_scheduler() -> None:
    beat_vm = _vm_profile("worker_beat")

    assert beat_vm["min_machines_running"] == 1
    assert beat_vm["max_machines_running"] == 1


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


def _vm_profile(process_name: str) -> dict[str, object]:
    for vm in _fly_config()["vm"]:
        if vm["processes"] == [process_name]:
            return vm
    raise AssertionError(f"missing VM profile for {process_name}")


def _command_queues(command: str) -> tuple[str, ...]:
    match = re.search(r"(?:\s-Q|\s--queues)\s+([^\s]+)", command)
    assert match is not None, f"missing -Q flag in {command}"
    return tuple(match.group(1).split(","))


def _command_concurrency(command: str) -> int:
    match = re.search(r"--concurrency=(\d+)", command)
    assert match is not None, f"missing --concurrency flag in {command}"
    return int(match.group(1))


def _worker_command(command: str) -> str:
    return _celery_command(command)


def test_fly_workers_use_nullpool() -> None:
    processes = _fly_config()["processes"]

    for process_name in (*EXPECTED_PROCESS_QUEUES, "worker_beat"):
        command = _unwrap_startup_wrapper(processes[process_name])
        assert command.startswith(
            "env DB_USE_NULLPOOL=true "
        ), f"{process_name} must run workers with DB_USE_NULLPOOL=true"


def _celery_command(command: str) -> str:
    return (
        _unwrap_startup_wrapper(command)
        .removeprefix("env DB_USE_NULLPOOL=true ")
        .strip()
    )


def _unwrap_startup_wrapper(command: str) -> str:
    return command.removeprefix("scripts/prepare_google_credentials.sh ").strip()
