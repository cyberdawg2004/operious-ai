"""Phase 6-A operational observability architectural invariants."""

from __future__ import annotations

from pathlib import Path


def test_observability_runtime_is_not_a_celery_transport() -> None:
    observability_dir = Path(__file__).parent.parent / "app" / "observability"
    offenders: list[str] = []
    for path in observability_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "app.workers" in text or "celery" in text or "Celery" in text:
            offenders.append(str(path.relative_to(observability_dir)))
    assert not offenders, (
        "operational observability must stay service/runtime/persistence "
        f"only; Celery transport leaked into {offenders}"
    )


def test_workers_do_not_own_operational_observability_reads() -> None:
    workers_dir = Path(__file__).parent.parent / "app" / "workers"
    forbidden = (
        "OperationalObservabilityRuntime",
        "PostgresOperationalObservabilityPersistence",
        "get_operational_observability_service",
        "operational_observability_service",
    )
    offenders: list[str] = []
    for path in workers_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.name}:{token}")
    assert not offenders, (
        "workers must remain transport-only and cannot own "
        f"operational observability reads: {offenders}"
    )
