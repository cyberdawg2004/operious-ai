"""M5: per-field size limits on ingress schemas.

raw_content / body > 100 KB → 422 Unprocessable Entity.
Normal-length content → accepted.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.v1.schemas.ingress.ingress import (
    TicketIngressRequest,
    _MAX_CONTENT_BYTES,
    _MAX_ID_BYTES,
)
from app.api.v1.schemas.ingress.batch import (
    BatchIngestItem,
    _MAX_BODY_BYTES,
    _MAX_ID_BYTES as _BATCH_MAX_ID_BYTES,
)

_NOW = "2026-07-03T12:00:00Z"


# ---------------------------------------------------------------------------
# TicketIngressRequest
# ---------------------------------------------------------------------------

def test_ticket_raw_content_over_limit_rejected() -> None:
    with pytest.raises(ValidationError):
        TicketIngressRequest(
            external_id="ext-1",
            channel="email",
            raw_content="x" * (_MAX_CONTENT_BYTES + 1),
        )


def test_ticket_raw_content_at_limit_accepted() -> None:
    req = TicketIngressRequest(
        external_id="ext-1",
        channel="email",
        raw_content="x" * _MAX_CONTENT_BYTES,
    )
    assert len(req.raw_content) == _MAX_CONTENT_BYTES


def test_ticket_normal_content_accepted() -> None:
    req = TicketIngressRequest(
        external_id="ext-1",
        channel="whatsapp",
        raw_content="My product broke please help",
    )
    assert req.raw_content == "My product broke please help"


def test_ticket_external_id_over_limit_rejected() -> None:
    with pytest.raises(ValidationError):
        TicketIngressRequest(
            external_id="x" * (_MAX_ID_BYTES + 1),
            channel="email",
            raw_content="ok",
        )


# ---------------------------------------------------------------------------
# BatchIngestItem
# ---------------------------------------------------------------------------

def _base_item(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "channel_type": "email",
        "source_id": "src-1",
        "external_message_id": "msg-1",
        "body": "normal body",
        "received_at": _NOW,
    }
    base.update(overrides)
    return base


def test_batch_body_over_limit_rejected() -> None:
    with pytest.raises(ValidationError):
        BatchIngestItem(**_base_item(body="x" * (_MAX_BODY_BYTES + 1)))


def test_batch_body_at_limit_accepted() -> None:
    item = BatchIngestItem(**_base_item(body="x" * _MAX_BODY_BYTES))
    assert len(item.body) == _MAX_BODY_BYTES


def test_batch_body_normal_accepted() -> None:
    item = BatchIngestItem(**_base_item(body="Hello, my order is missing."))
    assert item.body == "Hello, my order is missing."


def test_batch_external_id_over_limit_rejected() -> None:
    with pytest.raises(ValidationError):
        BatchIngestItem(**_base_item(external_message_id="x" * (_BATCH_MAX_ID_BYTES + 1)))
