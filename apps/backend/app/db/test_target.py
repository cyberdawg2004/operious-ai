"""Fail-closed target validation for local PostgreSQL integration tests.

This is intentionally separate from runtime database configuration: it is a
test-boundary guard that prevents test fixtures and local integration commands
from opening a connection to a non-disposable target.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TypeVar
from urllib.parse import unquote

from sqlalchemy.engine import URL, make_url

_DEFAULT_UNIX_SOCKET_DIRS = frozenset({"/var/run/postgresql"})
_DEFAULT_CONTAINER_HOSTS = frozenset({"postgres"})
_TEST_DATABASE_NAME = re.compile(
    r"(?:^test(?:[_-]|$)|(?:^|[_-])test(?:[_-]|$)|_test$)",
    re.IGNORECASE,
)
_T = TypeVar("_T")


class LocalTestDatabaseTargetError(ValueError):
    """A sanitized explanation for a rejected integration-test target."""


@dataclass(frozen=True, slots=True)
class LocalPostgresTestTarget:
    """Validated non-secret target facts for reporting and connection setup."""

    host_kind: str
    port: int | None
    database_name: str

    @property
    def endpoint_label(self) -> str:
        if self.host_kind == "unix_socket":
            return "approved-unix-socket"
        return f"{self.host_kind}:{self.port or 5432}"


def validate_local_postgres_test_target(
    database_url: str,
    *,
    approved_container_hosts: Iterable[str] = _DEFAULT_CONTAINER_HOSTS,
    approved_unix_socket_dirs: Iterable[str] = _DEFAULT_UNIX_SOCKET_DIRS,
) -> LocalPostgresTestTarget:
    """Validate a local, explicit PostgreSQL database target before connect.

    The exception messages deliberately identify only the rejected target
    class; they never include credentials, a hostname, or a complete DSN.
    """

    if not database_url.strip():
        raise LocalTestDatabaseTargetError("test database URL is missing")
    try:
        url = make_url(database_url)
    except Exception as exc:
        raise LocalTestDatabaseTargetError(
            "test database URL is malformed"
        ) from exc
    if url.get_backend_name().casefold() != "postgresql":
        raise LocalTestDatabaseTargetError("test target must use PostgreSQL")

    database_name = _validated_database_name(url)
    host_kind, port = _validated_host(
        url,
        approved_container_hosts=approved_container_hosts,
        approved_unix_socket_dirs=approved_unix_socket_dirs,
    )
    return LocalPostgresTestTarget(
        host_kind=host_kind,
        port=port,
        database_name=database_name,
    )


def create_checked_test_resource(
    database_url: str,
    factory: Callable[[str], _T],
    *,
    approved_container_hosts: Iterable[str] = _DEFAULT_CONTAINER_HOSTS,
    approved_unix_socket_dirs: Iterable[str] = _DEFAULT_UNIX_SOCKET_DIRS,
) -> _T:
    """Validate first, then invoke a caller-supplied connection resource factory."""

    validate_local_postgres_test_target(
        database_url,
        approved_container_hosts=approved_container_hosts,
        approved_unix_socket_dirs=approved_unix_socket_dirs,
    )
    return factory(database_url)


def _validated_database_name(url: URL) -> str:
    raw_name = url.database
    if not isinstance(raw_name, str) or not raw_name:
        raise LocalTestDatabaseTargetError("test database name is missing")
    database_name = unquote(raw_name).casefold()
    if "/" in database_name or "\\" in database_name or not _TEST_DATABASE_NAME.search(database_name):
        raise LocalTestDatabaseTargetError(
            "database name is not explicitly test-designated"
        )
    return database_name


def _validated_host(
    url: URL,
    *,
    approved_container_hosts: Iterable[str],
    approved_unix_socket_dirs: Iterable[str],
) -> tuple[str, int | None]:
    host = _normalise_host(url.host)
    if host is None:
        socket_dir = _single_unix_socket_dir(url)
        approved_dirs = {str(value) for value in approved_unix_socket_dirs}
        if socket_dir not in approved_dirs:
            raise LocalTestDatabaseTargetError(
                "database host is missing or not an approved Unix socket"
            )
        return "unix_socket", None

    if host == "localhost":
        return "localhost", _validated_port(url.port)
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        approved_hosts = {
            _normalise_host(value) for value in approved_container_hosts
        }
        if host in approved_hosts:
            return "local-test-container", _validated_port(url.port)
        raise LocalTestDatabaseTargetError(
            "database host is not an approved local test target"
        )
    if not address.is_loopback:
        raise LocalTestDatabaseTargetError(
            "database host is not a loopback address"
        )
    return "loopback", _validated_port(url.port)


def _normalise_host(value: str | None) -> str | None:
    if value is None:
        return None
    host = value.strip().rstrip(".").casefold()
    return host or None


def _single_unix_socket_dir(url: URL) -> str | None:
    value = url.query.get("host")
    if isinstance(value, tuple):
        if len(value) != 1:
            return None
        value = value[0]
    if not isinstance(value, str):
        return None
    decoded = unquote(value)
    return decoded if decoded.startswith("/") else None


def _validated_port(port: int | None) -> int:
    if port is None:
        return 5432
    if not 1 <= port <= 65535:
        raise LocalTestDatabaseTargetError("database port is invalid")
    return port


__all__ = [
    "LocalPostgresTestTarget",
    "LocalTestDatabaseTargetError",
    "create_checked_test_resource",
    "validate_local_postgres_test_target",
]
