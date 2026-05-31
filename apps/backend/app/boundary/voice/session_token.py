"""Short-lived HMAC-signed voice session tokens (S-04).

The voice media WebSocket cannot trust a client-supplied ``tenant``
query parameter — anyone could open a stream attributed to any tenant.
Instead the authenticated call-initiation flow mints a signed token
that binds ``tenant_id`` + ``session_id`` + ``expires_at``. The
WebSocket handshake verifies the token BEFORE ``accept()`` and derives
the tenant from the verified payload, never from the URL.

Token format (all ASCII, URL-safe, dot-delimited)::

    v1.<b64u(tenant_id)>.<b64u(session_id)>.<exp>.<hex_hmac_sha256>

where the HMAC covers ``v1.<b64u(tenant)>.<b64u(session)>.<exp>``.
Verification is constant-time (:func:`hmac.compare_digest`).
"""

from __future__ import annotations

import base64
import hmac
from hashlib import sha256
from typing import Final

_VERSION: Final[str] = "v1"


class VoiceSessionTokenError(Exception):
    """Raised when a voice session token is absent, malformed, expired,
    bound to a different session, or fails signature verification."""


def _b64u_encode(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip(
        "="
    )


def _b64u_decode(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding).decode("utf-8")


def _signature(*, secret: str, signing_input: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        signing_input.encode("utf-8"),
        sha256,
    ).hexdigest()


def mint_voice_session_token(
    *,
    secret: str,
    tenant_id: str,
    session_id: str,
    expires_at: int,
) -> str:
    """Mint a signed voice session token.

    ``expires_at`` is a Unix epoch second. Raises
    :class:`VoiceSessionTokenError` when no signing secret is configured
    (fail-closed: never mint an unsigned token).
    """

    if not secret:
        raise VoiceSessionTokenError("voice session token secret is not configured")
    if not tenant_id or not session_id:
        raise VoiceSessionTokenError("tenant_id and session_id are required")
    signing_input = (
        f"{_VERSION}.{_b64u_encode(tenant_id)}."
        f"{_b64u_encode(session_id)}.{int(expires_at)}"
    )
    signature = _signature(secret=secret, signing_input=signing_input)
    return f"{signing_input}.{signature}"


def verify_voice_session_token(
    *,
    secret: str,
    token: str,
    session_id: str,
    now: int,
) -> str:
    """Verify ``token`` and return the bound ``tenant_id``.

    Raises :class:`VoiceSessionTokenError` when the secret is missing,
    the token is malformed, the signature does not match, the token has
    expired (``now >= expires_at``), or the token was minted for a
    different ``session_id``.
    """

    if not secret:
        raise VoiceSessionTokenError("voice session token secret is not configured")
    parts = token.split(".")
    if len(parts) != 5:
        raise VoiceSessionTokenError("malformed voice session token")
    version, tenant_b64, session_b64, exp_raw, signature = parts
    if version != _VERSION:
        raise VoiceSessionTokenError("unsupported voice session token version")

    signing_input = f"{version}.{tenant_b64}.{session_b64}.{exp_raw}"
    expected = _signature(secret=secret, signing_input=signing_input)
    if not hmac.compare_digest(signature, expected):
        raise VoiceSessionTokenError("voice session token signature mismatch")

    try:
        tenant_id = _b64u_decode(tenant_b64)
        bound_session = _b64u_decode(session_b64)
        expires_at = int(exp_raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise VoiceSessionTokenError("malformed voice session token") from exc

    if not hmac.compare_digest(bound_session, session_id):
        raise VoiceSessionTokenError("voice session token session mismatch")
    if now >= expires_at:
        raise VoiceSessionTokenError("voice session token expired")
    return tenant_id


__all__ = [
    "VoiceSessionTokenError",
    "mint_voice_session_token",
    "verify_voice_session_token",
]
