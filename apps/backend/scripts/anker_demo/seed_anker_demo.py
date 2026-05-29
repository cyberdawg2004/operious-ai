#!/usr/bin/env python3
"""Seed the Phase 6-F Anker pilot demo through real backend APIs."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request

TENANT_ID = "anker-pilot"
PRINCIPAL_ID = "phase-6f-demo-seeder"
DEFAULT_API_BASE_URL = "https://operious-ai-imad.fly.dev/api/v1"

DEMO_NAMESPACE = uuid.UUID("6f000000-0000-5000-8000-00000000006f")
ROOT = Path(__file__).resolve().parent
SOPS_DIR = ROOT / "sops"
TICKETS_FILE = ROOT / "demo_tickets.json"


@dataclass(frozen=True, slots=True)
class DemoDocument:
    filename: str
    title: str
    document_type: str
    content: str


@dataclass(frozen=True, slots=True)
class ApiResult:
    method: str
    path: str
    status: int
    body: Any


DOCUMENT_MANIFEST: tuple[tuple[str, str, str], ...] = (
    (
        "anker_charging_issue_policy.md",
        "Anker Pilot Demo - Charging Issue Policy",
        "sop",
    ),
    (
        "anker_returns_policy.md",
        "Anker Pilot Demo - Returns And Refund Policy",
        "policy",
    ),
    (
        "anker_warranty_terms.md",
        "Anker Pilot Demo - Warranty Terms",
        "policy",
    ),
    (
        "anker_escalation_matrix.md",
        "Anker Pilot Demo - Escalation Matrix",
        "escalation_matrix",
    ),
    (
        "anker_product_defect_classification.md",
        "Anker Pilot Demo - Product Defect Classification Guide",
        "product_guide",
    ),
)

GOVERNANCE_POLICIES: tuple[dict[str, Any], ...] = (
    {
        "policy_type": "anker_refund_policy",
        "parameters": {
            "phase": "6-F",
            "non_quality_return_window_days": 30,
            "requires_original_packaging": True,
            "requires_all_accessories": True,
            "refund_scope": "product_cost_only_for_non_quality_returns",
            "deny_reasons": [
                "outside_return_window",
                "missing_proof_of_purchase",
                "unauthorized_reseller",
                "missing_original_packaging",
                "missing_accessories",
            ],
            "escalate_reasons": [
                "chargeback_threat",
                "legal_threat",
                "safety_signal",
                "quality_defect_claim",
            ],
        },
        "status": "active",
    },
    {
        "policy_type": "anker_confidence_thresholds",
        "parameters": {
            "phase": "6-F",
            "allow_min_confidence": 0.82,
            "human_review_below_confidence": 0.7,
            "multilingual_review_languages": ["ar"],
            "unknown_issue_requires_review": True,
        },
        "status": "active",
    },
    {
        "policy_type": "anker_action_tools",
        "parameters": {
            "phase": "RT6",
            "tools": {
                "warranty.claim": {
                    "allow": {
                        "confidence_gte": 0.85,
                        "issue_category_in": [
                            "charging_issue",
                            "product_defect",
                        ],
                    },
                    "else": "require_approval",
                },
                "replacement.order": {
                    "always": "require_approval",
                },
                "refund.request": {
                    "allow": {"refund_amount_cents_lte": 5000},
                    "else": "require_approval",
                },
                "warehouse.repair.report": {
                    "allow": {"severity_in": ["low", "medium"]},
                    "require_approval": {
                        "severity_in": ["high", "critical"],
                    },
                },
            },
        },
        "status": "active",
    },
    {
        "policy_type": "anker_escalation_rules",
        "parameters": {
            "phase": "6-F",
            "safety_terms": [
                "smoke",
                "fire",
                "sparking",
                "swelling",
                "burning smell",
                "electric shock",
                "overheating",
            ],
            "risk_terms": ["chargeback", "legal", "fraud", "counterfeit"],
            "queues": {
                "safety": "tier_2_product_safety",
                "refund_exception": "governance_review",
                "language_gap": "multilingual_support_lead",
                "ambiguous": "human_review",
            },
        },
        "status": "active",
    },
)

EXECUTION_GOVERNANCE_PAYLOAD: dict[str, Any] = {
    "execution_quota": 1000,
    "throughput_limit": 120,
    "throughput_window_minutes": 60,
    "governance_budget_limit": 1000,
    "governance_budget_window_minutes": 60,
    "circuit_failure_threshold": 20,
    "circuit_window_minutes": 15,
    "circuit_cooldown_minutes": 5,
    "status": "active",
    "metadata": {
        "phase": "6-F",
        "tenant": TENANT_ID,
        "purpose": "anker_demo_scenario",
    },
}


class ApiError(RuntimeError):
    """Raised when a live API call returns an unexpected status."""

    def __init__(self, message: str, *, status: int, body: str) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def load_demo_documents() -> list[DemoDocument]:
    documents: list[DemoDocument] = []
    for filename, title, document_type in DOCUMENT_MANIFEST:
        path = SOPS_DIR / filename
        documents.append(
            DemoDocument(
                filename=filename,
                title=title,
                document_type=document_type,
                content=path.read_text(encoding="utf-8"),
            )
        )
    return documents


def load_demo_tickets() -> list[dict[str, Any]]:
    data = json.loads(TICKETS_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("demo_tickets.json must contain a list")
    return [dict(item) for item in data]


def deterministic_external_id(*, tenant_id: str, slug: str) -> str:
    ticket_id = uuid.uuid5(DEMO_NAMESPACE, f"{tenant_id}|{slug}")
    return f"anker-demo-{slug}-{ticket_id}"


def planned_ticket_payloads(
    *,
    tenant_id: str = TENANT_ID,
    run_id: str | None = None,
) -> list[dict[str, str]]:
    payloads: list[dict[str, str]] = []
    for ticket in load_demo_tickets():
        slug = _require_str(ticket, "slug")
        external_id = deterministic_external_id(
            tenant_id=tenant_id,
            slug=slug,
        )
        if run_id:
            external_id = f"{external_id}-{run_id}"
        payloads.append(
            {
                "external_id": external_id,
                "channel": _require_str(ticket, "channel"),
                "raw_content": _require_str(ticket, "raw_content"),
                "language_code": _require_str(ticket, "language_code"),
            }
        )
    return payloads


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    headers = _headers(
        tenant_id=args.tenant_id,
        principal_id=args.principal_id,
        bearer_token=args.bearer_token,
    )
    client = ApiClient(
        api_base_url=args.api_base_url,
        headers=headers,
        dry_run=args.dry_run,
        timeout_seconds=args.timeout_seconds,
    )
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    _progress(
        f"phase-6f seed start tenant={args.tenant_id} run_id={run_id} "
        f"api={client.api_base_url}"
    )
    summary: dict[str, Any] = {
        "tenant_id": args.tenant_id,
        "api_base_url": client.api_base_url,
        "run_id": run_id,
        "dry_run": args.dry_run,
        "channel": None,
        "execution_governance": None,
        "governance_policies": [],
        "knowledge_documents": [],
        "tickets": [],
    }

    if not args.skip_channel:
        _progress("seed channel configuration")
        summary["channel"] = seed_channel(
            client,
            tenant_id=args.tenant_id,
            force=args.force,
        )
    if not args.skip_policies:
        _progress("seed execution governance and tenant policies")
        summary["execution_governance"] = seed_execution_governance(
            client,
            force=args.force,
        )
        summary["governance_policies"] = seed_governance_policies(
            client,
            force=args.force,
        )
    if not args.skip_sops:
        _progress("seed and ingest knowledge documents")
        summary["knowledge_documents"] = seed_knowledge_documents(
            client,
            force=args.force,
            reingest=args.reingest,
        )
    if not args.skip_tickets:
        _progress("submit demo tickets")
        summary["tickets"] = submit_demo_tickets(
            client,
            tenant_id=args.tenant_id,
            run_id=run_id,
        )

    print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


def seed_channel(
    client: "ApiClient",
    *,
    tenant_id: str,
    force: bool,
) -> dict[str, Any]:
    routing_address = os.environ.get(
        "ANKER_EMAIL_ROUTING_ADDRESS",
        "support@anker-pilot.operious.com",
    )
    api_key = os.environ.get("ANKER_EMAIL_CHANNEL_API_KEY")
    webhook_secret = os.environ.get("ANKER_EMAIL_WEBHOOK_SECRET")
    if not client.dry_run and (not api_key or not webhook_secret):
        raise RuntimeError(
            "ANKER_EMAIL_CHANNEL_API_KEY and ANKER_EMAIL_WEBHOOK_SECRET "
            "are required for live channel seeding"
        )
    existing = _tenant_list_or_empty(
        client,
        "/tenant/channels?channel_type=email&limit=100",
    )
    if (
        not force
        and isinstance(existing.body, dict)
        and any(
            item.get("channel_type") == "email"
            and item.get("routing_address") == routing_address
            for item in existing.body.get("items", [])
            if isinstance(item, dict)
        )
    ):
        return {"status": "skipped_existing", "routing_address": routing_address}
    payload = {
        "channel_type": "email",
        "routing_address": routing_address,
        "credentials": {
            "provider": "anker_demo_email",
            "api_key": api_key or "dry-run-placeholder",
        },
        "webhook_secret": webhook_secret or "dry-run-placeholder",
        "status": "active",
    }
    return _result_dict(client.post("/tenant/channels", payload))


def seed_execution_governance(
    client: "ApiClient",
    *,
    force: bool,
) -> dict[str, Any]:
    existing = _tenant_list_or_empty(
        client,
        "/tenant/execution-governance?status=active&limit=100",
    )
    if (
        not force
        and isinstance(existing.body, dict)
        and any(
            isinstance(item, dict)
            and item.get("metadata", {}).get("phase") == "6-F"
            for item in existing.body.get("items", [])
        )
    ):
        return {"status": "skipped_existing"}
    return _result_dict(
        client.post("/tenant/execution-governance", EXECUTION_GOVERNANCE_PAYLOAD)
    )


def seed_governance_policies(
    client: "ApiClient",
    *,
    force: bool,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()
    for policy in GOVERNANCE_POLICIES:
        policy_type = str(policy["policy_type"])
        query = parse.urlencode(
            {"policy_type": policy_type, "status": "active", "limit": 100}
        )
        existing = _tenant_list_or_empty(client, f"/tenant/policies?{query}")
        if (
            not force
            and isinstance(existing.body, dict)
            and _contains_same_parameters(
                existing.body.get("items", []),
                policy["parameters"],
            )
        ):
            results.append({"policy_type": policy_type, "status": "skipped_existing"})
            continue
        payload = {
            **policy,
            "effective_from": now,
        }
        results.append(_result_dict(client.post("/tenant/policies", payload)))
    return results


def seed_knowledge_documents(
    client: "ApiClient",
    *,
    force: bool,
    reingest: bool,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    existing = _tenant_list_or_empty(client, "/tenant/knowledge?limit=100")
    existing_by_title = _records_by_title(existing.body)
    for document in load_demo_documents():
        existing_document = existing_by_title.get(document.title)
        if existing_document is not None and not force:
            document_id = str(existing_document["document_id"])
            document_result: dict[str, Any] = {
                "title": document.title,
                "document_id": document_id,
                "status": "skipped_existing",
            }
        elif existing_document is not None:
            document_id = str(existing_document["document_id"])
            document_result = _result_dict(
                client.put(
                    f"/tenant/knowledge/{document_id}",
                    {
                        "content": document.content,
                        "status": "pending_index",
                    },
                )
            )
        else:
            created = client.post(
                "/tenant/knowledge",
                {
                    "title": document.title,
                    "content": document.content,
                    "document_type": document.document_type,
                    "status": "pending_index",
                },
            )
            document_result = _result_dict(created)
            document_id = str(created.body["document_id"])

        should_ingest = (
            force
            or reingest
            or document_result.get("status") != "skipped_existing"
            or existing_document is None
            or existing_document.get("status") != "active"
        )
        if should_ingest:
            document_result["ingestion"] = _result_dict(
                client.post(f"/knowledge/documents/{document_id}/ingest", None)
            )
        results.append(document_result)
    return results


def submit_demo_tickets(
    client: "ApiClient",
    *,
    tenant_id: str,
    run_id: str,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    tickets = load_demo_tickets()
    payloads = planned_ticket_payloads(tenant_id=tenant_id, run_id=run_id)
    for ticket, payload in zip(tickets, payloads):
        slug = _require_str(ticket, "slug")
        _progress(f"[{slug}] ingress start")
        ingress = client.post("/boundary/translation/ingress", payload)
        _progress(
            f"[{slug}] ingress ok ingress_id={ingress.body.get('ingress_id')}"
        )
        _progress(f"[{slug}] dispatch start")
        dispatch = client.post(
            "/coordination/dispatch",
            {"ingress_id": ingress.body.get("ingress_id")},
        )
        _progress(
            f"[{slug}] dispatch ok session_id={dispatch.body.get('session_id')}"
        )
        item: dict[str, Any] = {
            "slug": slug,
            "scenario": ticket["scenario"],
            "expected_category": ticket["expected_category"],
            "expected_governance": ticket["expected_governance"],
            "external_id": payload["external_id"],
            "ingress": _result_dict(ingress),
            "dispatch": _result_dict(dispatch),
        }
        session_id = dispatch.body.get("session_id")
        if isinstance(session_id, str) and session_id:
            _progress(f"[{slug}] timeline fetch")
            item["timeline"] = _result_dict(
                client.get(f"/session/{session_id}/timeline")
            )
            _progress(f"[{slug}] session events fetch")
            item["session_events"] = _result_dict(
                client.get(f"/session/sessions/{session_id}/events")
            )
        results.append(item)
    return results


class ApiClient:
    def __init__(
        self,
        *,
        api_base_url: str,
        headers: dict[str, str],
        dry_run: bool,
        timeout_seconds: float,
    ) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.headers = dict(headers)
        self.dry_run = dry_run
        self.timeout_seconds = timeout_seconds

    def get(self, path: str) -> ApiResult:
        return self.request("GET", path, None)

    def post(self, path: str, payload: Any) -> ApiResult:
        return self.request("POST", path, payload)

    def put(self, path: str, payload: Any) -> ApiResult:
        return self.request("PUT", path, payload)

    def request(self, method: str, path: str, payload: Any) -> ApiResult:
        if self.dry_run:
            body = _dry_run_body(method=method, path=path, payload=payload)
            return ApiResult(method=method, path=path, status=0, body=body)
        url = f"{self.api_base_url}{path}"
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        req = request.Request(url, data=data, headers=self.headers, method=method)
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
                body = json.loads(raw_body) if raw_body else {}
                return ApiResult(
                    method=method,
                    path=path,
                    status=response.status,
                    body=body,
                )
        except error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise ApiError(
                f"{method} {path} failed with HTTP {exc.code}",
                status=exc.code,
                body=body_text,
            ) from exc


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-base-url",
        default=os.environ.get("OPERIOUS_API_BASE_URL", DEFAULT_API_BASE_URL),
    )
    parser.add_argument("--tenant-id", default=TENANT_ID)
    parser.add_argument("--principal-id", default=PRINCIPAL_ID)
    parser.add_argument(
        "--bearer-token",
        default=os.environ.get("OPERIOUS_API_TOKEN"),
        help="Optional verified bearer token. Omits X-*-ID headers when set.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--reingest", action="store_true")
    parser.add_argument(
        "--run-id",
        default=os.environ.get("ANKER_DEMO_RUN_ID"),
        help="Optional per-run suffix for ticket external IDs.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(os.environ.get("ANKER_DEMO_TIMEOUT_SECONDS", "120")),
        help="Per-request live API timeout.",
    )
    parser.add_argument("--skip-channel", action="store_true")
    parser.add_argument("--skip-policies", action="store_true")
    parser.add_argument("--skip-sops", action="store_true")
    parser.add_argument("--skip-tickets", action="store_true")
    return parser.parse_args(argv)


def _progress(message: str) -> None:
    print(f"[anker-demo] {message}", file=sys.stderr, flush=True)


def _headers(
    *,
    tenant_id: str,
    principal_id: str,
    bearer_token: str | None,
) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
        return headers
    headers["X-Tenant-ID"] = tenant_id
    headers["X-Principal-ID"] = principal_id
    return headers


def _dry_run_body(*, method: str, path: str, payload: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "dry_run": True,
        "method": method,
        "path": path,
        "payload": payload,
    }
    if method == "GET" and path.startswith("/tenant/"):
        return {**base, "items": [], "total": 0, "offset": 0}
    if method == "POST" and path == "/tenant/channels":
        return {
            **base,
            "config_id": _dry_uuid("channel", str(payload)),
            "channel_type": payload["channel_type"],
            "routing_address": payload["routing_address"],
            "status": payload["status"],
            "verified_at": None,
            "credential_rotated_at": None,
            "credential_rotation_expires_at": None,
        }
    if method == "POST" and path == "/tenant/execution-governance":
        return {
            **base,
            "config_id": _dry_uuid("execution-governance", str(payload)),
            "status": payload["status"],
            "version": 1,
            "metadata": payload.get("metadata", {}),
        }
    if method == "POST" and path == "/tenant/policies":
        return {
            **base,
            "policy_id": _dry_uuid("policy", payload["policy_type"]),
            "policy_type": payload["policy_type"],
            "parameters": payload["parameters"],
            "status": payload["status"],
            "version": 1,
        }
    if method == "POST" and path == "/tenant/knowledge":
        return {
            **base,
            "document_id": _dry_uuid("knowledge", payload["title"]),
            "title": payload["title"],
            "content": payload["content"],
            "document_type": payload["document_type"],
            "status": payload["status"],
            "version": 1,
        }
    if method == "PUT" and path.startswith("/tenant/knowledge/"):
        return {
            **base,
            "document_id": path.rsplit("/", 1)[-1],
            "content": payload.get("content"),
            "status": payload.get("status"),
        }
    if (
        method == "POST"
        and path.startswith("/knowledge/documents/")
        and path.endswith("/ingest")
    ):
        document_id = path.removeprefix("/knowledge/documents/").removesuffix(
            "/ingest"
        )
        return {
            **base,
            "tenant_id": TENANT_ID,
            "document_id": document_id,
            "document_version": 1,
            "chunk_count": 1,
            "vector_count": 1,
            "vector_index_name": "dry_run",
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        }
    if method == "POST" and path == "/boundary/translation/ingress":
        external_id = str(payload["external_id"])
        return {
            **base,
            "ingress_id": _dry_uuid("ingress", external_id),
            "canonical_envelope_id": _dry_uuid("envelope", external_id),
            "status": "received",
        }
    if method == "POST" and path == "/coordination/dispatch":
        ingress_id = str(payload["ingress_id"])
        return {
            **base,
            "dispatch_id": _dry_uuid("dispatch", ingress_id),
            "session_id": _dry_uuid("session", ingress_id),
            "execution_id": _dry_uuid("execution", ingress_id),
            "governance_decision_id": _dry_uuid("governance", ingress_id),
            "verdict": "accepted",
            "halted": False,
            "halt_reason": None,
        }
    if method == "GET" and "/timeline" in path:
        return {**base, "events": [], "total": 0}
    if method == "GET" and path.endswith("/events"):
        return {**base, "items": [], "total": 0}
    return base


def _dry_uuid(kind: str, seed: str) -> str:
    return str(uuid.uuid5(DEMO_NAMESPACE, f"dry-run|{kind}|{seed}"))


def _result_dict(result: ApiResult) -> dict[str, Any]:
    return {
        "method": result.method,
        "path": result.path,
        "status_code": result.status,
        "body": result.body,
    }


def _tenant_list_or_empty(client: ApiClient, path: str) -> ApiResult:
    """Allow the first tenant-owned write to create the tenant anchor row.

    Live production can return HTTP 500 for tenant list reads before the
    tenant exists. Writes in the tenant repository already create the
    `tenants` anchor row, so the seed runner treats only that first
    tenant-list 500 as an empty page and immediately proceeds to the
    tenant-creating write. Any following write failure still surfaces the
    exact API error.
    """

    try:
        return client.get(path)
    except ApiError as exc:
        if exc.status != 500:
            raise
        return ApiResult(
            method="GET",
            path=path,
            status=exc.status,
            body={
                "items": [],
                "total": 0,
                "offset": 0,
                "bootstrap_note": (
                    "tenant list returned HTTP 500 before tenant anchor "
                    "creation; proceeding to tenant-owned write"
                ),
                "original_body": exc.body,
            },
        )


def _records_by_title(body: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(body, dict):
        return {}
    records: dict[str, dict[str, Any]] = {}
    for item in body.get("items", []):
        if isinstance(item, dict) and isinstance(item.get("title"), str):
            records[str(item["title"])] = item
    return records


def _contains_same_parameters(items: Any, expected: Any) -> bool:
    expected_json = json.dumps(expected, sort_keys=True)
    if not isinstance(items, list):
        return False
    for item in items:
        if not isinstance(item, dict):
            continue
        parameters = item.get("parameters")
        if json.dumps(parameters, sort_keys=True) == expected_json:
            return True
    return False


def _require_str(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"ticket {key} must be a non-empty string")
    return value


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ApiError as exc:
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "status": exc.status,
                    "body": exc.body,
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
