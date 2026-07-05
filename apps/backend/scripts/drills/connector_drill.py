#!/usr/bin/env python3
"""Connector configuration and probe drill.

Exercises the tenant connector configuration path end-to-end:
1. Proposes a connector config change request
2. Approves it (requires a different principal — dual-control)
3. Applies it
4. Optionally probes the connector endpoint (--probe-http)
5. Cleans up (revokes or leaves for inspection)

This covers warranty/replacement connector, OMS credential update, and
inventory check connector paths through the same dual-control ledger.

Usage:
    PYTHONPATH=/app python3 scripts/drills/connector_drill.py \\
        --base-url https://operious-ai-imad.fly.dev \\
        --tenant-id <tenant> \\
        --proposer-token <jwt> \\
        --approver-token <jwt> \\
        --connector-type goods.warranty \\
        --tool-name warranty.claim \\
        --endpoint https://httpbin.org/post

Note: proposer and approver must be DIFFERENT Auth0 principals.
This is enforced server-side (S-03 dual-control).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from typing import Any
from urllib.error import HTTPError


def _req(method: str, url: str, *, headers: dict[str, str], body: bytes | None = None, timeout: float = 15.0) -> tuple[int, Any]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {"error": str(e)}


def run_drill(
    *,
    base_url: str,
    tenant_id: str,
    proposer_token: str,
    approver_token: str,
    connector_type: str,
    tool_name: str,
    endpoint: str,
    probe_http: bool,
) -> dict[str, Any]:
    prop_headers = {
        "Authorization": f"Bearer {proposer_token}",
        "Content-Type": "application/json",
    }
    appr_headers = {
        "Authorization": f"Bearer {approver_token}",
        "Content-Type": "application/json",
    }
    steps: list[dict[str, Any]] = []

    # Step 1: Propose connector config change request
    payload = {
        "policy_type": "connector_config",
        "parameters": {
            "connector_type": connector_type,
            "tool_name": tool_name,
            "http_method": "POST",
            "endpoint_template": endpoint,
            "endpoint_host": endpoint.split("/")[2] if "/" in endpoint else endpoint,
            "idempotency_header_name": "Idempotency-Key",
        },
    }
    status, body = _req(
        "POST",
        f"{base_url}/api/v1/tenant/config/change-requests",
        headers=prop_headers,
        body=json.dumps(payload).encode(),
    )
    steps.append({"step": "propose", "status": status, "body": body})
    if status not in (200, 201, 202):
        return {"overall": "FAIL", "steps": steps, "failure": "propose failed"}

    cr_id = body.get("change_request_id") or body.get("id")
    if not cr_id:
        return {"overall": "FAIL", "steps": steps, "failure": "no change_request_id in response"}

    # Step 2: Approve (must be different principal)
    status2, body2 = _req(
        "POST",
        f"{base_url}/api/v1/tenant/config/change-requests/{cr_id}/approve",
        headers=appr_headers,
        body=b"{}",
    )
    steps.append({"step": "approve", "status": status2, "body": body2, "change_request_id": cr_id})
    if status2 not in (200, 201, 202):
        return {"overall": "FAIL", "steps": steps, "failure": "approve failed (check proposer≠approver)"}

    # Step 3: Apply (proposer can apply after approval)
    status3, body3 = _req(
        "POST",
        f"{base_url}/api/v1/tenant/config/change-requests/{cr_id}/apply",
        headers=prop_headers,
        body=b"{}",
    )
    steps.append({"step": "apply", "status": status3, "body": body3})
    if status3 not in (200, 201, 202):
        return {"overall": "FAIL", "steps": steps, "failure": "apply failed"}

    # Step 4: Optionally probe the connector endpoint
    if probe_http:
        status4, body4 = _req(
            "POST",
            f"{base_url}/api/v1/tenant/connectors/{tool_name}/probe",
            headers=prop_headers,
            body=json.dumps({"probe_http": True}).encode(),
        )
        steps.append({"step": "probe", "status": status4, "body": body4})

    return {"overall": "PASS", "steps": steps, "change_request_id": cr_id}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--proposer-token", required=True)
    parser.add_argument("--approver-token", required=True)
    parser.add_argument("--connector-type", default="goods.warranty")
    parser.add_argument("--tool-name", default="warranty.claim")
    parser.add_argument("--endpoint", default="https://httpbin.org/post")
    parser.add_argument("--probe-http", action="store_true")
    args = parser.parse_args()

    result = run_drill(
        base_url=args.base_url,
        tenant_id=args.tenant_id,
        proposer_token=args.proposer_token,
        approver_token=args.approver_token,
        connector_type=args.connector_type,
        tool_name=args.tool_name,
        endpoint=args.endpoint,
        probe_http=args.probe_http,
    )
    print(f"{result['overall']} connector_drill {json.dumps(result, indent=2)}")
    return 0 if result["overall"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
