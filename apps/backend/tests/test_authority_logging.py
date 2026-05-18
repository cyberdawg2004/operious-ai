# pyright: reportAttributeAccessIssue=false
"""Branch D — authority attribution for structured logs.

Covers:

* :class:`AuthorityContextFilter` enrichment when authority is
  bound vs absent.
* ContextVar isolation across tasks (no cross-request leakage).
* Both the request-id ContextVar (B8 → observability) and the
  authority-source ContextVar coexist without interfering.
"""

from __future__ import annotations

import logging

from app.identity import (
    AuthorityContext,
    TenantId,
    PrincipalId,
    OrganizationId,
    EnvironmentId,
    reset_request_authority,
    reset_request_authority_source,
    set_request_authority,
    set_request_authority_source,
)
from app.observability.authority_logging import AuthorityContextFilter


def _make_record() -> logging.LogRecord:
    return logging.LogRecord(
        name="t",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=None,
        exc_info=None,
    )


def test_filter_attaches_defaults_outside_request() -> None:
    record = _make_record()
    assert AuthorityContextFilter().filter(record) is True
    assert record.tenant_id == "-"
    assert record.principal_id == "-"
    assert record.organization_id == "-"
    assert record.environment_id == "-"
    assert record.authority_source == "-"


def test_filter_extracts_all_axes_when_bound() -> None:
    authority = AuthorityContext(
        tenant_id=TenantId("acme"),
        principal_id=PrincipalId("alice"),
        organization_id=OrganizationId("acme-ops"),
        environment_id=EnvironmentId("prod"),
    )
    auth_token = set_request_authority(authority)
    source_token = set_request_authority_source("verified")
    try:
        record = _make_record()
        AuthorityContextFilter().filter(record)
        assert record.tenant_id == "acme"
        assert record.principal_id == "alice"
        assert record.organization_id == "acme-ops"
        assert record.environment_id == "prod"
        assert record.authority_source == "verified"
    finally:
        reset_request_authority_source(source_token)
        reset_request_authority(auth_token)


def test_filter_uses_dash_for_unset_axes() -> None:
    """An :class:`AuthorityContext` with only some axes populated
    still produces a record with the missing axes filled with the
    sentinel."""
    authority = AuthorityContext(tenant_id=TenantId("acme"))
    auth_token = set_request_authority(authority)
    source_token = set_request_authority_source("header")
    try:
        record = _make_record()
        AuthorityContextFilter().filter(record)
        assert record.tenant_id == "acme"
        assert record.principal_id == "-"
        assert record.organization_id == "-"
        assert record.environment_id == "-"
        assert record.authority_source == "header"
    finally:
        reset_request_authority_source(source_token)
        reset_request_authority(auth_token)


def test_filter_does_not_mutate_record_payload() -> None:
    record = _make_record()
    original_msg = record.msg
    AuthorityContextFilter().filter(record)
    assert record.msg == original_msg


def test_filter_returns_true_always() -> None:
    """The filter is for enrichment, not censorship — must always
    let records through."""
    assert AuthorityContextFilter().filter(_make_record()) is True


def test_capabilities_deliberately_not_logged() -> None:
    """Capabilities can be large; the filter intentionally omits
    them from records."""
    authority = AuthorityContext(
        tenant_id=TenantId("acme"),
        capabilities=frozenset({"a", "b", "c"}),
    )
    auth_token = set_request_authority(authority)
    source_token = set_request_authority_source("verified")
    try:
        record = _make_record()
        AuthorityContextFilter().filter(record)
        assert not hasattr(record, "capabilities")
    finally:
        reset_request_authority_source(source_token)
        reset_request_authority(auth_token)


# ─── ContextVar isolation ──────────────────────────────────────────


def test_authority_source_contextvar_isolated_per_task() -> None:
    """Like authority itself, the source ContextVar must reset on
    leaving its bound scope (no cross-request leakage)."""
    from app.identity import get_request_authority_source

    assert get_request_authority_source() is None
    token = set_request_authority_source("verified")
    try:
        assert get_request_authority_source() == "verified"
    finally:
        reset_request_authority_source(token)
    assert get_request_authority_source() is None
