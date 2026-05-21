"""Database URL normalization shared by runtime and Alembic.

This module is deliberately settings-agnostic. Callers pass the raw
SQLAlchemy URL and the operational connect timeout; the helper returns
the canonical engine inputs both runtime and migration engines must use.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.engine import make_url


@dataclass(frozen=True, slots=True)
class DatabaseEngineConfig:
    """Canonical SQLAlchemy engine inputs."""

    async_url: str
    sync_url: str
    connect_args: dict[str, object] = field(default_factory=dict)


def build_database_engine_config(
    database_url: str,
    *,
    connect_timeout: float,
) -> DatabaseEngineConfig:
    """Return canonical runtime and Alembic engine configuration."""

    url = make_url(database_url)
    connect_args: dict[str, object] = {}

    if url.drivername == "postgresql+asyncpg":
        connect_args["timeout"] = _connect_timeout_for_asyncpg(
            raw_query_value=url.query.get("connect_timeout"),
            default=connect_timeout,
        )

        sslmode = url.query.get("sslmode")
        if sslmode in {"require", "verify-ca", "verify-full"}:
            connect_args["ssl"] = True

        url = url.difference_update_query(
            ["sslmode", "channel_binding", "connect_timeout"]
        )

    async_url = url.render_as_string(hide_password=False)
    sync_url = async_url.replace("+asyncpg", "+psycopg2")
    return DatabaseEngineConfig(
        async_url=async_url,
        sync_url=sync_url,
        connect_args=connect_args,
    )


def _connect_timeout_for_asyncpg(
    *,
    raw_query_value: str | tuple[str, ...] | None,
    default: float,
) -> float:
    if raw_query_value is None:
        return default
    if isinstance(raw_query_value, tuple):
        if not raw_query_value:
            return default
        raw = raw_query_value[0]
    else:
        raw = raw_query_value
    return float(raw)


__all__ = ["DatabaseEngineConfig", "build_database_engine_config"]
