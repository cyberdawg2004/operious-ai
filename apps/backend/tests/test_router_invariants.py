"""Phase 3.2 / PR-D2 — router constitutional invariants.

Seven structural protections, each pinned at test-collection time
so every router PR (PR-D3..D8 and beyond) must satisfy them at
merge:

1. **Substrate leakage** — routers under ``app/api/v1/routers/``
   must NOT import from a sibling substrate runtime. Each router
   may import ONLY from:
   * its own substrate's public surface (``app.<substrate>.*``),
   * ``app.api.v1.schemas.<own-substrate>`` (its Pydantic schema),
   * ``app.dependencies.*`` (DI surface),
   * ``app.identity``, ``app.middleware.*``, ``app.auth.*``
     (cross-cutting infrastructure),
   * stdlib + FastAPI + Pydantic + SQLAlchemy.

   Any other ``app.*`` import is a substrate leak: it couples
   the HTTP surface of substrate A to the runtime of substrate
   B, which makes a future swap-of-backend a multi-router PR
   instead of a single-substrate PR.

2. **Cross-router imports** — modules in
   ``app/api/v1/routers/`` MUST NOT import from each other.
   The aggregator ``app/api/v1/__init__.py`` is the single legal
   composition point. Cross-router imports compose handlers in
   ways middleware cannot see and reviewers cannot enforce.

3. **Response-model drift** — every endpoint's ``response_model``
   MUST be a class imported from ``app.api.v1.schemas.*``.
   Returning raw substrate dataclasses (or dicts, or
   ``response_model=None``) is forbidden — the wire shape must
   be a versioned Pydantic schema with explicit
   ``from_record`` / ``from_domain`` projection.

4. **Authority bypass paths** — every handler in a tenant-scoped
   router file MUST take ``Depends(require_tenant_scope)`` (or
   the explicit admin escape ``request_tenant_scope_opt``,
   covered by allowlist). Routers exempted from tenant scoping
   (health, auth/me, future public/marketing) are pinned by
   ``_PUBLIC_ROUTER_FILES`` here.

5. **Repository shortcutting** — handlers MUST acquire a
   substrate repository via ``Depends(get_<substrate>_repository)``
   from ``app.dependencies.services``. Direct construction of a
   ``Postgres*Repository`` / ``InMemory*Repository`` inside a
   router file is forbidden.

6. **Middleware pinning** — ``app.main.create_app`` registers
   exactly the seven classes ``AuthorityContextMiddleware``,
   ``TrustedIngressMiddleware`` (conditional), ``RequestContextMiddleware``,
   ``RequestBodyLimitMiddleware``, ``CORSMiddleware`` (conditional),
   ``EdgeRateLimitMiddleware``, and ``TenantRateLimitMiddleware`` (spec 1b #39).
   The class catalogue
   is pinned here; adding a new middleware requires explicit
   doctrine review.

7. **DI surface pinning** — the public surface of
   ``app.dependencies.services`` is pinned. Adding / removing
   a factory requires explicit doctrine review.

The intent is constitutional rigidity: every shortcut becomes
future infrastructure debt, so we encode the prohibitions in
tests before the shortcuts can be taken.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

import pytest

_BACKEND_APP: Final[Path] = Path(__file__).parent.parent / "app"
_ROUTERS_DIR: Final[Path] = _BACKEND_APP / "api" / "v1" / "routers"
_SCHEMAS_DIR: Final[Path] = _BACKEND_APP / "api" / "v1" / "schemas"

# ─── Substrate vocabulary ────────────────────────────────────────────────

#: Every substrate runtime package under ``app.*``. Used to detect
#: cross-substrate imports inside router files.
_SUBSTRATE_PACKAGES: Final[frozenset[str]] = frozenset(
    {
        "arbitration",
        "boundary",
        "cognition",
        "coordination",
        "data_protection",
        "escalation",
        "governance",
        "hardening",
        "knowledge",
        "organizational_intelligence",
        "session",
        "sop_intelligence",
        "supervisor",
        "tenant",
    }
)

#: ``app.*`` packages that routers may import freely. These are
#: cross-cutting infrastructure, not sibling-substrate runtimes —
#: importing them doesn't leak substrate semantics.
_ROUTER_ALLOWED_APP_PACKAGES: Final[frozenset[str]] = frozenset(
    {
        "api",  # for response schemas
        "auth",  # authentication primitives (Credential, etc.)
        "core",  # config, redis, logging
        "dependencies",  # DI surface
        "identity",  # AuthorityContext typed primitives
        "middleware",  # request-state contracts
        "observability",  # logging / tracing helpers
        "services",  # health service (the only legacy service)
        "survivability",  # idempotency / problem-details helpers
    }
)


# ─── Routers exempt from tenant scoping ──────────────────────────────────

#: Each router file path (relative to ``app/api/v1/routers/``) listed
#: here is exempt from the require_tenant_scope dependency invariant.
#: Adding a router here requires explicit doctrine review.
_PUBLIC_ROUTER_FILES: Final[frozenset[str]] = frozenset(
    {
        "health.py",  # /health /live /ready — operational probes
        "auth.py",  # /me — self-identity (uses require_authority, not tenant)
    }
)


# ─── DI surface pinning ──────────────────────────────────────────────────

_EXPECTED_SERVICES_SURFACE: Final[frozenset[str]] = frozenset(
    {
        "get_audit_export_service",
        "get_arbitration_repository",
        "get_boundary_repository",
        "get_cognition_service",
        "get_conversation_service",
        "get_coordination_repository",
        "get_data_protection_service",
        "get_escalation_service",
        "get_governance_repository",
        "get_health_service",
        "get_knowledge_service",
        "get_operational_event_service",
        "get_operational_observability_service",
        "get_quarantine_service",
        "get_queue_operations_service",
        "get_quota_operations_service",
        "get_quota_runtime",
        "get_semantic_circuit_service",
        "get_session_read_service",
        "get_session_repository",
        "get_sop_intelligence_service",
        "get_supervisor_repository",
        "get_tenant_config_change_request_service",
        "get_tenant_configuration_service",
        "get_tenant_lifecycle_service",
    }
)


# ─── Middleware pinning ──────────────────────────────────────────────────

_EXPECTED_MIDDLEWARE_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "AuthorityContextMiddleware",
        "TrustedIngressMiddleware",
        "RequestContextMiddleware",
        "RequestBodyLimitMiddleware",
        "CORSMiddleware",
        # Spec 1b: per-IP pre-auth and per-tenant/principal post-auth rate
        # limiting (#39). Reviewed and pinned here so any future addition
        # requires the same explicit sign-off.
        "EdgeRateLimitMiddleware",
        "TenantRateLimitMiddleware",
    }
)


# ─── Helpers ─────────────────────────────────────────────────────────────


def _router_files() -> list[Path]:
    """Every concrete router module file (excludes ``__init__.py``)."""
    return sorted(p for p in _ROUTERS_DIR.glob("*.py") if p.name != "__init__.py")


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(tree: ast.Module) -> list[tuple[str, str | None]]:
    """Yield ``(module, alias)`` pairs for every ``import`` / ``from``."""
    pairs: list[tuple[str, str | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                pairs.append((module, alias.name))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                pairs.append((alias.name, None))
    return pairs


def _substrate_from_router_filename(name: str) -> str:
    """``governance.py`` → ``governance``; ``auth.py`` → ``auth``."""
    if name == "voice.py":
        return "boundary"
    return name.removesuffix(".py")


# ─── Invariant 1: substrate leakage ──────────────────────────────────────


@pytest.mark.parametrize(
    "router_file",
    _router_files(),
    ids=lambda p: p.name,
)
def test_router_imports_no_sibling_substrate(
    router_file: Path,
) -> None:
    """A router file may import from at most ONE substrate runtime:
    its own (matching the file name) — and only via the substrate's
    public package surface (``app.<substrate>``, plus
    ``app.<substrate>.persistence``, ``app.<substrate>.identity``,
    ``app.<substrate>.enums``, ``app.<substrate>.taxonomy``).
    """
    own_substrate = _substrate_from_router_filename(router_file.name)
    tree = _parse(router_file)
    offenders: list[str] = []
    for module, _ in _imports(tree):
        if not module.startswith("app."):
            continue
        parts = module.split(".")
        if len(parts) < 2:
            continue
        top = parts[1]
        # Allowed cross-cutting infrastructure packages.
        if top in _ROUTER_ALLOWED_APP_PACKAGES:
            continue
        # Substrate import — must be the router's own substrate.
        if top in _SUBSTRATE_PACKAGES:
            if top != own_substrate:
                offenders.append(module)
            continue
        # Any other app.* package is unexpected (db, repositories,
        # etc.). Allow ``app.db.base`` / ``app.db.repository`` (the
        # constitutional foundation) but flag everything else.
        if module.startswith("app.db.base") or module.startswith("app.db.repository"):
            continue
        offenders.append(module)
    assert not offenders, (
        f"{router_file.name} imports forbidden modules: {offenders}. "
        f"Routers may only import their own substrate "
        f"({own_substrate!r}) plus the cross-cutting infrastructure "
        f"packages {_ROUTER_ALLOWED_APP_PACKAGES}."
    )


def test_session_router_does_not_import_runtime() -> None:
    tree = _parse(_ROUTERS_DIR / "session.py")
    runtime_imports = [
        f"{module}.{name}" if name is not None else module
        for module, name in _imports(tree)
        if module == "app.session.runtime" or name == "SessionRuntime"
    ]
    assert runtime_imports == []


# ─── Invariant 2: cross-router imports ───────────────────────────────────


@pytest.mark.parametrize(
    "router_file",
    _router_files(),
    ids=lambda p: p.name,
)
def test_router_does_not_import_other_routers(
    router_file: Path,
) -> None:
    """No router may import another router.

    The aggregator ``app/api/v1/__init__.py`` is the single legal
    composition point. Cross-router imports compose handlers in
    ways middleware cannot see and reviewers cannot enforce.
    """
    tree = _parse(router_file)
    offenders: list[str] = []
    for module, _ in _imports(tree):
        if (
            module.startswith("app.api.v1.routers.")
            and module != f"app.api.v1.routers.{router_file.stem}"
        ):
            offenders.append(module)
    assert not offenders, (
        f"{router_file.name} imports other routers: {offenders}. "
        "Compose at app/api/v1/__init__.py only."
    )


# ─── Invariant 3: response-model discipline ──────────────────────────────


_DECORATOR_VERBS: Final[frozenset[str]] = frozenset(
    {
        "get",
        "post",
        "put",
        "patch",
        "delete",
        "head",
        "options",
    }
)


def _route_decorators(
    tree: ast.Module,
) -> list[tuple[ast.AsyncFunctionDef | ast.FunctionDef, ast.Call]]:
    """Yield ``(handler_fn, decorator_call)`` pairs for every
    ``@router.<verb>(...)``-style decorator in the module."""
    pairs: list[tuple[ast.AsyncFunctionDef | ast.FunctionDef, ast.Call]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            if isinstance(func, ast.Attribute) and func.attr in _DECORATOR_VERBS:
                pairs.append((node, dec))
    return pairs


@pytest.mark.parametrize(
    "router_file",
    _router_files(),
    ids=lambda p: p.name,
)
def test_router_response_model_imported_from_v1_schemas(
    router_file: Path,
) -> None:
    """Every ``@router.<verb>(...)`` decorator that sets
    ``response_model=`` MUST reference a class name that was
    imported from ``app.api.v1.schemas.*``. Returning raw substrate
    dataclasses, dicts, or ``response_model=None`` is forbidden —
    the wire shape must be a versioned Pydantic schema.

    Auth-only / health-only handlers without bodies (rare) are
    exempt because they typically use ``Response`` directly; the
    invariant only fires when a ``response_model`` kwarg is
    actually present.
    """
    tree = _parse(router_file)
    schema_names: set[str] = set()
    for module, alias in _imports(tree):
        if module.startswith("app.api.v1.schemas") and alias is not None:
            schema_names.add(alias)

    offenders: list[str] = []
    for handler, dec in _route_decorators(tree):
        for kw in dec.keywords:
            if kw.arg != "response_model":
                continue
            if isinstance(kw.value, ast.Name):
                name = kw.value.id
                if name not in schema_names:
                    offenders.append(
                        f"{handler.name}: response_model={name} "
                        "not imported from app.api.v1.schemas.*"
                    )
            elif isinstance(kw.value, ast.Constant) and kw.value.value is None:
                # Explicit ``response_model=None`` is forbidden.
                offenders.append(
                    f"{handler.name}: response_model=None forbidden "
                    "(wire shape must be a versioned Pydantic schema)"
                )
            else:
                offenders.append(
                    f"{handler.name}: response_model is not a "
                    "plain name reference (got "
                    f"{ast.dump(kw.value)}); response models must "
                    "be a single name imported from "
                    "app.api.v1.schemas.*"
                )
    assert not offenders, f"{router_file.name} response-model violations: {offenders}"


# ─── Invariant 4: authority bypass paths ─────────────────────────────────


def _handler_depends_on(
    handler: ast.AsyncFunctionDef | ast.FunctionDef,
    target_names: frozenset[str],
) -> bool:
    """Return True iff the handler has a parameter with a default
    of the form ``Depends(<one of target_names>)``."""
    args = handler.args
    defaults = list(args.defaults)
    kw_defaults = list(args.kw_defaults)
    for default in (*defaults, *kw_defaults):
        if default is None:
            continue
        if (
            isinstance(default, ast.Call)
            and isinstance(default.func, ast.Name)
            and default.func.id == "Depends"
            and default.args
            and isinstance(default.args[0], ast.Name)
            and default.args[0].id in target_names
        ):
            return True
    return False


_TENANT_SCOPE_DEPENDENCIES: Final[frozenset[str]] = frozenset(
    {
        "require_tenant_scope",
        "request_tenant_scope_opt",
    }
)


@pytest.mark.parametrize(
    "router_file",
    _router_files(),
    ids=lambda p: p.name,
)
def test_tenant_scoped_router_handlers_depend_on_tenant_scope(
    router_file: Path,
) -> None:
    """Every handler in a tenant-scoped router file MUST depend on
    either :func:`require_tenant_scope` (the default) or
    :func:`request_tenant_scope_opt` (the explicit admin escape).

    Public router files (``health.py``, ``auth.py``) are exempt
    via :data:`_PUBLIC_ROUTER_FILES`. Adding a new exemption
    requires touching this allowlist — visible at review time.
    """
    if router_file.name in _PUBLIC_ROUTER_FILES:
        pytest.skip(
            f"{router_file.name} is a constitutionally public "
            "router (see _PUBLIC_ROUTER_FILES)"
        )
    tree = _parse(router_file)
    offenders: list[str] = []
    for handler, _ in _route_decorators(tree):
        if not _handler_depends_on(handler, _TENANT_SCOPE_DEPENDENCIES):
            offenders.append(handler.name)
    assert not offenders, (
        f"{router_file.name} handlers missing tenant-scope "
        f"dependency: {offenders}. Every handler in a tenant-"
        "scoped router MUST take Depends(require_tenant_scope) "
        "or Depends(request_tenant_scope_opt)."
    )


# ─── Invariant 5: repository shortcutting ────────────────────────────────


_FORBIDDEN_REPO_CLASSES_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:Postgres|InMemory)\w*Repository\b|"
    r"\b(?:Postgres|InMemory)\w*Persistence\b"
)


@pytest.mark.parametrize(
    "router_file",
    _router_files(),
    ids=lambda p: p.name,
)
def test_router_does_not_construct_concrete_repository(
    router_file: Path,
) -> None:
    """Routers MUST acquire substrate repositories via
    ``Depends(get_<substrate>_repository)`` from
    :mod:`app.dependencies.services`. Direct import or instantiation
    of a ``Postgres*Repository`` / ``InMemory*Persistence`` class
    inside a router file is forbidden — that coupling defeats
    PR-B1's "swap-the-backend-at-the-composition-root" doctrine.
    """
    text = router_file.read_text(encoding="utf-8")
    matches = _FORBIDDEN_REPO_CLASSES_RE.findall(text)
    assert not matches, (
        f"{router_file.name} references concrete repository "
        f"classes {matches}. Routers must reach repositories "
        "via Depends(get_<substrate>_repository) only — never "
        "construct or import concrete backends."
    )


# ─── Invariant 6: middleware pinning ─────────────────────────────────────


def test_main_create_app_middleware_stack_is_pinned() -> None:
    """:func:`app.main.create_app` may register only the five
    constitutional middleware classes. Adding / removing one
    requires explicit doctrine review and an update to
    :data:`_EXPECTED_MIDDLEWARE_CLASSES` AND a corresponding
    update to the middleware-ordering docstring in
    ``app/main.py``.
    """
    main_text = (_BACKEND_APP / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(main_text)
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "add_middleware"):
            continue
        if not node.args:
            continue
        first_arg = node.args[0]
        if isinstance(first_arg, ast.Name):
            found.add(first_arg.id)
    unexpected = found - _EXPECTED_MIDDLEWARE_CLASSES
    assert not unexpected, (
        f"app.main.create_app registers unexpected middleware: "
        f"{unexpected}. The pinned stack is "
        f"{sorted(_EXPECTED_MIDDLEWARE_CLASSES)}."
    )
    missing = _EXPECTED_MIDDLEWARE_CLASSES - found
    assert not missing, (
        f"app.main.create_app no longer registers: {missing}. "
        "Removing constitutional middleware requires doctrine "
        "review."
    )


# ─── Invariant 7: DI surface pinning ─────────────────────────────────────


def test_dependencies_services_public_surface_is_pinned() -> None:
    """Adding or removing a factory in :mod:`app.dependencies.services`
    requires explicit doctrine review and a corresponding update to
    :data:`_EXPECTED_SERVICES_SURFACE` here.
    """
    from app.dependencies import services as mod

    assert set(mod.__all__) == _EXPECTED_SERVICES_SURFACE, (
        "app.dependencies.services public surface drifted from "
        f"the pinned set. Expected {sorted(_EXPECTED_SERVICES_SURFACE)}, "
        f"got {sorted(mod.__all__)}."
    )


# ─── Schema-package hygiene ──────────────────────────────────────────────


def test_schemas_directory_contains_only_pydantic_modules() -> None:
    """Every module under ``app/api/v1/schemas/`` (except ``__init__.py``)
    MUST import :class:`pydantic.BaseModel`. This prevents the
    schemas directory from accidentally accumulating non-schema
    helpers (which would then become a back door for response-model
    drift)."""
    if not _SCHEMAS_DIR.exists():
        pytest.skip("schemas directory does not exist yet")
    offenders: list[str] = []
    for path in sorted(_SCHEMAS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "from pydantic" not in text and "import pydantic" not in text:
            offenders.append(path.name)
    assert not offenders, (
        f"schemas/ contains non-Pydantic modules: {offenders}. "
        "Schemas must import from pydantic."
    )
