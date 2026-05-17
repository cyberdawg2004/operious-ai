"""`SessionRegistry` deterministic-iteration discipline."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.session.enums import (
    SessionLifecyclePhase,
    SessionScope,
)
from app.session.exceptions import SessionConfigurationError
from app.session.identity import (
    derive_lineage_id,
    generate_session_id,
)
from app.session.models.identity import SessionIdentity
from app.session.models.lifecycle import SessionLifecycle
from app.session.models.lineage import SessionLineage
from app.session.models.session import OperationalSession
from app.session.registry.registry import SessionRegistry


def _build(*, revision: int = 1) -> OperationalSession:
    sid = generate_session_id()
    return OperationalSession(
        identity=SessionIdentity(
            session_id=sid,
            scope=SessionScope.TENANT,
            external_handle="h",
        ),
        opened_at=datetime.now(tz=timezone.utc),
        lifecycle=SessionLifecycle(
            phase=SessionLifecyclePhase.INITIATED,
            recorded_at=datetime.now(tz=timezone.utc),
        ),
        lineage=SessionLineage(
            lineage_id=derive_lineage_id(root_session_id=sid),
            session_id=sid,
            root_session_id=sid,
            parent_session_id=None,
            ancestor_session_ids=(),
            depth=0,
        ),
        sequence_head=-1,
        revision=revision,
    )


@pytest.mark.asyncio
async def test_register_rejects_duplicates() -> None:
    reg = SessionRegistry()
    s = _build()
    await reg.register(s)
    with pytest.raises(SessionConfigurationError):
        await reg.register(s)


@pytest.mark.asyncio
async def test_update_requires_existing() -> None:
    reg = SessionRegistry()
    with pytest.raises(SessionConfigurationError):
        await reg.update(_build())


@pytest.mark.asyncio
async def test_update_requires_revision_monotonic() -> None:
    reg = SessionRegistry()
    s = _build(revision=1)
    await reg.register(s)
    with pytest.raises(SessionConfigurationError):
        await reg.update(s)


@pytest.mark.asyncio
async def test_iteration_is_sorted_by_id() -> None:
    reg = SessionRegistry()
    a = _build()
    b = _build()
    c = _build()
    await reg.register(b)
    await reg.register(c)
    await reg.register(a)
    sorted_ids = sorted(
        [
            a.identity.session_id,
            b.identity.session_id,
            c.identity.session_id,
        ],
        key=str,
    )
    assert reg.ids() == tuple(sorted_ids)
