"""Spec 1b — voice provider signature uses server-derived URL (#23)."""

from __future__ import annotations

from types import SimpleNamespace

from app.api.v1.routers.voice import _verify_voice_provider_signature
from app.core.twilio_signature import (
    TWILIO_CANONICAL_URL_HEADER,
    TWILIO_SIGNATURE_HEADER,
    compute_twilio_signature,
)

_PATH = "/api/v1/voice/sess-1/stream"


def _ws(headers: dict[str, str], *, path: str = _PATH, query: bytes = b""):
    return SimpleNamespace(headers=headers, scope={"path": path, "query_string": query})


def test_voice_signature_uses_server_url_ignores_header() -> None:
    auth = "provtok"
    server_url = f"https://api.operious.com{_PATH}"
    sig = compute_twilio_signature(auth_token=auth, url=server_url, params=None)
    ws = _ws({TWILIO_SIGNATURE_HEADER: sig, TWILIO_CANONICAL_URL_HEADER: "https://evil/x"})
    assert _verify_voice_provider_signature(
        websocket=ws, auth_token=auth,
        public_base_url="https://api.operious.com", trust_url_header=False,
    ) is True


def test_voice_signature_over_forged_url_rejected() -> None:
    auth = "provtok"
    forged = "https://evil/x"
    sig = compute_twilio_signature(auth_token=auth, url=forged, params=None)
    ws = _ws({TWILIO_SIGNATURE_HEADER: sig, TWILIO_CANONICAL_URL_HEADER: forged})
    assert _verify_voice_provider_signature(
        websocket=ws, auth_token=auth,
        public_base_url="https://api.operious.com", trust_url_header=False,
    ) is False


def test_voice_trust_header_flag_uses_client_header() -> None:
    auth = "provtok"
    forged = "https://evil/x"
    sig = compute_twilio_signature(auth_token=auth, url=forged, params=None)
    ws = _ws({TWILIO_SIGNATURE_HEADER: sig, TWILIO_CANONICAL_URL_HEADER: forged})
    assert _verify_voice_provider_signature(
        websocket=ws, auth_token=auth,
        public_base_url="", trust_url_header=True,
    ) is True


def test_voice_missing_base_url_fails_closed() -> None:
    auth = "provtok"
    server_url = f"https://api.operious.com{_PATH}"
    sig = compute_twilio_signature(auth_token=auth, url=server_url, params=None)
    ws = _ws({TWILIO_SIGNATURE_HEADER: sig})
    assert _verify_voice_provider_signature(
        websocket=ws, auth_token=auth,
        public_base_url="", trust_url_header=False,
    ) is False
