"""External coarsening of authority / auth errors (spec 1b #25).

In production the external body is generic (no reconnaissance detail such as
``header_authority_disabled`` vs ``verification_failed``); the precise internal
code + reason are logged server-side with the request correlation id so support
can still trace failures.
"""

from __future__ import annotations

import logging

from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

_GENERIC: dict[int, str] = {400: "bad_request", 401: "unauthorized", 403: "forbidden"}


def auth_error_response(
    *,
    status_code: int,
    internal_code: str,
    reason: str,
    coarsen: bool,
) -> JSONResponse:
    """Return the auth error response, coarsened when ``coarsen`` is true."""
    headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
    if coarsen:
        logger.warning(
            "auth_error_coarsened",
            extra={
                "internal_code": internal_code,
                "reason": reason,
                "status": status_code,
            },
        )
        return JSONResponse(
            status_code=status_code,
            content={"error": _GENERIC.get(status_code, "error")},
            headers=headers,
        )
    return JSONResponse(
        status_code=status_code,
        content={"error": internal_code, "reason": reason},
        headers=headers,
    )


__all__ = ["auth_error_response"]
