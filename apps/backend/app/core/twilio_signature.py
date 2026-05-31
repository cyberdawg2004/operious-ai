"""Shared Twilio request-signature verification."""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Mapping
from typing import Any, Final

TWILIO_SIGNATURE_HEADER: Final[str] = "x-twilio-signature"
TWILIO_CANONICAL_URL_HEADER: Final[str] = "x-operious-webhook-url"


def compute_twilio_signature(
    *,
    auth_token: str,
    url: str,
    params: Mapping[str, Any] | None = None,
) -> str:
    """Return Twilio's base64 HMAC-SHA1 signature for ``url`` + params."""

    pieces = [url]
    if params is not None:
        for key in sorted(str(k) for k in params.keys()):
            value = params.get(key)
            pieces.append(key)
            pieces.append("" if value is None else str(value))
    return base64.b64encode(
        hmac.new(
            auth_token.encode("utf-8"),
            "".join(pieces).encode("utf-8"),
            hashlib.sha1,
        ).digest()
    ).decode("ascii")


def verify_twilio_signature(
    *,
    auth_token: str,
    url: str | None,
    params: Mapping[str, Any] | None,
    signature: str | None,
) -> bool:
    """Constant-time verification of Twilio's ``X-Twilio-Signature``."""

    token = auth_token.strip()
    if not token or not url or not signature:
        return False
    expected = compute_twilio_signature(
        auth_token=token,
        url=url,
        params=params,
    )
    return hmac.compare_digest(signature.strip(), expected)


def header_value(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


def verify_twilio_signature_from_headers(
    *,
    auth_token: str,
    headers: Mapping[str, str],
    params: Mapping[str, Any] | None,
) -> bool:
    """Verify using the canonical URL and signature headers."""

    return verify_twilio_signature(
        auth_token=auth_token,
        url=header_value(headers, TWILIO_CANONICAL_URL_HEADER),
        params=params,
        signature=header_value(headers, TWILIO_SIGNATURE_HEADER),
    )


__all__ = [
    "TWILIO_CANONICAL_URL_HEADER",
    "TWILIO_SIGNATURE_HEADER",
    "compute_twilio_signature",
    "header_value",
    "verify_twilio_signature",
    "verify_twilio_signature_from_headers",
]
