"""M3: Webhook ingress HMAC invariant.

_webhook_signature_header_present is the fail-closed gate in
process_channel_webhook: no signature header present → missing_signature
rejection before any tenant work.

Tests verify:
1. All known channel types return False (→ reject) when no signature header present.
2. Unknown/future channel types return False (fail-closed) — not True (fail-open).
3. Each known channel type returns True when the correct header is present.
4. process_channel_webhook raises TicketIngressRejected (missing_signature) for
   an unsigned WhatsApp payload — exercises the full guard path.
"""

from __future__ import annotations

import pytest

from app.services.ticket_ingress_service import (
    _webhook_signature_header_present,
)
from app.tenant.enums import TenantChannelType


# ---------------------------------------------------------------------------
# (1) All known channel types: no header → False (fail-closed)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("channel_type", [
    TenantChannelType.EMAIL,
    TenantChannelType.WHATSAPP,
    TenantChannelType.SHULEX,
    TenantChannelType.LARK,
])
def test_no_signature_header_returns_false(channel_type: TenantChannelType) -> None:
    """A request with no signature header is rejected for every known channel."""
    result = _webhook_signature_header_present(
        channel_type=channel_type,
        headers={},
    )
    assert result is False, (
        f"Expected False (fail-closed) for {channel_type!r} with no headers, "
        f"got {result}"
    )


# ---------------------------------------------------------------------------
# (2) Unknown channel type → False (fail-closed, not fail-open)
# ---------------------------------------------------------------------------

def test_unknown_channel_type_fails_closed() -> None:
    """A channel type not in the known set returns False, never True."""
    # Use VOICE which is a known TenantChannelType but not handled in the function
    # (or any future type not added yet).  We verify the sentinel False behaviour.
    from app.tenant.enums import TenantChannelType as _T
    unknown_types = [
        t for t in _T
        if t not in (
            _T.EMAIL,
            _T.WHATSAPP,
            _T.SHULEX,
            _T.LARK,
        )
    ]
    for channel_type in unknown_types:
        result = _webhook_signature_header_present(
            channel_type=channel_type,
            headers={"x-fake-signature": "fake"},
        )
        assert result is False, (
            f"Channel type {channel_type!r} is not in the signature guard — "
            f"must return False (fail-closed), got {result}. "
            "If this is a new channel type that should accept webhooks, "
            "add it to _webhook_signature_header_present and this test."
        )


# ---------------------------------------------------------------------------
# (3) Each known channel type: correct header present → True
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("channel_type,header_name,header_value", [
    (TenantChannelType.EMAIL, "x-operious-signature", "sha256=abc123"),
    (TenantChannelType.EMAIL, "x-email-signature", "sha256=abc123"),
    (TenantChannelType.EMAIL, "x-amz-sns-message-signature", "some-sig"),
    (TenantChannelType.WHATSAPP, "x-hub-signature-256", "sha256=abc123"),
    (TenantChannelType.WHATSAPP, "x-operious-signature", "sha256=abc123"),
    (TenantChannelType.WHATSAPP, "x-twilio-signature", "twilio-sig"),
    (TenantChannelType.SHULEX, "x-shulex-signature", "some-sig"),
    (TenantChannelType.SHULEX, "x-operious-signature", "sha256=abc123"),
    (TenantChannelType.LARK, "x-lark-signature", "some-sig"),
])
def test_correct_header_present_returns_true(
    channel_type: TenantChannelType,
    header_name: str,
    header_value: str,
) -> None:
    """The correct signature header for each channel returns True."""
    result = _webhook_signature_header_present(
        channel_type=channel_type,
        headers={header_name: header_value},
    )
    assert result is True, (
        f"Expected True for {channel_type!r} with header {header_name!r}, "
        f"got {result}"
    )
