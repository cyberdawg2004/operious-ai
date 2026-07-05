#!/usr/bin/env python3
"""Webhook replay rejection drill.

Verifies the webhook ingress security properties end-to-end:
1. Sends a webhook POST with a valid HMAC-SHA256 signature and records the
   result (expected: 200 received or 202 accepted).
2. Sends the identical webhook a second time (same payload, same nonce / same
   deterministic message ID) and verifies the replay-rejection path triggers
   (expected: 200 with status=duplicate_delivery_acknowledged, or 409).
3. Sends a webhook with an invalid HMAC signature and verifies 401.
4. Reports PASS/FAIL per case and overall.

The drill uses the generic "whatsapp" channel type because it uses the
standard x-hub-signature-256 HMAC header that is the simplest to construct
outside of a real WhatsApp Business Account integration. It targets
/api/v1/boundary/channels/whatsapp/webhook (adjust --channel-type if needed).

Prerequisites:
- --tenant-id must be a tenant that has a whatsapp (or chosen) channel
  configured with --webhook-secret.
- --bearer-token is used for the queue-status readback; the webhook endpoint
  itself is unauthenticated (validated by HMAC).
"""

from __future__ import annotations

import argparse
import hashlib
import hmac as _hmac
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

DRILL_NAME = "webhook_replay"
HTTP_TIMEOUT_SECONDS = 30.0

# The ingress router is mounted at /boundary/translation in api/v1/__init__.py.
# The webhook endpoint in ingress.py is /channels/{channel_type}/webhook.
# Full path: /api/v1/boundary/translation/channels/{channel_type}/webhook
WEBHOOK_PATH_TEMPLATE = "/api/v1/boundary/translation/channels/{channel_type}/webhook"


# ---------------------------------------------------------------------------
# HMAC helpers
# ---------------------------------------------------------------------------


def _compute_hmac_sha256(secret: str, payload_bytes: bytes) -> str:
    """Return lowercase hex HMAC-SHA256 digest of payload_bytes."""
    return _hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()


def _signature_header_value(secret: str, payload_bytes: bytes) -> str:
    """Return the x-hub-signature-256 header value."""
    digest = _compute_hmac_sha256(secret, payload_bytes)
    return f"sha256={digest}"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _http_post(
    url: str,
    *,
    payload_bytes: bytes,
    headers: dict[str, str],
    timeout: float = HTTP_TIMEOUT_SECONDS,
) -> tuple[int, Any]:
    req = Request(url, data=payload_bytes, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            try:
                return resp.status, json.loads(body) if body else {}
            except json.JSONDecodeError:
                return resp.status, {"raw": body.decode("utf-8", errors="replace")}
    except HTTPError as exc:
        body = exc.read()
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, {"raw": body.decode("utf-8", errors="replace")}
    except (TimeoutError, URLError) as exc:
        reason = str(exc.reason) if isinstance(exc, URLError) else str(exc)
        raise RuntimeError(f"POST {url} failed: {reason}") from exc


def _build_webhook_url(base_url: str, channel_type: str) -> str:
    path = WEBHOOK_PATH_TEMPLATE.format(channel_type=channel_type)
    return base_url.rstrip("/") + path


# ---------------------------------------------------------------------------
# Drill cases
# ---------------------------------------------------------------------------


def _run_case_valid_first_delivery(
    *,
    url: str,
    payload_bytes: bytes,
    webhook_secret: str,
    message_id: str,
    channel_type: str,
) -> dict[str, Any]:
    """Case 1: valid signature, first delivery — expect 200/202 received."""
    sig = _signature_header_value(webhook_secret, payload_bytes)
    headers = {
        "Content-Type": "application/json",
        "x-hub-signature-256": sig,
        # WhatsApp includes a message ID that is used as the nonce.
        # We embed it in the body; the service extracts it from there.
    }
    status, body = _http_post(url, payload_bytes=payload_bytes, headers=headers)
    response_status = body.get("status") if isinstance(body, dict) else None
    passed = status in (200, 202) and response_status not in (
        "duplicate_delivery_acknowledged",
    )
    return {
        "case": "valid_first_delivery",
        "message_id": message_id,
        "status_code": status,
        "response_status": response_status,
        "body": body,
        "passed": passed,
        "note": "expected HTTP 200 or 202 with received/subscription_confirmed status",
    }


def _run_case_duplicate_delivery(
    *,
    url: str,
    payload_bytes: bytes,
    webhook_secret: str,
    message_id: str,
) -> dict[str, Any]:
    """Case 2: identical replay — expect 200 duplicate_delivery_acknowledged or 409."""
    sig = _signature_header_value(webhook_secret, payload_bytes)
    headers = {
        "Content-Type": "application/json",
        "x-hub-signature-256": sig,
    }
    status, body = _http_post(url, payload_bytes=payload_bytes, headers=headers)
    response_status = body.get("status") if isinstance(body, dict) else None
    # The service returns 200 with status=duplicate_delivery_acknowledged when
    # the nonce already exists. Some implementations return 409.
    passed = (status == 200 and response_status == "duplicate_delivery_acknowledged") or (
        status == 409
    )
    return {
        "case": "duplicate_delivery",
        "message_id": message_id,
        "status_code": status,
        "response_status": response_status,
        "body": body,
        "passed": passed,
        "note": "expected HTTP 200 duplicate_delivery_acknowledged or 409",
    }


def _run_case_invalid_signature(
    *,
    url: str,
    payload_bytes: bytes,
) -> dict[str, Any]:
    """Case 3: invalid HMAC signature — expect 401."""
    bad_sig = "sha256=" + "0" * 64
    headers = {
        "Content-Type": "application/json",
        "x-hub-signature-256": bad_sig,
    }
    status, body = _http_post(url, payload_bytes=payload_bytes, headers=headers)
    passed = status == 401
    return {
        "case": "invalid_signature",
        "status_code": status,
        "body": body,
        "passed": passed,
        "note": "expected HTTP 401",
    }


def _run_case_missing_signature(
    *,
    url: str,
    payload_bytes: bytes,
) -> dict[str, Any]:
    """Case 4: missing signature header — expect 401."""
    headers = {"Content-Type": "application/json"}
    status, body = _http_post(url, payload_bytes=payload_bytes, headers=headers)
    passed = status == 401
    return {
        "case": "missing_signature",
        "status_code": status,
        "body": body,
        "passed": passed,
        "note": "expected HTTP 401 (missing_signature rejection)",
    }


# ---------------------------------------------------------------------------
# Payload factory
# ---------------------------------------------------------------------------


def _build_whatsapp_payload(*, message_id: str, tenant_id: str) -> bytes:
    """Build a minimal WhatsApp webhook payload with a deterministic message_id.

    The service extracts the nonce from the message ID embedded in the
    WhatsApp payload structure (entry[0].changes[0].value.messages[0].id).
    """
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": f"drill-waba-{tenant_id}",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550000000",
                                "phone_number_id": f"drill-phone-{tenant_id}",
                            },
                            "messages": [
                                {
                                    "from": "15551234567",
                                    "id": message_id,
                                    "timestamp": "1700000000",
                                    "type": "text",
                                    "text": {
                                        "body": (
                                            "[DRILL] webhook replay drill test message "
                                            f"id={message_id}"
                                        )
                                    },
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _build_email_payload(*, message_id: str) -> bytes:
    """Build a minimal email webhook payload with a deterministic message_id."""
    payload = {
        "MessageId": message_id,
        "Source": "drill@example.com",
        "Destination": {"ToAddresses": ["support@operious.com"]},
        "mail": {
            "messageId": message_id,
            "source": "drill@example.com",
            "commonHeaders": {
                "subject": f"[DRILL] webhook replay drill {message_id}",
                "from": ["drill@example.com"],
            },
        },
        "content": f"[DRILL] replay drill test body. message_id={message_id}",
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------------------
# Drill orchestrator
# ---------------------------------------------------------------------------


def run_drill(
    *,
    base_url: str,
    tenant_id: str,
    webhook_secret: str,
    bearer_token: str | None,
    channel_type: str,
    message_id: str,
    first_delivery_delay_seconds: float,
) -> dict[str, Any]:
    t0 = time.monotonic()
    url = _build_webhook_url(base_url, channel_type)

    if channel_type == "whatsapp":
        payload_bytes = _build_whatsapp_payload(
            message_id=message_id, tenant_id=tenant_id
        )
    else:
        # Fall back to generic email-style payload for other channel types
        payload_bytes = _build_email_payload(message_id=message_id)

    cases: list[dict[str, Any]] = []

    # Case 1: valid first delivery
    case1 = _run_case_valid_first_delivery(
        url=url,
        payload_bytes=payload_bytes,
        webhook_secret=webhook_secret,
        message_id=message_id,
        channel_type=channel_type,
    )
    cases.append(case1)

    # Brief pause to allow nonce to be recorded before replay attempt
    if first_delivery_delay_seconds > 0:
        time.sleep(first_delivery_delay_seconds)

    # Case 2: duplicate delivery (same payload, same nonce)
    case2 = _run_case_duplicate_delivery(
        url=url,
        payload_bytes=payload_bytes,
        webhook_secret=webhook_secret,
        message_id=message_id,
    )
    cases.append(case2)

    # Case 3: invalid signature
    case3 = _run_case_invalid_signature(url=url, payload_bytes=payload_bytes)
    cases.append(case3)

    # Case 4: missing signature
    case4 = _run_case_missing_signature(url=url, payload_bytes=payload_bytes)
    cases.append(case4)

    all_passed = all(c["passed"] for c in cases)
    return {
        "drill": DRILL_NAME,
        "passed": all_passed,
        "elapsed_seconds": round(time.monotonic() - t0, 3),
        "url": url,
        "tenant_id": tenant_id,
        "channel_type": channel_type,
        "message_id": message_id,
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("OPERIOUS_BASE_URL", "https://operious-ai-imad.fly.dev"),
        help="Backend base URL (default: https://operious-ai-imad.fly.dev)",
    )
    parser.add_argument(
        "--tenant-id",
        default=os.environ.get("OPERIOUS_TENANT_ID", "anker-pilot"),
        help="Tenant ID whose channel is being exercised",
    )
    parser.add_argument(
        "--webhook-secret",
        default=os.environ.get("OPERIOUS_WEBHOOK_SECRET"),
        required=True,
        help="HMAC-SHA256 webhook secret configured for this tenant's channel",
    )
    parser.add_argument(
        "--bearer-token",
        default=os.environ.get("OPERIOUS_OPERATOR_TOKEN"),
        help="Auth0 operator bearer token (used for readback checks, not webhook auth)",
    )
    parser.add_argument(
        "--channel-type",
        default="whatsapp",
        choices=["whatsapp", "email"],
        help="Channel type to exercise (default: whatsapp)",
    )
    parser.add_argument(
        "--message-id",
        default=f"wamid.drill.{uuid.uuid4().hex}",
        help="Deterministic message ID used as the replay-protection nonce",
    )
    parser.add_argument(
        "--first-delivery-delay-seconds",
        type=float,
        default=1.0,
        help="Seconds to wait after first delivery before sending the duplicate",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.webhook_secret:
        print(
            "FAIL webhook_replay --webhook-secret is required (or set OPERIOUS_WEBHOOK_SECRET)",
            file=sys.stderr,
        )
        return 2

    result = run_drill(
        base_url=args.base_url,
        tenant_id=args.tenant_id,
        webhook_secret=args.webhook_secret,
        bearer_token=args.bearer_token,
        channel_type=args.channel_type,
        message_id=args.message_id,
        first_delivery_delay_seconds=args.first_delivery_delay_seconds,
    )
    status = "PASS" if result["passed"] else "FAIL"
    print(f"{status} {DRILL_NAME} {json.dumps(result, sort_keys=True, default=str)}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
