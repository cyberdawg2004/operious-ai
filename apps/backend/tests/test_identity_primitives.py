"""Constitutional regression tests for ``app.identity.primitives``.

Wedge A (Phase 1) pins the following invariants:

1. Each primitive is runtime-transparent (``NewType`` collapses to
   ``str``), so adopting them at substrate boundaries does not
   perturb byte-level replay or canonicalisation.
2. Every ``coerce_*`` helper strips surrounding whitespace.
3. Every ``coerce_*`` helper rejects non-string input with
   ``IdentityError``.
4. Every ``coerce_*`` helper rejects empty / whitespace-only input
   with ``IdentityError`` (no silent identity coercion to ``""``).
5. The identity substrate is a LEAF — no source file under
   ``app/identity/`` may import any sibling substrate. The check is
   performed by source inspection so that it remains valid regardless
   of which tests have already loaded which modules.
"""

from __future__ import annotations

import pathlib
from typing import Callable

import pytest

import app.identity as identity_pkg
from app.identity.primitives import (
    EnvironmentId,
    IdentityError,
    OrganizationId,
    PrincipalId,
    TenantId,
    coerce_environment_id,
    coerce_organization_id,
    coerce_principal_id,
    coerce_tenant_id,
)


COERCERS: tuple[tuple[Callable[[object], str], str], ...] = (
    (coerce_tenant_id, "tenant_id"),
    (coerce_principal_id, "principal_id"),
    (coerce_organization_id, "organization_id"),
    (coerce_environment_id, "environment_id"),
)


def test_primitives_are_runtime_strings() -> None:
    assert TenantId("acme") == "acme"
    assert PrincipalId("user-1") == "user-1"
    assert OrganizationId("org-7") == "org-7"
    assert EnvironmentId("prod") == "prod"


def test_primitives_are_str_at_runtime() -> None:
    assert isinstance(TenantId("acme"), str)
    assert isinstance(PrincipalId("user-1"), str)
    assert isinstance(OrganizationId("org-7"), str)
    assert isinstance(EnvironmentId("prod"), str)


def test_coerce_strips_surrounding_whitespace() -> None:
    assert coerce_tenant_id("  acme  ") == "acme"
    assert coerce_principal_id("\tuser-1\n") == "user-1"
    assert coerce_organization_id("  org-7") == "org-7"
    assert coerce_environment_id("prod\t") == "prod"


@pytest.mark.parametrize("coercer,name", COERCERS)
def test_coerce_rejects_non_string(
    coercer: Callable[[object], str], name: str
) -> None:
    with pytest.raises(IdentityError, match=name):
        coercer(123)


@pytest.mark.parametrize("coercer,name", COERCERS)
def test_coerce_rejects_none(
    coercer: Callable[[object], str], name: str
) -> None:
    with pytest.raises(IdentityError, match=name):
        coercer(None)


@pytest.mark.parametrize("coercer,name", COERCERS)
def test_coerce_rejects_empty(
    coercer: Callable[[object], str], name: str
) -> None:
    with pytest.raises(IdentityError, match=name):
        coercer("")


@pytest.mark.parametrize("coercer,name", COERCERS)
def test_coerce_rejects_whitespace_only(
    coercer: Callable[[object], str], name: str
) -> None:
    with pytest.raises(IdentityError, match=name):
        coercer("   \t\n")


def test_identity_error_is_value_error_subclass() -> None:
    """``IdentityError`` must remain a ``ValueError`` so callers that
    catch ``ValueError`` (boundary validators, Pydantic) still work.
    """
    assert issubclass(IdentityError, ValueError)


def test_identity_substrate_is_leaf() -> None:
    """Guard the leaf invariant by source inspection.

    Every ``.py`` file under ``app/identity/`` must not import from any
    sibling substrate. This protects future contributors from quietly
    inverting the dependency direction.
    """
    forbidden_prefixes = (
        "app.governance",
        "app.session",
        "app.hardening",
        "app.arbitration",
        "app.boundary",
        "app.coordination",
        "app.agents",
        "app.supervisor",
        "app.organizational_intelligence",
        "app.api",
        "app.services",
        "app.repositories",
        "app.db",
        "app.middleware",
        "app.observability",
        "app.dependencies",
        "app.core",
    )
    identity_init = identity_pkg.__file__
    assert identity_init is not None, "app.identity must be a package"
    identity_root = pathlib.Path(identity_init).parent
    for py_file in identity_root.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for forbidden in forbidden_prefixes:
            assert f"from {forbidden}" not in text, (
                f"{py_file} imports from forbidden sibling substrate "
                f"{forbidden}; identity substrate must remain a leaf"
            )
            assert f"import {forbidden}" not in text, (
                f"{py_file} imports forbidden sibling substrate "
                f"{forbidden}; identity substrate must remain a leaf"
            )


def test_public_api_surface_is_stable() -> None:
    """Pin the public surface so future contributors must consciously
    grow it rather than accreting symbols by accident.
    """
    expected = {
        "AuthorityContext",
        "AuthorityResolution",
        "AuthoritySource",
        "EnvironmentId",
        "IdentityError",
        "OrganizationId",
        "PrincipalId",
        "TenantId",
        "coerce_environment_id",
        "coerce_organization_id",
        "coerce_principal_id",
        "coerce_tenant_id",
        "get_request_authority",
        "project_optional_str",
        "reset_request_authority",
        "resolve_authority",
        "set_request_authority",
    }
    assert set(identity_pkg.__all__) == expected
