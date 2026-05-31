"""Spec 1b — rate-limit fail policy + 429/503 responses."""

from __future__ import annotations

from app.core.rate_limit import (
    fail_open_allowed,
    service_unavailable_response,
    too_many_requests_response,
)


def test_idempotent_reads_fail_degraded_open() -> None:
    assert fail_open_allowed("GET") is True
    assert fail_open_allowed("HEAD") is True
    assert fail_open_allowed("OPTIONS") is True
    assert fail_open_allowed("get") is True  # case-insensitive


def test_writes_fail_closed() -> None:
    assert fail_open_allowed("POST") is False
    assert fail_open_allowed("PUT") is False
    assert fail_open_allowed("PATCH") is False
    assert fail_open_allowed("DELETE") is False


def test_429_response_has_retry_after() -> None:
    resp = too_many_requests_response(retry_after_seconds=7)
    assert resp.status_code == 429
    assert resp.headers["retry-after"] == "7"


def test_503_response_for_backend_unavailable() -> None:
    resp = service_unavailable_response()
    assert resp.status_code == 503
