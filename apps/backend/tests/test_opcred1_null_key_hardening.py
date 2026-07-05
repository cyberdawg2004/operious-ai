"""Break-controls for OPCRED1 null-key fallback hardening (security fix D).

D1 verdict: _active_pytest_case() reads os.environ["PYTEST_CURRENT_TEST"], which
pytest sets automatically. It cannot be set accidentally in prod by normal
env contamination — but the b"0"*32 fallback was still a latent risk: any
future caller that passes a sentinel or a test helper that forgets to set the
key would silently produce known-plaintext-encrypted data.

D2 fix: the b"0"*32 fallback is removed entirely. The only valid paths are:
  (a) key is set → real encryptor
  (b) key is unset → RuntimeError, always

D3 break-control: with TENANT_CREDENTIAL_MASTER_KEY unset → RuntimeError, never
null-key. With the key set → encryptor works normally.
"""

from __future__ import annotations

import os

import pytest

# We call the private function directly through the module to avoid the Celery
# task decorator interfering. We reload the module with a fresh settings context.


def _import_cognition_audit_encryptor():
    """Import the encryptor factory fresh with current settings."""
    from app.workers import agent_tasks
    return agent_tasks._cognition_audit_encryptor


# ---------------------------------------------------------------------------
# D3 (a): Key unset → RuntimeError, never falls back to null key
# ---------------------------------------------------------------------------

def test_missing_master_key_always_raises_never_null_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With TENANT_CREDENTIAL_MASTER_KEY unset, _cognition_audit_encryptor
    must raise RuntimeError — even when PYTEST_CURRENT_TEST is set (i.e.,
    inside a pytest run). The null-key fallback must be impossible.
    """
    monkeypatch.setenv("TENANT_CREDENTIAL_MASTER_KEY", "")
    # Confirm PYTEST_CURRENT_TEST is set (we ARE inside pytest right now)
    assert "PYTEST_CURRENT_TEST" in os.environ, (
        "This test must run under pytest — PYTEST_CURRENT_TEST should be set"
    )

    fn = _import_cognition_audit_encryptor()

    # Reload settings so the monkeypatched env takes effect
    from app.core.config import get_settings
    get_settings.cache_clear()

    try:
        with pytest.raises(RuntimeError, match="TENANT_CREDENTIAL_MASTER_KEY must be configured"):
            fn()
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# D3 (b): Key set → encryptor constructed without error
# ---------------------------------------------------------------------------

def test_with_master_key_set_encryptor_constructed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With TENANT_CREDENTIAL_MASTER_KEY set, the encryptor is returned normally."""
    # 64-hex-char string → 32 decoded bytes (256-bit) — test-only material
    monkeypatch.setenv("TENANT_CREDENTIAL_MASTER_KEY", "74" * 32)

    fn = _import_cognition_audit_encryptor()

    from app.core.config import get_settings
    get_settings.cache_clear()

    try:
        encryptor = fn()
        from app.tenant.credentials import TenantCredentialEncryptor
        assert isinstance(encryptor, TenantCredentialEncryptor)
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Confirm the null-key constant b"0"*32 is NOT present in the function source
# ---------------------------------------------------------------------------

def test_null_key_literal_removed_from_source() -> None:
    """Verify the b\"0\"*32 null-key literal is gone from _cognition_audit_encryptor."""
    import inspect
    from app.workers import agent_tasks
    source = inspect.getsource(agent_tasks._cognition_audit_encryptor)
    assert 'b"0" * 32' not in source and "b'0' * 32" not in source, (
        "Null-key fallback literal b\"0\"*32 found in _cognition_audit_encryptor — "
        "it must be removed"
    )
    assert "_active_pytest_case" not in source, (
        "_active_pytest_case() call found in _cognition_audit_encryptor — "
        "the pytest-detection branch must be removed"
    )
