"""Spec 1b — server-side canonical webhook URL derivation (#23)."""

from __future__ import annotations

import pytest

from app.core.webhook_url import CanonicalWebhookUrlError, derive_canonical_webhook_url


def test_builds_from_public_base_url_and_path() -> None:
    url = derive_canonical_webhook_url(
        public_base_url="https://api.operious.com",
        request_path="/api/v1/webhooks/twilio/voice",
        query_string="",
    )
    assert url == "https://api.operious.com/api/v1/webhooks/twilio/voice"


def test_appends_query_when_present() -> None:
    url = derive_canonical_webhook_url(
        public_base_url="https://api.operious.com",
        request_path="/hook",
        query_string="b=2&a=1",
    )
    assert url == "https://api.operious.com/hook?b=2&a=1"


def test_empty_base_url_raises() -> None:
    with pytest.raises(CanonicalWebhookUrlError):
        derive_canonical_webhook_url(
            public_base_url="", request_path="/hook", query_string=""
        )


def test_strips_trailing_slash_on_base() -> None:
    url = derive_canonical_webhook_url(
        public_base_url="https://api.operious.com/",
        request_path="/hook",
        query_string="",
    )
    assert url == "https://api.operious.com/hook"


def test_normalizes_missing_leading_slash_on_path() -> None:
    url = derive_canonical_webhook_url(
        public_base_url="https://api.operious.com",
        request_path="hook",
        query_string="",
    )
    assert url == "https://api.operious.com/hook"
