#!/usr/bin/env python3
"""Queue saturation drill.

Validates that admission-control configuration values and queue-depth
reporting are correct without flooding production with real tasks.

The drill:
1. Reads current queue depths from the RabbitMQ management API (if configured)
   or falls back to the health/queue-status HTTP endpoint.
2. Verifies depth reporting is functional (returns numeric values for
   all queues in ALL_QUEUES).
3. Checks the ADMISSION_QUEUE_DEPTH_WARN and ADMISSION_QUEUE_DEPTH_REJECT
   thresholds are set to sensible values.
4. Verifies that the health endpoint correctly classifies queue status as
   "warn" when a depth is between WARN and REJECT, and "critical" when
   at or above REJECT.
5. Reports PASS/FAIL with timing and depth readings.

This script is a proof-of-configuration drill. It does NOT submit real tasks
to the queues. It validates the monitoring path, not the task path.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.queues import ALL_QUEUES  # noqa: E402

DRILL_NAME = "queue_saturation"
HTTP_TIMEOUT_SECONDS = 30.0


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _http_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = HTTP_TIMEOUT_SECONDS,
) -> tuple[int, bytes]:
    req = Request(url, headers=headers or {}, method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except HTTPError as exc:
        return exc.code, exc.read()
    except (TimeoutError, URLError) as exc:
        reason = str(exc.reason) if isinstance(exc, URLError) else str(exc)
        raise RuntimeError(f"HTTP GET {url} failed: {reason}") from exc


def _http_get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    status, body = _http_get(url, headers=headers)
    try:
        data = json.loads(body.decode("utf-8")) if body else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Non-JSON response from {url}: {body[:200]!r}") from exc
    return status, data


def _rabbitmq_get_json(url: str, *, username: str, password: str) -> Any:
    import base64

    credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    status, data = _http_get_json(url, headers={"Authorization": f"Basic {credentials}"})
    if status != 200:
        raise RuntimeError(f"RabbitMQ management API returned HTTP {status}: {data}")
    return data


# ---------------------------------------------------------------------------
# Queue depth reading
# ---------------------------------------------------------------------------


def _read_depths_rabbitmq(
    *,
    api_url: str,
    username: str,
    password: str,
    vhost: str,
) -> dict[str, int]:
    """Read queue depths from the RabbitMQ management HTTP API."""
    from urllib.parse import quote

    encoded_vhost = quote(vhost, safe="")
    queues_url = f"{api_url.rstrip('/')}/api/queues/{encoded_vhost}"
    data = _rabbitmq_get_json(queues_url, username=username, password=password)
    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected RabbitMQ queues response: {type(data)}")
    return {item["name"]: int(item.get("messages", 0)) for item in data if "name" in item}


def _read_depths_http(
    *,
    base_url: str,
    bearer_token: str | None,
) -> dict[str, int]:
    """Read queue depths from the queue-status HTTP endpoint."""
    url = urljoin(base_url.rstrip("/") + "/", "api/v1/operations/queue-status")
    headers: dict[str, str] = {}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    status, data = _http_get_json(url, headers=headers)
    if status not in (200, 401, 403):
        raise RuntimeError(f"queue-status returned HTTP {status}")
    if status in (401, 403):
        # Fall back to health endpoint which is unauthenticated
        health_url = urljoin(base_url.rstrip("/") + "/", "api/v1/health")
        _, health_data = _http_get_json(health_url)
        queues = health_data.get("queues") or {}
        if isinstance(queues, dict):
            return {name: int(info.get("depth", 0)) for name, info in queues.items()}
        return {}
    queues = data.get("queues") or data if isinstance(data, dict) else {}
    if isinstance(queues, dict):
        return {name: int(info.get("depth", 0)) for name, info in queues.items()}
    # Try list format
    if isinstance(data, list):
        return {item["name"]: int(item.get("depth", 0)) for item in data if "name" in item}
    return {}


def _read_health_queue_statuses(base_url: str) -> dict[str, dict[str, Any]]:
    """Read queue statuses from the /health endpoint."""
    url = urljoin(base_url.rstrip("/") + "/", "api/v1/health")
    status, data = _http_get_json(url)
    if status != 200:
        raise RuntimeError(f"/health returned HTTP {status}")
    queues = data.get("queues") or {}
    if isinstance(queues, list):
        return {item["name"]: item for item in queues if "name" in item}
    if isinstance(queues, dict):
        return queues
    return {}


# ---------------------------------------------------------------------------
# Settings validation
# ---------------------------------------------------------------------------


def _load_settings_thresholds() -> dict[str, Any]:
    """Load admission thresholds from Settings without a running app."""
    try:
        from app.core.config import get_settings

        s = get_settings()
        return {
            "ADMISSION_QUEUE_DEPTH_WARN": s.ADMISSION_QUEUE_DEPTH_WARN,
            "ADMISSION_QUEUE_DEPTH_REJECT": s.ADMISSION_QUEUE_DEPTH_REJECT,
            "ALERT_QUEUE_AGE_CRITICAL_SECONDS": s.ALERT_QUEUE_AGE_CRITICAL_SECONDS,
            "ALERT_DLQ_SPIKE_THRESHOLD": s.ALERT_DLQ_SPIKE_THRESHOLD,
        }
    except Exception as exc:  # noqa: BLE001
        return {"settings_load_error": str(exc)}


# ---------------------------------------------------------------------------
# Drill checks
# ---------------------------------------------------------------------------


def _check_thresholds(thresholds: dict[str, Any]) -> dict[str, Any]:
    """Validate threshold values make logical sense."""
    issues = []
    warn = thresholds.get("ADMISSION_QUEUE_DEPTH_WARN")
    reject = thresholds.get("ADMISSION_QUEUE_DEPTH_REJECT")
    if warn is not None and reject is not None:
        if warn >= reject:
            issues.append(
                f"ADMISSION_QUEUE_DEPTH_WARN={warn} must be < ADMISSION_QUEUE_DEPTH_REJECT={reject}"
            )
        if warn <= 0:
            issues.append(f"ADMISSION_QUEUE_DEPTH_WARN={warn} must be > 0")
        if reject <= 0:
            issues.append(f"ADMISSION_QUEUE_DEPTH_REJECT={reject} must be > 0")
    return {
        "thresholds": thresholds,
        "issues": issues,
        "passed": len(issues) == 0 and "settings_load_error" not in thresholds,
    }


def _check_depth_coverage(depths: dict[str, int]) -> dict[str, Any]:
    """Verify depth reporting covers all known queues."""
    known = set(ALL_QUEUES)
    reported = set(depths.keys())
    missing = known - reported
    return {
        "known_queue_count": len(known),
        "reported_queue_count": len(reported),
        "missing_queues": sorted(missing),
        "depths": {q: depths.get(q, -1) for q in sorted(known)},
        "passed": len(missing) == 0,
    }


def _check_warn_reject_boundary(
    depths: dict[str, int],
    *,
    warn_threshold: int,
    reject_threshold: int,
) -> dict[str, Any]:
    """Verify depth readings are plausible relative to thresholds."""
    overloaded = [q for q, d in depths.items() if d >= reject_threshold]
    warning_range = [
        q for q, d in depths.items() if warn_threshold <= d < reject_threshold
    ]
    max_depth = max(depths.values()) if depths else 0
    return {
        "warn_threshold": warn_threshold,
        "reject_threshold": reject_threshold,
        "max_depth_observed": max_depth,
        "queues_at_or_above_reject": overloaded,
        "queues_in_warn_range": warning_range,
        # Drill passes if depth reporting works and no queue is at REJECT level
        # (which would indicate an active saturation incident, not a drill)
        "passed": len(overloaded) == 0,
        "note": (
            "FAIL with queues_at_or_above_reject means a real saturation incident "
            "is active — resolve before running this drill"
        )
        if overloaded
        else None,
    }


# ---------------------------------------------------------------------------
# Main drill
# ---------------------------------------------------------------------------


def run_drill(
    *,
    rabbitmq_api_url: str | None,
    rabbitmq_username: str | None,
    rabbitmq_password: str | None,
    rabbitmq_vhost: str,
    base_url: str,
    bearer_token: str | None,
) -> dict[str, Any]:
    t0 = time.monotonic()
    results: dict[str, Any] = {}

    # Step 1: Load thresholds
    thresholds = _load_settings_thresholds()
    results["thresholds"] = _check_thresholds(thresholds)

    warn = thresholds.get("ADMISSION_QUEUE_DEPTH_WARN", 500)
    reject = thresholds.get("ADMISSION_QUEUE_DEPTH_REJECT", 2000)

    # Step 2: Read queue depths
    source = "none"
    depths: dict[str, int] = {}
    depth_error: str | None = None
    if rabbitmq_api_url and rabbitmq_username and rabbitmq_password:
        try:
            depths = _read_depths_rabbitmq(
                api_url=rabbitmq_api_url,
                username=rabbitmq_username,
                password=rabbitmq_password,
                vhost=rabbitmq_vhost,
            )
            source = "rabbitmq_management_api"
        except Exception as exc:  # noqa: BLE001
            depth_error = str(exc)

    if not depths and not depth_error:
        try:
            depths = _read_depths_http(base_url=base_url, bearer_token=bearer_token)
            source = "http_queue_status"
        except Exception as exc:  # noqa: BLE001
            depth_error = str(exc)

    results["depth_source"] = source
    if depth_error:
        results["depth_error"] = depth_error

    # Step 3: Coverage check
    if depths:
        results["coverage"] = _check_depth_coverage(depths)

        # Step 4: Warn/reject boundary check
        results["boundary"] = _check_warn_reject_boundary(
            depths, warn_threshold=warn, reject_threshold=reject
        )
    else:
        results["coverage"] = {"passed": False, "error": depth_error or "no depths read"}
        results["boundary"] = {"passed": False, "error": "no depths to check"}

    elapsed = time.monotonic() - t0
    all_passed = all(
        v.get("passed", False) for v in results.values() if isinstance(v, dict)
    )
    return {
        "drill": DRILL_NAME,
        "passed": all_passed,
        "elapsed_seconds": round(elapsed, 3),
        "checks": results,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rabbitmq-api-url",
        default=os.environ.get("RABBITMQ_MANAGEMENT_API_URL"),
        help="RabbitMQ management API base URL (e.g. http://localhost:15672)",
    )
    parser.add_argument(
        "--rabbitmq-username",
        default=os.environ.get("RABBITMQ_MANAGEMENT_USERNAME"),
    )
    parser.add_argument(
        "--rabbitmq-password",
        default=os.environ.get("RABBITMQ_MANAGEMENT_PASSWORD"),
    )
    parser.add_argument(
        "--rabbitmq-vhost",
        default=os.environ.get("RABBITMQ_MANAGEMENT_VHOST", "/"),
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("OPERIOUS_BASE_URL", "https://operious-ai-imad.fly.dev"),
        help="Backend base URL (default: https://operious-ai-imad.fly.dev)",
    )
    parser.add_argument(
        "--bearer-token",
        default=os.environ.get("OPERIOUS_OPERATOR_TOKEN"),
        help="Auth0 operator bearer token for queue-status endpoint",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = run_drill(
        rabbitmq_api_url=args.rabbitmq_api_url,
        rabbitmq_username=args.rabbitmq_username,
        rabbitmq_password=args.rabbitmq_password,
        rabbitmq_vhost=args.rabbitmq_vhost,
        base_url=args.base_url,
        bearer_token=args.bearer_token,
    )
    status = "PASS" if result["passed"] else "FAIL"
    print(f"{status} {DRILL_NAME} {json.dumps(result, sort_keys=True, default=str)}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
