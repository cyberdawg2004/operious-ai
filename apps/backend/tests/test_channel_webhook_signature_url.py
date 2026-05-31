"""Spec 1b — channel webhook Twilio signature uses server-derived URL (#23)."""

from __future__ import annotations

import os
from unittest.mock import patch

from app.boundary.adapters.channel_webhooks import _verify_twilio_signature
from app.boundary.models.payload import IngressPayload
from app.core.config import get_settings
from app.core.twilio_signature import (
    TWILIO_CANONICAL_URL_HEADER,
    TWILIO_SIGNATURE_HEADER,
    compute_twilio_signature,
)

_PATH = "/api/v1/ingress/channels/twilio/webhook"


def _verify(*, headers, body, path, env) -> bool:
    get_settings.cache_clear()
    try:
        with patch.dict(os.environ, env, clear=False):
            payload = IngressPayload(body=body, headers=headers, request_path=path)
            return _verify_twilio_signature(secret="tok", payload=payload)
    finally:
        get_settings.cache_clear()


def test_forged_header_url_is_ignored() -> None:
    body = {"From": "+15550001111", "Body": "hi"}
    server_url = f"https://api.operious.com{_PATH}"
    good_sig = compute_twilio_signature(auth_token="tok", url=server_url, params=body)
    headers = {
        TWILIO_SIGNATURE_HEADER: good_sig,
        TWILIO_CANONICAL_URL_HEADER: "https://evil.test/forged",
    }
    assert _verify(
        headers=headers, body=body, path=_PATH,
        env={"PUBLIC_BASE_URL": "https://api.operious.com", "ENVIRONMENT": "test",
             "WEBHOOK_TRUST_URL_HEADER": "false"},
    ) is True


def test_signature_over_forged_url_rejected() -> None:
    body = {"From": "+15550001111", "Body": "hi"}
    forged = "https://evil.test/forged"
    sig_over_forged = compute_twilio_signature(auth_token="tok", url=forged, params=body)
    headers = {
        TWILIO_SIGNATURE_HEADER: sig_over_forged,
        TWILIO_CANONICAL_URL_HEADER: forged,
    }
    assert _verify(
        headers=headers, body=body, path=_PATH,
        env={"PUBLIC_BASE_URL": "https://api.operious.com", "ENVIRONMENT": "test",
             "WEBHOOK_TRUST_URL_HEADER": "false"},
    ) is False


def test_trust_header_flag_uses_client_header() -> None:
    body = {"From": "+15550001111", "Body": "hi"}
    forged = "https://evil.test/forged"
    sig = compute_twilio_signature(auth_token="tok", url=forged, params=body)
    headers = {TWILIO_SIGNATURE_HEADER: sig, TWILIO_CANONICAL_URL_HEADER: forged}
    assert _verify(
        headers=headers, body=body, path="/whatever",
        env={"WEBHOOK_TRUST_URL_HEADER": "true", "ENVIRONMENT": "test"},
    ) is True


def test_missing_base_url_fails_closed() -> None:
    body = {"From": "+1", "Body": "x"}
    server_url = f"https://api.operious.com{_PATH}"
    sig = compute_twilio_signature(auth_token="tok", url=server_url, params=body)
    headers = {TWILIO_SIGNATURE_HEADER: sig}
    assert _verify(
        headers=headers, body=body, path=_PATH,
        env={"PUBLIC_BASE_URL": "", "ENVIRONMENT": "test",
             "WEBHOOK_TRUST_URL_HEADER": "false"},
    ) is False
