"""Worker process boot guard.

Regression guard for the 2026-06-13 production incident: all Celery
workers crash-looped because ``app.workers.celery_app`` had a circular
import that only manifests when ``app.workers.celery_app`` is the import
*entrypoint* (as it is for ``celery -A app.workers.celery_app worker``).

A normal pytest import graph loads ``app.workers.celery_app`` indirectly,
after other modules have already populated ``sys.modules`` -- which hides
this class of cycle. This test runs a fresh subprocess that imports
``app.workers.celery_app`` first, then every module in its Celery
``include=[...]`` list, exactly as the worker entrypoint does, and fails
if any import raises.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]

_WORKER_INCLUDE_MODULES = [
    "app.workers.agent_tasks",
    "app.workers.approval_tasks",
    "app.workers.defect_cluster_tasks",
    "app.workers.escalation_recovery_tasks",
    "app.workers.escalation_tasks",
    "app.workers.execution_recovery_tasks",
    "app.workers.failure_pattern_tasks",
    "app.workers.ingress_dispatch_tasks",
    "app.workers.knowledge_tasks",
    "app.workers.outbound_send_tasks",
    "app.workers.outbound_tasks",
    "app.workers.qa_tasks",
    "app.workers.s10_probe_tasks",
    "app.workers.sop_intelligence_tasks",
    "app.workers.supervisor_tasks",
    "app.workers.webhook_nonce_tasks",
]

_BOOT_SCRIPT = "\n".join(
    [
        "from app.workers.celery_app import celery_app",
        *(f"import {module}" for module in _WORKER_INCLUDE_MODULES),
        "print('WORKER_BOOT_OK')",
    ]
)


def test_worker_entrypoint_imports_without_circular_import() -> None:
    """`celery -A app.workers.celery_app worker` must import cleanly.

    Imports ``app.workers.celery_app`` as the entrypoint module (matching
    the worker's actual import order), then every task module Celery
    loads via ``include=[...]``. Any ``ImportError`` here means the
    worker process would crash-loop on boot.
    """
    result = subprocess.run(
        [sys.executable, "-c", _BOOT_SCRIPT],
        cwd=_BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, (
        f"worker entrypoint failed to import "
        f"(returncode={result.returncode}):\n{result.stderr}"
    )
    assert "WORKER_BOOT_OK" in result.stdout
