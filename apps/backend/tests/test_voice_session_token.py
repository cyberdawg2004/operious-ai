"""Signed voice session token (S-04).

The voice WebSocket previously trusted a plaintext ``?tenant=`` query
parameter, so anyone could open a stream attributed to any tenant. The
tenant identity now comes from a short-lived HMAC-signed token that
binds tenant + session + expiry; a forged or replayed-across-session
token is rejected.
"""

from __future__ import annotations

import pytest

from app.boundary.voice.session_token import (
    VoiceSessionTokenError,
    mint_voice_session_token,
    verify_voice_session_token,
)

_SECRET = "voice-session-secret-material-at-least-32b"


def test_mint_then_verify_roundtrip_returns_tenant() -> None:
    token = mint_voice_session_token(
        secret=_SECRET,
        tenant_id="tenant-a",
        session_id="session-1",
        expires_at=1000,
    )
    tenant = verify_voice_session_token(
        secret=_SECRET,
        token=token,
        session_id="session-1",
        now=999,
    )
    assert tenant == "tenant-a"


def test_expired_token_rejected() -> None:
    token = mint_voice_session_token(
        secret=_SECRET,
        tenant_id="tenant-a",
        session_id="session-1",
        expires_at=1000,
    )
    with pytest.raises(VoiceSessionTokenError):
        verify_voice_session_token(
            secret=_SECRET, token=token, session_id="session-1", now=1000
        )


def test_token_bound_to_session_cannot_be_replayed() -> None:
    token = mint_voice_session_token(
        secret=_SECRET,
        tenant_id="tenant-a",
        session_id="session-1",
        expires_at=1000,
    )
    with pytest.raises(VoiceSessionTokenError):
        verify_voice_session_token(
            secret=_SECRET, token=token, session_id="session-2", now=999
        )


def test_tampered_signature_rejected() -> None:
    token = mint_voice_session_token(
        secret=_SECRET,
        tenant_id="tenant-a",
        session_id="session-1",
        expires_at=1000,
    )
    # Flip the tenant segment but keep the original signature.
    parts = token.split(".")
    forged = mint_voice_session_token(
        secret="different-secret-entirely-32-bytes-long",
        tenant_id="tenant-victim",
        session_id="session-1",
        expires_at=1000,
    ).split(".")
    tampered = ".".join([parts[0], forged[1], parts[2], parts[3], parts[4]])
    with pytest.raises(VoiceSessionTokenError):
        verify_voice_session_token(
            secret=_SECRET, token=tampered, session_id="session-1", now=999
        )


def test_wrong_secret_rejected() -> None:
    token = mint_voice_session_token(
        secret=_SECRET,
        tenant_id="tenant-a",
        session_id="session-1",
        expires_at=1000,
    )
    with pytest.raises(VoiceSessionTokenError):
        verify_voice_session_token(
            secret="not-the-secret-but-also-32-bytes-padxx",
            token=token,
            session_id="session-1",
            now=999,
        )


def test_malformed_token_rejected() -> None:
    with pytest.raises(VoiceSessionTokenError):
        verify_voice_session_token(
            secret=_SECRET, token="garbage", session_id="s", now=0
        )


def test_empty_secret_refuses_to_mint() -> None:
    with pytest.raises(VoiceSessionTokenError):
        mint_voice_session_token(
            secret="",
            tenant_id="tenant-a",
            session_id="session-1",
            expires_at=1000,
        )
