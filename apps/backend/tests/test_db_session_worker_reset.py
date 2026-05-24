from __future__ import annotations

import pytest

from app.db.session import dispose_engine, get_session_factory, reset_engine_state


@pytest.mark.asyncio
async def test_reset_engine_state_forgets_cached_session_factory() -> None:
    await dispose_engine()

    first = get_session_factory()
    reset_engine_state()
    second = get_session_factory()

    assert second is not first

    await dispose_engine()
