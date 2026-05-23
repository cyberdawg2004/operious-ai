"""Bounded SQL pagination helpers for repository read paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

API_DEFAULT_PAGE_LIMIT = 25
API_MAX_PAGE_LIMIT = 100
SERVER_PAGE_HARD_CAP = 500

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class PaginatedResult(Generic[T]):
    """Repository page result with explicit total and applied bounds."""

    items: tuple[T, ...]
    total: int
    limit: int
    offset: int


def normalize_page_bounds(
    *,
    limit: int | None,
    offset: int,
) -> tuple[int, int]:
    """Return bounded pagination values for SQL-native list reads."""

    if offset < 0:
        raise ValueError("offset must be >= 0")
    if limit is None:
        return SERVER_PAGE_HARD_CAP, offset
    if limit < 1:
        raise ValueError("limit must be >= 1")
    if limit > SERVER_PAGE_HARD_CAP:
        raise ValueError(
            f"limit must be <= {SERVER_PAGE_HARD_CAP}"
        )
    return limit, offset


async def count_matching_rows(
    session: AsyncSession,
    stmt: Select[Any],
) -> int:
    """Count rows matching ``stmt`` without inheriting its ordering."""

    count_stmt = select(func.count()).select_from(
        stmt.order_by(None).subquery()
    )
    return int((await session.execute(count_stmt)).scalar_one())


async def fetch_scalar_page(
    session: AsyncSession,
    stmt: Select[tuple[T]],
    *,
    limit: int | None,
    offset: int,
) -> PaginatedResult[T]:
    """Fetch a caller-bounded scalar page plus total count."""

    page_limit, page_offset = normalize_page_bounds(
        limit=limit,
        offset=offset,
    )
    total = await count_matching_rows(session, stmt)
    rows = tuple(
        (
            await session.execute(
                stmt.offset(page_offset).limit(page_limit)
            )
        )
        .scalars()
        .all()
    )
    return PaginatedResult(
        items=rows,
        total=total,
        limit=page_limit,
        offset=page_offset,
    )


async def fetch_row_page(
    session: AsyncSession,
    stmt: Select[Any],
    *,
    limit: int | None,
    offset: int,
) -> PaginatedResult[Any]:
    """Fetch a caller-bounded row-tuple page plus total count."""

    page_limit, page_offset = normalize_page_bounds(
        limit=limit,
        offset=offset,
    )
    total = await count_matching_rows(session, stmt)
    rows = tuple(
        (
            await session.execute(
                stmt.offset(page_offset).limit(page_limit)
            )
        ).all()
    )
    return PaginatedResult(
        items=rows,
        total=total,
        limit=page_limit,
        offset=page_offset,
    )


__all__ = [
    "API_DEFAULT_PAGE_LIMIT",
    "API_MAX_PAGE_LIMIT",
    "PaginatedResult",
    "SERVER_PAGE_HARD_CAP",
    "count_matching_rows",
    "fetch_row_page",
    "fetch_scalar_page",
    "normalize_page_bounds",
]
