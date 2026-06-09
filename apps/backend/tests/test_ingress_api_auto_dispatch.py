"""Spec #3 closure: the /ingress API entrypoint also immediately enqueues dispatch.

inv2 was proven for the WhatsApp and SES webhook paths; this covers the remaining
capture entrypoint (``TicketIngressService.process``). The /ingress text API serves
email and whatsapp; Shopify is ingested through its own webhook (not this entrypoint)
and rides the same channel-agnostic ``_best_effort_enqueue_captured_ingress_dispatch``
helper exercised by the WhatsApp/SES webhook enqueue tests.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

import pytest

from app.boundary.ingress_dispatch_outbox import IngressDispatchOutboxRecord
from app.boundary.persistence import InMemoryBoundaryPersistence
from app.services.ticket_ingress_service import TicketIngressService


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.parametrize("channel", ["email", "whatsapp"])
@pytest.mark.asyncio
async def test_ingress_api_process_immediately_enqueues_dispatch(channel: str) -> None:
    persistence = InMemoryBoundaryPersistence()
    enqueued: list[IngressDispatchOutboxRecord] = []
    service = TicketIngressService(
        persistence=persistence,
        session=cast(Any, _FakeSession()),
        ingress_dispatch_enqueue=enqueued.append,
    )

    result = await service.process(
        external_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"ingress-api-{channel}")),
        channel=channel,
        raw_content="my order has not shipped and i need help with a refund",
        language_code="en",
        expected_tenant_id="tenant-ingress-api",
    )

    assert result.ingress_id is not None
    assert len(enqueued) == 1
    assert str(enqueued[0].ingress_id) == result.ingress_id
    assert enqueued[0].channel == channel
