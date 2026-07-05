"""L7: Rate-limit disabled startup warning.

When RATE_LIMIT_ENABLED=false, create_app() must call logger.warning with
the 'rate_limit_disabled' message.  When rate limiting is on (default),
no such warning is called.
"""

from __future__ import annotations

import logging

import pytest


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    from app.core.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _run_create_app_capturing_warnings(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Run create_app() and return a list of warning message keys emitted."""
    warning_calls: list[str] = []
    app_logger = logging.getLogger("app.main")
    original_warning = app_logger.warning

    def _capture(msg: object, *args: object, **kwargs: object) -> None:
        warning_calls.append(str(msg))
        original_warning(msg, *args, **kwargs)

    app_logger.warning = _capture  # type: ignore[method-assign]
    try:
        from app.main import create_app
        create_app()
    finally:
        app_logger.warning = original_warning  # type: ignore[method-assign]
    return warning_calls


def test_rate_limit_disabled_emits_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RATE_LIMIT_ENABLED=false → logger.warning('rate_limit_disabled', ...) called."""
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    warning_calls = _run_create_app_capturing_warnings(monkeypatch)
    rate_limit_warnings = [m for m in warning_calls if "rate_limit_disabled" in m]
    assert rate_limit_warnings, (
        "Expected logger.warning('rate_limit_disabled', ...) when "
        "RATE_LIMIT_ENABLED=false, but it was not called. "
        f"All warning calls: {warning_calls}"
    )


def test_rate_limit_explicitly_enabled_no_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit RATE_LIMIT_ENABLED=true → no 'rate_limit_disabled' warning."""
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    warning_calls = _run_create_app_capturing_warnings(monkeypatch)
    rate_limit_warnings = [m for m in warning_calls if "rate_limit_disabled" in m]
    assert not rate_limit_warnings, (
        "Unexpected 'rate_limit_disabled' warning when RATE_LIMIT_ENABLED=true. "
        f"Warning calls: {warning_calls}"
    )
