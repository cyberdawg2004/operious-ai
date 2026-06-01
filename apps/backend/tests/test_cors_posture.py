"""Spec 1b — CORS middleware respects configured posture (#16)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from app.core.config import get_settings
from app.main import create_app


def _cors_kwargs(env: dict[str, str]) -> dict:
    get_settings.cache_clear()
    try:
        base = {"ENVIRONMENT": "test", "CORS_ALLOW_ORIGINS": "https://app.operious.com"}
        with patch.dict(os.environ, {**base, **env}):
            app = create_app()
        for m in app.user_middleware:
            if m.cls.__name__ == "CORSMiddleware":
                return m.kwargs
        raise AssertionError("CORSMiddleware not registered")
    finally:
        get_settings.cache_clear()


def test_credentials_respected_when_true() -> None:
    assert _cors_kwargs({"CORS_ALLOW_CREDENTIALS": "true"})["allow_credentials"] is True


def test_credentials_respected_when_false() -> None:
    assert _cors_kwargs({"CORS_ALLOW_CREDENTIALS": "false"})["allow_credentials"] is False


def test_methods_come_from_config() -> None:
    kwargs = _cors_kwargs({"CORS_ALLOW_METHODS": "GET,POST,OPTIONS"})
    assert kwargs["allow_methods"] == ["GET", "POST", "OPTIONS"]


def test_wildcard_origin_rejected() -> None:
    get_settings.cache_clear()
    try:
        with patch.dict(os.environ, {"ENVIRONMENT": "test", "CORS_ALLOW_ORIGINS": "*"}):
            with pytest.raises(ValueError):
                create_app()
    finally:
        get_settings.cache_clear()
