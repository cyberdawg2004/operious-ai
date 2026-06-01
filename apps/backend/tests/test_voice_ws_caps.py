"""Spec 1b — voice WebSocket frame-rate cap primitive (#40)."""

from __future__ import annotations

import pytest

from app.api.v1.routers.voice import FrameRateExceeded, _enforce_frame_rate


def test_frame_rate_cap_trips_over_limit() -> None:
    window: list[float] = []
    _enforce_frame_rate(window, now=100.0, max_per_second=2)
    _enforce_frame_rate(window, now=100.1, max_per_second=2)
    with pytest.raises(FrameRateExceeded):
        _enforce_frame_rate(window, now=100.2, max_per_second=2)


def test_frame_rate_window_evicts_old_timestamps() -> None:
    window: list[float] = []
    _enforce_frame_rate(window, now=100.0, max_per_second=2)
    _enforce_frame_rate(window, now=100.4, max_per_second=2)
    # 1.1s after the first frame: both prior timestamps fall out of the window.
    _enforce_frame_rate(window, now=101.5, max_per_second=2)
    assert len(window) == 1


def test_frame_rate_allows_steady_under_limit() -> None:
    window: list[float] = []
    # 1 frame per second, cap 2/sec — never trips.
    for i in range(10):
        _enforce_frame_rate(window, now=float(i), max_per_second=2)
    assert len(window) <= 2
