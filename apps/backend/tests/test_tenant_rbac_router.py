"""Integration: tenant mutation routes enforce domain capabilities (S-02/B4).

A tenant-scoped caller WITHOUT the route's domain capability must be
rejected with 403 before any persistence work happens. This is the
end-to-end statement of S-02/B4: tenant scope alone no longer authorises
configuration mutation, and the old broad capability is no longer the
route-level write gate.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app

# Mutation routes that must reject a non-admin tenant-scoped caller.
_MUTATIONS: list[tuple[str, str, dict]] = [
    (
        "post",
        "/api/v1/tenant/channels",
        {
            "channel_type": "email",
            "routing_address": "support@example.com",
            "credentials": {"api_key": "x"},
            "webhook_secret": "y",
        },
    ),
    (
        "post",
        "/api/v1/tenant/knowledge",
        {"title": "t", "content": "c", "document_type": "policy"},
    ),
    (
        "post",
        "/api/v1/tenant/policies",
        {"policy_type": "content_safety", "parameters": {}},
    ),
    (
        "post",
        "/api/v1/tenant/execution-governance",
        {
            "execution_quota": 10,
            "throughput_limit": 20,
            "throughput_window_minutes": 5,
            "governance_budget_limit": 30,
            "governance_budget_window_minutes": 15,
            "circuit_failure_threshold": 3,
            "circuit_window_minutes": 10,
            "circuit_cooldown_minutes": 2,
            "metadata": {},
        },
    ),
    (
        "post",
        "/api/v1/tenant/topologies",
        {"topology_name": "routing", "topology": {}},
    ),
]


@pytest.fixture
def staging_client():
    # No lifespan context manager: the capability gate (S-02) rejects
    # before any app.state/runtime is touched, so we avoid redis/db
    # startup entirely and keep the test hermetic.
    get_settings.cache_clear()
    with patch.dict(os.environ, {"ENVIRONMENT": "staging"}):
        app = create_app()
        yield TestClient(app, raise_server_exceptions=False)
    get_settings.cache_clear()


@pytest.mark.parametrize("method,path,body", _MUTATIONS)
def test_mutation_without_domain_capability_is_forbidden(
    staging_client: TestClient, method: str, path: str, body: dict
) -> None:
    # Header auth carries a tenant axis but NO capabilities.
    response = getattr(staging_client, method)(
        path, json=body, headers={"X-Tenant-ID": "acme"}
    )
    assert response.status_code == 403
    # The capability-required code surfaces through whichever error
    # envelope the app emits (RFC9457 problem+json or raw detail).
    assert "capability_required" in response.text
