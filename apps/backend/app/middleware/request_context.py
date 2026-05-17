"""Request correlation middleware.

For every inbound request:

1. Use the incoming `X-Request-ID` header if present, else mint a fresh
   UUID4. Honouring an inbound header keeps the correlation chain
   intact when an upstream proxy (ingress, load balancer, frontend)
   already produced one.
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
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.observability.context import reset_request_id, set_request_id

REQUEST_ID_HEADER = "X-Request-ID"


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
        call_next: Callable,
    ) -> Response:
        request_id = (
            request.headers.get(self._header_name) or uuid.uuid4().hex
        )

        request.state.request_id = request_id
        token = set_request_id(request_id)
        try:
            response: Response = await call_next(request)
        finally:
            reset_request_id(token)

        response.headers[self._header_name] = request_id
        return response


__all__ = ["RequestContextMiddleware", "REQUEST_ID_HEADER"]
