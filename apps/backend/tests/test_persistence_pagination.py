"""Phase E bounded pagination contract tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.repositories.pagination import (
    API_DEFAULT_PAGE_LIMIT,
    API_MAX_PAGE_LIMIT,
    SERVER_PAGE_HARD_CAP,
    PaginatedResult,
    normalize_page_bounds,
)

APP_DIR = Path(__file__).resolve().parents[1] / "app"

_PUBLIC_LIST_ROUTERS = (
    "arbitration.py",
    "boundary.py",
    "cognition.py",
    "coordination.py",
    "escalation.py",
    "governance.py",
    "observability.py",
    "session.py",
    "sop_intelligence.py",
    "supervisor.py",
    "tenant.py",
)


def test_server_side_pagination_hard_cap_is_enforced() -> None:
    assert normalize_page_bounds(limit=None, offset=7) == (
        SERVER_PAGE_HARD_CAP,
        7,
    )
    assert normalize_page_bounds(limit=100, offset=0) == (100, 0)

    with pytest.raises(ValueError):
        normalize_page_bounds(limit=SERVER_PAGE_HARD_CAP + 1, offset=0)
    with pytest.raises(ValueError):
        normalize_page_bounds(limit=0, offset=0)
    with pytest.raises(ValueError):
        normalize_page_bounds(limit=10, offset=-1)


def test_paginated_result_exposes_items_total_limit_and_offset() -> None:
    page = PaginatedResult(items=("a", "b"), total=5, limit=2, offset=3)

    assert page.items == ("a", "b")
    assert page.total == 5
    assert page.limit == 2
    assert page.offset == 3


def test_public_list_routers_default_to_25_and_cap_at_100() -> None:
    routers_dir = APP_DIR / "api" / "v1" / "routers"
    for router_name in _PUBLIC_LIST_ROUTERS:
        source = (routers_dir / router_name).read_text(encoding="utf-8")
        assert str(API_DEFAULT_PAGE_LIMIT) in source, router_name
        assert str(API_MAX_PAGE_LIMIT) in source, router_name
        assert "le=500" not in source, router_name
        assert "default=100" not in source, router_name


def test_knowledge_vector_retrieval_is_sql_ranked_and_bounded() -> None:
    postgres_source = (
        APP_DIR / "knowledge" / "persistence" / "postgres.py"
    ).read_text(encoding="utf-8")
    runtime_source = (APP_DIR / "knowledge" / "runtime.py").read_text(
        encoding="utf-8"
    )

    assert "func.ts_rank" in postgres_source
    assert "func.plainto_tsquery" in postgres_source
    assert "fetch_row_page" in postgres_source
    assert "search_text=query" in runtime_source
    assert "limit=top_k" in runtime_source
