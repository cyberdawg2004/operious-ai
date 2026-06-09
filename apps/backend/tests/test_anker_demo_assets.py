"""Phase 6-F Anker demo artifact checks."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


DEMO_ROOT = Path("apps/backend/scripts/anker_demo")
SCRIPT_PATH = DEMO_ROOT / "seed_anker_demo.py"
EXPECTED_TICKET_SLUGS = {
    "charging-allow",
    "refund-over-limit-deny-escalate",
    "arabic-language-review",
    "product-defect-claim",
    "ambiguous-human-review",
    "warranty-replacement-require-approval",
}


def _load_seed_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "anker_demo_seed",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_anker_demo_sop_corpus_is_complete() -> None:
    module = _load_seed_module()

    documents = module.load_demo_documents()

    assert len(documents) == 5
    assert {document.document_type for document in documents} == {
        "sop",
        "policy",
        "escalation_matrix",
        "product_guide",
    }
    for document in documents:
        assert document.content.startswith("# Anker Pilot Demo")
        assert "Source basis:" in document.content
        assert "api_key" not in document.content.casefold()
        assert "webhook_secret" not in document.content.casefold()


def test_anker_demo_tickets_cover_required_scenarios() -> None:
    module = _load_seed_module()

    tickets = module.load_demo_tickets()
    payloads = module.planned_ticket_payloads()

    assert len(tickets) == len(EXPECTED_TICKET_SLUGS)
    assert {ticket["slug"] for ticket in tickets} == EXPECTED_TICKET_SLUGS
    assert {ticket["language_code"] for ticket in tickets} >= {"en", "ar"}
    assert len({payload["external_id"] for payload in payloads}) == len(
        EXPECTED_TICKET_SLUGS
    )
    for payload in payloads:
        assert payload["channel"] == "email"
        assert payload["external_id"].startswith("anker-demo-")


def test_anker_demo_external_ids_are_deterministic() -> None:
    module = _load_seed_module()

    first = module.deterministic_external_id(
        tenant_id="anker-pilot",
        slug="charging-allow",
    )
    second = module.deterministic_external_id(
        tenant_id="anker-pilot",
        slug="charging-allow",
    )

    assert first == second
    assert "uuid4" not in SCRIPT_PATH.read_text(encoding="utf-8")


def test_anker_demo_run_id_makes_live_payloads_retry_safe() -> None:
    module = _load_seed_module()

    baseline = module.planned_ticket_payloads(tenant_id="anker-pilot")
    retry_safe = module.planned_ticket_payloads(
        tenant_id="anker-pilot",
        run_id="retry-001",
    )

    assert len(baseline) == len(retry_safe) == len(EXPECTED_TICKET_SLUGS)
    assert {payload["external_id"] for payload in baseline}.isdisjoint(
        {payload["external_id"] for payload in retry_safe}
    )
    assert all(
        payload["external_id"].endswith("-retry-001") for payload in retry_safe
    )


def test_anker_demo_dry_run_uses_confirmed_phase_6f_endpoints(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_seed_module()

    assert module.main(["--dry-run", "--skip-channel"]) == 0
    summary = json.loads(capsys.readouterr().out)
    serialized = json.dumps(summary, sort_keys=True)

    assert len(summary["knowledge_documents"]) == 5
    assert len(summary["tickets"]) == len(EXPECTED_TICKET_SLUGS)
    assert "/boundary/translation/ingress" in serialized
    assert "/coordination/dispatch" in serialized
    assert "/session/" in serialized
    assert "/knowledge/documents/" in serialized
    assert "/tenant/knowledge" in serialized
    assert "/tenant/policies" in serialized
    assert "/operational-events/replay" not in serialized
    assert "/api/v1/sessions" not in serialized


def test_execution_governance_write_bootstraps_after_missing_tenant_read() -> None:
    module = _load_seed_module()
    client = _MissingTenantReadClient(module)

    result = module.seed_execution_governance(client, force=False)

    assert result["method"] == "POST"
    assert result["path"] == "/tenant/execution-governance"
    assert client.get_paths == ["/tenant/execution-governance?status=active&limit=100"]
    assert client.post_paths == ["/tenant/execution-governance"]


class _MissingTenantReadClient:
    def __init__(self, module: ModuleType) -> None:
        self._module = module
        self.get_paths: list[str] = []
        self.post_paths: list[str] = []

    def get(self, path: str) -> Any:
        self.get_paths.append(path)
        raise self._module.ApiError(
            "GET failed",
            status=500,
            body='{"title":"internal_error"}',
        )

    def post(self, path: str, payload: Any) -> Any:
        self.post_paths.append(path)
        return self._module.ApiResult(
            method="POST",
            path=path,
            status=200,
            body={
                "config_id": "demo-config",
                "status": payload["status"],
                "metadata": payload["metadata"],
            },
        )
