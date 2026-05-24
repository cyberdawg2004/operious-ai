"""Request correlation middleware.

For every inbound request:

1. Use the incoming `X-Request-ID` header if present, else derive a
   deterministic fallback from ASGI request scope inputs. Honouring an
   inbound header keeps the correlation chain intact when an upstream
   proxy (ingress, load balancer, frontend) already produced one.
2. Bind the id to a `ContextVar` so every `logging.getLogger(...)`
   call inside the request — including code in services, repositories,
   and background tasks spawned from the request — emits records
   carrying the id automatically.
3. Stash the id on `request.state` so handlers and downstream
   middleware that prefer explicit access don't need to import the
   context module.
4. Echo the id back on the response so callers can correlate their own
   logs without parsing the response body.

The middleware is intentionally tiny — it owns one concern and nothing
else. Future concerns get their own modules.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.deterministic_identity import derive_runtime_id
from app.observability.context import reset_request_id, set_request_id

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_NAMESPACE = uuid.UUID("9a0b8701-0001-4001-8001-000000000001")


def derive_request_id_from_scope(
    *,
    method: str,
    path: str,
    query_string: str,
    host: str | None,
    client: str | None,
    user_agent: str | None,
) -> str:
    """Derive a stable fallback request id from ASGI request inputs."""

    return derive_runtime_id(
        namespace=_REQUEST_ID_NAMESPACE,
        tenant_id=None,
        seed_components=(
            "http_request",
            method.upper(),
            path,
            query_string,
            host,
            client,
            user_agent,
        ),
    ).hex


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind a per-request correlation id to the runtime context."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        header_name: str = REQUEST_ID_HEADER,
    ) -> None:
        super().__init__(app)
        self._header_name = header_name

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = (
            request.headers.get(self._header_name)
            or derive_request_id_from_scope(
                method=request.method,
                path=request.url.path,
                query_string=request.url.query,
                host=request.headers.get("host"),
                client=(
                    request.client.host
                    if request.client is not None
                    else None
                ),
                user_agent=request.headers.get("user-agent"),
            )
        )

        request.state.request_id = request_id
        token = set_request_id(request_id)
        try:
            response: Response = await call_next(request)
        finally:
            reset_request_id(token)

        response.headers[self._header_name] = request_id
        return response


__all__ = [
    "RequestContextMiddleware",
    "REQUEST_ID_HEADER",
    "derive_request_id_from_scope",
]
