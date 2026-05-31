"""Server-side canonical webhook URL derivation (spec 1b #23).

A provider signature (e.g. Twilio's ``X-Twilio-Signature``) is computed over the
URL the provider POSTed to. That URL is OUR public URL — it must be derived from
server-trusted config (``PUBLIC_BASE_URL`` + the matched request path), never
from a client-supplied header an attacker controls.
"""

from __future__ import annotations


class CanonicalWebhookUrlError(ValueError):
    """Raised when the canonical URL cannot be derived (missing base URL)."""


def derive_canonical_webhook_url(
    *,
    public_base_url: str,
    request_path: str,
    query_string: str,
) -> str:
    base = public_base_url.strip().rstrip("/")
    if not base:
        raise CanonicalWebhookUrlError(
            "PUBLIC_BASE_URL must be configured to verify webhook signatures"
        )
    path = request_path if request_path.startswith("/") else f"/{request_path}"
    url = f"{base}{path}"
    if query_string:
        url = f"{url}?{query_string}"
    return url


__all__ = ["CanonicalWebhookUrlError", "derive_canonical_webhook_url"]
