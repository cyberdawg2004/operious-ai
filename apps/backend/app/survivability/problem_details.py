"""RFC 9457 Problem Details for HTTP APIs (P2-E).

Canonical structured-failure shape for production HTTP responses.
Members follow RFC 9457 §3.1:

  type      — URI reference identifying the problem type
              (``"about:blank"`` for unclassified problems)
  title     — short human-readable summary
  status    — HTTP status code (mirrors response status)
  detail    — human-readable explanation
  instance  — URI reference identifying this specific occurrence

Extension members may be added freely; consumers SHOULD ignore
unknown ones (RFC 9457 §3.2).

This module is a pure shape + a thin response helper. It does not
catch exceptions, does not register itself as a FastAPI handler, and
does not depend on any sibling substrate. Adoption (wiring it to
exception handlers, mapping internal exceptions to problem types) is
deferred to a future wedge.
"""

from __future__ import annotations

from typing import Any, Mapping

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field


PROBLEM_DETAILS_MEDIA_TYPE = "application/problem+json"


class ProblemDetails(BaseModel):
    """RFC 9457 Problem Details model.

    Use :func:`problem_details_response` to emit a ``JSONResponse``
    with the canonical media type.
    """

    model_config = ConfigDict(
        extra="allow",  # extension members are explicitly permitted
        frozen=True,
    )

    type: str = Field(
        default="about:blank",
        description="URI reference identifying the problem type",
    )
    title: str = Field(
        description="Short human-readable summary",
    )
    status: int = Field(
        description="HTTP status code (mirrors response status)",
        ge=100,
        le=599,
    )
    detail: str | None = Field(
        default=None,
        description="Human-readable explanation",
    )
    instance: str | None = Field(
        default=None,
        description="URI reference identifying this occurrence",
    )


def problem_details_response(
    problem: ProblemDetails,
    *,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Return a :class:`JSONResponse` carrying ``problem`` with the
    canonical ``application/problem+json`` media type.

    The HTTP status of the response mirrors ``problem.status``;
    callers MUST keep the two aligned (RFC 9457 §3.1.4).
    """
    payload: dict[str, Any] = problem.model_dump(exclude_none=True)
    return JSONResponse(
        content=payload,
        status_code=problem.status,
        media_type=PROBLEM_DETAILS_MEDIA_TYPE,
        headers=dict(headers or {}),
    )


__all__ = [
    "PROBLEM_DETAILS_MEDIA_TYPE",
    "ProblemDetails",
    "problem_details_response",
]
