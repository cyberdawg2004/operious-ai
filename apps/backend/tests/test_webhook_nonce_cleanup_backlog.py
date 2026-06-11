"""Webhook nonce cleanup growth signal (#52)."""

from __future__ import annotations

from app.workers.webhook_nonce_tasks import cleanup_batch_is_backlogged


def test_saturated_batch_is_backlogged() -> None:
    # Hitting the batch limit means more expired rows remain -> growth signal.
    assert cleanup_batch_is_backlogged(deleted_count=1000, limit=1000) is True
    assert cleanup_batch_is_backlogged(deleted_count=1001, limit=1000) is True


def test_partial_batch_is_not_backlogged() -> None:
    assert cleanup_batch_is_backlogged(deleted_count=0, limit=1000) is False
    assert cleanup_batch_is_backlogged(deleted_count=999, limit=1000) is False
