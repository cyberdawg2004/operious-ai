#!/usr/bin/env python3
"""DLQ replay drill.

Verifies the dead-letter queue replay path end-to-end:
1. Injects one labeled test task into the dead_letter queue using the
   s10_dead_letter_probe task (same pattern as live_verification_probes.py).
2. Polls the DLQ API until the probe row appears.
3. Calls POST /api/v1/operations/dead-letters/{id}/replay.
4. Verifies the task left the DLQ (replayed=true).
5. Reports PASS/FAIL with full evidence JSON.

Prerequisites:
- CELERY_BROKER_URL (or REDIS_URL) must be reachable.
- DATABASE_URL must be reachable (for the probe execution row).
- --bearer-token must be an Auth0 operator token for the target environment.
- The worker_maintenance process group must be running (consumes dead_letter queue).

This drill writes one row to dead_letter_tasks and marks it replayed.
It is safe to run against production: the probe uses a deterministic
namespace UUID so repeated runs are idempotent (upsert).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.queues import QUEUE_DEAD_LETTER  # noqa: E402
from app.workers.celery_app import celery_app  # noqa: E402
from app.workers.s10_probe_tasks import (  # noqa: E402
    s10_probe_dead_letter_id,
    s10_probe_execution_id,
    s10_probe_session_id,
)

DRILL_NAME = "dlq_replay"
HTTP_TIMEOUT_SECONDS = 30.0
DEFAULT_PROBE_POLL_TIMEOUT_SECONDS = 90.0
DEFAULT_PROBE_POLL_INTERVAL_SECONDS = 3.0
DEFAULT_REPLAY_POLL_TIMEOUT_SECONDS = 60.0
DEFAULT_REPLAY_POLL_INTERVAL_SECONDS = 5.0


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _http_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: float = HTTP_TIMEOUT_SECONDS,
) -> tuple[int, Any]:
    payload = json.dumps(json_body, separators=(",", ":")).encode() if json_body else None
    req_headers = dict(headers or {})
    if json_body is not None:
        req_headers["Content-Type"] = "application/json"
    req = Request(url, data=payload, headers=req_headers, method=method.upper())
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return resp.status, json.loads(body) if body else {}
    except HTTPError as exc:
        body = exc.read()
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, {"raw": body.decode("utf-8", errors="replace")}
    except (TimeoutError, URLError) as exc:
        reason = str(exc.reason) if isinstance(exc, URLError) else str(exc)
        raise RuntimeError(f"HTTP {method} {url} failed: {reason}") from exc


def _api_headers(bearer_token: str | None) -> dict[str, str]:
    if bearer_token:
        return {"Authorization": f"Bearer {bearer_token}"}
    return {}


# ---------------------------------------------------------------------------
# Probe helpers (adapted from live_verification_probes.py)
# ---------------------------------------------------------------------------


async def _ensure_probe_execution_row(
    *,
    database_url: str,
    tenant_id: str,
    probe_id: str,
) -> dict[str, str]:
    """Upsert a probe execution row — same pattern as live_verification_probes."""
    from datetime import datetime, timezone

    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import get_settings
    from app.db.url import build_database_engine_config
    from app.execution.db.models import ExecutionRow
    from app.execution.enums import ExecutionKind, ExecutionState

    settings = get_settings()
    engine_config = build_database_engine_config(
        database_url,
        connect_timeout=settings.DB_CONNECT_TIMEOUT_SECONDS,
    )
    engine = create_async_engine(
        engine_config.async_url,
        connect_args=engine_config.connect_args,
    )
    execution_id = s10_probe_execution_id(tenant_id=tenant_id, probe_id=probe_id)
    session_id = s10_probe_session_id(probe_id=probe_id)
    dispatch_id = f"dlq-replay-drill-dispatch:{probe_id}"
    now = datetime.now(timezone.utc)
    metadata = {
        "probe_id": probe_id,
        "purpose": "dlq_replay_drill",
        "dispatch_id": dispatch_id,
        "session_id": session_id,
        "tenant_id": tenant_id,
    }
    stmt = (
        pg_insert(ExecutionRow)
        .values(
            execution_id=execution_id,
            kind=ExecutionKind.DIAGNOSTIC_AGENT.value,
            dispatch_id=dispatch_id,
            session_id=session_id,
            tenant_id=tenant_id,
            state=ExecutionState.DEAD_LETTERED.value,
            attempt_count=0,
            requested_at=now,
            failed_at=now,
            result={"status": "dead_lettered", "reason": "dlq_replay_drill"},
            error="dlq_replay_drill",
            metadata_json=metadata,
        )
        .on_conflict_do_update(
            index_elements=[ExecutionRow.execution_id],
            set_={
                ExecutionRow.state: ExecutionState.DEAD_LETTERED.value,
                ExecutionRow.failed_at: now,
                ExecutionRow.result: {
                    "status": "dead_lettered",
                    "reason": "dlq_replay_drill",
                },
                ExecutionRow.error: "dlq_replay_drill",
                ExecutionRow.metadata_json: metadata,
            },
        )
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            async with session.begin():
                from sqlalchemy import text as sa_text

                await session.execute(
                    sa_text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": tenant_id},
                )
                await session.execute(stmt)
    finally:
        await engine.dispose()
    return {
        "execution_id": str(execution_id),
        "session_id": session_id,
        "dispatch_id": dispatch_id,
    }


def _send_probe_task(
    *,
    tenant_id: str,
    probe_id: str,
    execution_id: str,
    session_id: str,
) -> str:
    """Send the s10_dead_letter_probe task and return the Celery task ID."""
    from datetime import datetime, timezone

    enqueued_at = datetime.now(timezone.utc).isoformat()
    async_result = celery_app.send_task(
        "s10_dead_letter_probe",
        kwargs={
            "tenant_id": tenant_id,
            "probe_id": probe_id,
            "enqueued_at": enqueued_at,
            "execution_id": execution_id,
            "session_id": session_id,
        },
        queue=QUEUE_DEAD_LETTER,
    )
    return str(getattr(async_result, "id", ""))


def _poll_dlq_api_for_probe(
    *,
    base_url: str,
    bearer_token: str | None,
    expected_dlq_id: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any] | None:
    """Poll GET /api/v1/operations/dead-letters until the probe row appears."""
    api_base = base_url.rstrip("/") + "/"
    url = urljoin(api_base, "api/v1/operations/dead-letters") + "?limit=50"
    headers = _api_headers(bearer_token)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status, data = _http_request("GET", url, headers=headers)
        if status == 200:
            items = data.get("items", []) if isinstance(data, dict) else []
            for item in items:
                if str(item.get("id", "")) == expected_dlq_id:
                    return item
        time.sleep(poll_interval_seconds)
    return None


def _replay_dlq_record(
    *,
    base_url: str,
    bearer_token: str | None,
    dlq_id: str,
) -> tuple[int, Any]:
    api_base = base_url.rstrip("/") + "/"
    url = urljoin(api_base, f"api/v1/operations/dead-letters/{dlq_id}/replay")
    return _http_request("POST", url, headers=_api_headers(bearer_token))


def _poll_for_replayed(
    *,
    base_url: str,
    bearer_token: str | None,
    dlq_id: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any] | None:
    """Poll until the DLQ record shows replayed=true."""
    api_base = base_url.rstrip("/") + "/"
    url = urljoin(api_base, "api/v1/operations/dead-letters") + "?limit=50"
    headers = _api_headers(bearer_token)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status, data = _http_request("GET", url, headers=headers)
        if status == 200:
            items = data.get("items", []) if isinstance(data, dict) else []
            for item in items:
                if str(item.get("id", "")) == dlq_id and item.get("replayed") is True:
                    return item
        time.sleep(poll_interval_seconds)
    return None


# ---------------------------------------------------------------------------
# Drill
# ---------------------------------------------------------------------------


async def run_drill_async(
    *,
    database_url: str,
    base_url: str,
    tenant_id: str,
    probe_id: str,
    bearer_token: str | None,
    probe_poll_timeout_seconds: float,
    probe_poll_interval_seconds: float,
    replay_poll_timeout_seconds: float,
    replay_poll_interval_seconds: float,
) -> dict[str, Any]:
    t0 = time.monotonic()
    expected_dlq_id = str(
        s10_probe_dead_letter_id(tenant_id=tenant_id, probe_id=probe_id)
    )

    # Step 1: Upsert execution row
    try:
        probe_execution = await _ensure_probe_execution_row(
            database_url=database_url,
            tenant_id=tenant_id,
            probe_id=probe_id,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "drill": DRILL_NAME,
            "passed": False,
            "elapsed_seconds": round(time.monotonic() - t0, 3),
            "step": "upsert_execution_row",
            "error": str(exc),
            "tenant_id": tenant_id,
            "probe_id": probe_id,
        }

    # Step 2: Send probe task to dead_letter queue
    try:
        celery_task_id = _send_probe_task(
            tenant_id=tenant_id,
            probe_id=probe_id,
            execution_id=probe_execution["execution_id"],
            session_id=probe_execution["session_id"],
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "drill": DRILL_NAME,
            "passed": False,
            "elapsed_seconds": round(time.monotonic() - t0, 3),
            "step": "send_probe_task",
            "error": str(exc),
            "tenant_id": tenant_id,
            "probe_id": probe_id,
            "probe_execution": probe_execution,
        }

    # Step 3: Poll DLQ API until probe row appears
    dlq_row = _poll_dlq_api_for_probe(
        base_url=base_url,
        bearer_token=bearer_token,
        expected_dlq_id=expected_dlq_id,
        timeout_seconds=probe_poll_timeout_seconds,
        poll_interval_seconds=probe_poll_interval_seconds,
    )
    if dlq_row is None:
        return {
            "drill": DRILL_NAME,
            "passed": False,
            "elapsed_seconds": round(time.monotonic() - t0, 3),
            "step": "poll_dlq_for_probe",
            "error": f"DLQ row {expected_dlq_id} not found within {probe_poll_timeout_seconds}s",
            "tenant_id": tenant_id,
            "probe_id": probe_id,
            "probe_execution": probe_execution,
            "celery_task_id": celery_task_id,
            "expected_dlq_id": expected_dlq_id,
        }

    # Step 4: Replay the DLQ record
    replay_status, replay_body = _replay_dlq_record(
        base_url=base_url,
        bearer_token=bearer_token,
        dlq_id=expected_dlq_id,
    )
    if replay_status not in (200, 409):  # 409 = already replayed (idempotent)
        return {
            "drill": DRILL_NAME,
            "passed": False,
            "elapsed_seconds": round(time.monotonic() - t0, 3),
            "step": "replay_dlq_record",
            "error": f"Replay returned HTTP {replay_status}",
            "replay_status": replay_status,
            "replay_body": replay_body,
            "tenant_id": tenant_id,
            "probe_id": probe_id,
            "expected_dlq_id": expected_dlq_id,
            "dlq_row": dlq_row,
        }

    # Step 5: Verify the record is now marked replayed
    replayed_row = _poll_for_replayed(
        base_url=base_url,
        bearer_token=bearer_token,
        dlq_id=expected_dlq_id,
        timeout_seconds=replay_poll_timeout_seconds,
        poll_interval_seconds=replay_poll_interval_seconds,
    )
    passed = replayed_row is not None or replay_status == 409

    return {
        "drill": DRILL_NAME,
        "passed": passed,
        "elapsed_seconds": round(time.monotonic() - t0, 3),
        "tenant_id": tenant_id,
        "probe_id": probe_id,
        "probe_execution": probe_execution,
        "celery_task_id": celery_task_id,
        "expected_dlq_id": expected_dlq_id,
        "dlq_row_found": dlq_row is not None,
        "replay_status": replay_status,
        "replay_body": replay_body,
        "replayed_row": replayed_row,
        "queue": QUEUE_DEAD_LETTER,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("OPERIOUS_BASE_URL", "https://operious-ai-imad.fly.dev"),
    )
    parser.add_argument(
        "--tenant-id",
        default=os.environ.get("OPERIOUS_TENANT_ID", "anker-pilot"),
    )
    parser.add_argument(
        "--probe-id",
        default=f"dlq-drill-{uuid.uuid4().hex[:12]}",
        help="Deterministic probe ID (reusing the same ID is idempotent)",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL"),
    )
    parser.add_argument(
        "--bearer-token",
        default=os.environ.get("OPERIOUS_OPERATOR_TOKEN"),
    )
    parser.add_argument(
        "--probe-poll-timeout-seconds",
        type=float,
        default=DEFAULT_PROBE_POLL_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--probe-poll-interval-seconds",
        type=float,
        default=DEFAULT_PROBE_POLL_INTERVAL_SECONDS,
    )
    parser.add_argument(
        "--replay-poll-timeout-seconds",
        type=float,
        default=DEFAULT_REPLAY_POLL_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--replay-poll-interval-seconds",
        type=float,
        default=DEFAULT_REPLAY_POLL_INTERVAL_SECONDS,
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    database_url = args.database_url
    if not database_url:
        try:
            from app.core.config import get_settings

            database_url = get_settings().database_url
        except Exception:  # noqa: BLE001
            print(
                "FAIL dlq_replay database_url not set; pass --database-url or set DATABASE_URL",
                file=sys.stderr,
            )
            return 2

    result = asyncio.run(
        run_drill_async(
            database_url=database_url,
            base_url=args.base_url,
            tenant_id=args.tenant_id,
            probe_id=args.probe_id,
            bearer_token=args.bearer_token,
            probe_poll_timeout_seconds=args.probe_poll_timeout_seconds,
            probe_poll_interval_seconds=args.probe_poll_interval_seconds,
            replay_poll_timeout_seconds=args.replay_poll_timeout_seconds,
            replay_poll_interval_seconds=args.replay_poll_interval_seconds,
        )
    )
    status = "PASS" if result["passed"] else "FAIL"
    print(f"{status} {DRILL_NAME} {json.dumps(result, sort_keys=True, default=str)}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
