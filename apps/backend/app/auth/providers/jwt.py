"""``JWTProvider`` — RFC 7519 verification.

Verifies a Bearer JWT against a configured key + algorithm
allowlist and translates registered identity claims into a
:class:`VerifiedIdentity`. Powered by PyJWT.

Determinism contract
────────────────────
Same token + same provider state (key, algorithms, issuer
allowlist, audience, leeway, claim mapping) → byte-equal
:class:`VerifiedIdentity` (modulo :attr:`issued_at`, which is
stamped with the verification clock). For replay-determinism in
recorded sessions, callers may pin :attr:`issued_at` post-hoc; the
provider itself does NOT inject randomness.

Failure modes (all → :class:`AuthenticationError`)
──────────────────────────────────────────────────
* scheme not Bearer
* malformed token / signature failure
* expired token
* issuer not in allowlist (when configured)
* audience mismatch (when configured)
* unsupported algorithm (defence-in-depth on top of PyJWT's
  ``algorithms=`` allowlist)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar, Final, TypeAlias, cast

import jwt
from jwt import (
    InvalidAlgorithmError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidTokenError,
)

from app.auth.credentials import Credential
from app.auth.errors import AuthenticationError
from app.auth.identity import VerifiedIdentity


@dataclass(frozen=True, slots=True)
class ClaimMapping:
    """Maps JWT claim names to :class:`VerifiedIdentity` axes.

    Each field names the JWT claim whose value is copied into the
    corresponding :class:`VerifiedIdentity` axis. ``None`` disables
    extraction for that axis (the verified identity carries
    ``None`` / empty on that axis).

    The ``capabilities``, ``permissions_claim``, and ``roles_claim``
    claims accept:

    * a JSON array of strings (preferred — RFC 8693 ``scopes``
      style),
    * a single space-separated string (OAuth2 ``scope`` style).

    Either shape is normalised to a ``frozenset[str]``.
    """

    tenant_id: str | None = "tenant_id"
    principal_id: str | None = "sub"
    organization_id: str | None = "org_id"
    environment_id: str | None = "env"
    capabilities: str | None = "capabilities"
    permissions_claim: str | None = "permissions"
    roles_claim: str | None = "roles"


DEFAULT_CLAIM_MAPPING: Final[ClaimMapping] = ClaimMapping()

CapabilityMappingValue: TypeAlias = str | tuple[str, ...]

TENANT_DOMAIN_CAPABILITIES: Final[tuple[str, ...]] = (
    "tenant.channel.admin",
    "tenant.knowledge.write",
    "tenant.policy.write",
    "tenant.topology.write",
    "tenant.execution_governance.write",
)

TENANT_CONFIG_ADMIN_CAPABILITIES: Final[tuple[str, ...]] = (
    *TENANT_DOMAIN_CAPABILITIES,
    "tenant.config.write",
)

OPERATOR_BUNDLE_CAPABILITIES: Final[tuple[str, ...]] = (
    "operator",
    "tenant.operations.read",
    "tenant.supervisor.read",
    "tenant.observability.read",
)

PERMISSION_CAPABILITY_MAP: Final[dict[str, CapabilityMappingValue]] = {
    "operator:access": "operator",
    "read:tenant_data": "tenant_read",
    "write:tenant_data": "tenant_write",
    "write:tenant_config": TENANT_CONFIG_ADMIN_CAPABILITIES,
    "read:tenant_observability": "tenant.observability.read",
    "read:tenant_audit":         "tenant.audit.export",
    "read:tenant_operations": "tenant.operations.read",
    "read:tenant_supervisor": "tenant.supervisor.read",
    "read:tenant_governance": "tenant.governance.read",
    "read:tenant_cognition": "tenant.cognition.read",
    "approve:tenant_actions": "tenant.actions.approve",
    "write:tenant_training": "tenant.training.write",
}

ROLE_CAPABILITY_MAP: Final[dict[str, CapabilityMappingValue]] = {
    # The operator bundle is broad read-only operations access. It deliberately
    # excludes governance/cognition reads and action/training writes; those
    # remain explicit grants for compliance and separation of duties.
    "Operator": OPERATOR_BUNDLE_CAPABILITIES,
    "TenantAdmin": TENANT_CONFIG_ADMIN_CAPABILITIES,
    "TenantConfigAdmin": TENANT_CONFIG_ADMIN_CAPABILITIES,
    "TenantConfigWriter": "tenant.config.write",
    "TenantChannelAdmin": "tenant.channel.admin",
    "TenantKnowledgeWriter": "tenant.knowledge.write",
    "TenantPolicyWriter": "tenant.policy.write",
    "TenantTopologyWriter": "tenant.topology.write",
    "TenantExecGovWriter": "tenant.execution_governance.write",
    "TenantViewer": "tenant_read",
    # Separation of duties (S-03): the approve duty is a DISTINCT role so
    # it can be granted to a different principal than ``TenantAdmin``.
    "TenantApprover":  "tenant.config.approve",
    # Observability + audit domain roles (#26/#80).
    "TenantObserver":  "tenant.observability.read",
    "TenantAuditor":   "tenant.audit.export",
    "TenantOperationsViewer": "tenant.operations.read",
    "TenantSupervisor": "tenant.supervisor.read",
    "TenantGovernanceViewer": "tenant.governance.read",
    "TenantCognitionViewer": "tenant.cognition.read",
    "TenantActionApprover": "tenant.actions.approve",
    "TenantTrainingWriter": "tenant.training.write",
}


def _empty_decode_options() -> dict[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class _DecodeOptions:
    issuer: str | tuple[str, ...] | None = None
    audience: str | tuple[str, ...] | None = None
    leeway: float = 0.0
    options: dict[str, Any] = field(default_factory=_empty_decode_options)


class JWTProvider:
    """Verify JWT bearer tokens and emit :class:`VerifiedIdentity`."""

    _accepted_schemes: ClassVar[frozenset[str]] = frozenset({"bearer"})

    def __init__(
        self,
        *,
        name: str = "jwt",
        key: str | bytes,
        algorithms: tuple[str, ...],
        issuer: str | tuple[str, ...] | None = None,
        audience: str | tuple[str, ...] | None = None,
        leeway: float = 0.0,
        claim_mapping: ClaimMapping = DEFAULT_CLAIM_MAPPING,
        require_claims: tuple[str, ...] = (),
    ) -> None:
        if not algorithms:
            raise ValueError("JWTProvider requires a non-empty algorithms allowlist")
        self.name = name
        self._key = key
        self._algorithms = tuple(algorithms)
        self._claim_mapping = claim_mapping
        self._require_claims = tuple(require_claims)
        self._decode = _DecodeOptions(
            issuer=issuer,
            audience=audience,
            leeway=leeway,
        )

    async def verify(self, credential: Credential) -> VerifiedIdentity:
        if credential.scheme.lower() not in self._accepted_schemes:
            raise AuthenticationError(
                f"JWTProvider only accepts Bearer credentials "
                f"(got scheme={credential.scheme!r})"
            )
        try:
            claims = jwt.decode(
                credential.value,
                self._key,
                algorithms=list(self._algorithms),
                issuer=self._decode.issuer,
                audience=self._decode.audience,
                leeway=self._decode.leeway,
            )
        except InvalidAlgorithmError as err:
            raise AuthenticationError(f"unsupported algorithm: {err}") from err
        except InvalidIssuerError as err:
            raise AuthenticationError(f"issuer not allowed: {err}") from err
        except InvalidAudienceError as err:
            raise AuthenticationError(f"audience mismatch: {err}") from err
        except InvalidTokenError as err:
            raise AuthenticationError(f"invalid token: {err}") from err

        if not isinstance(claims, dict):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise AuthenticationError("JWT payload is not a JSON object")

        for required in self._require_claims:
            if required not in claims:
                raise AuthenticationError(f"required claim missing: {required!r}")

        identity_axes: dict[str, Any] = {}
        for axis, claim_name in (
            ("tenant_id", self._claim_mapping.tenant_id),
            ("principal_id", self._claim_mapping.principal_id),
            ("organization_id", self._claim_mapping.organization_id),
            ("environment_id", self._claim_mapping.environment_id),
        ):
            if claim_name is None:
                identity_axes[axis] = None
                continue
            value = claims.get(claim_name)
            if value is None:
                identity_axes[axis] = None
                continue
            if not isinstance(value, str):
                raise AuthenticationError(
                    f"claim {claim_name!r} must be a string "
                    f"(got {type(value).__name__})"
                )
            identity_axes[axis] = value

        exp = claims.get("exp")
        expires_at: datetime | None
        if isinstance(exp, (int, float)):
            expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
        else:
            expires_at = None

        capabilities = self._extract_capabilities(claims)

        return VerifiedIdentity(
            tenant_id=identity_axes["tenant_id"],
            principal_id=identity_axes["principal_id"],
            organization_id=identity_axes["organization_id"],
            environment_id=identity_axes["environment_id"],
            capabilities=capabilities,
            issuer=self.name,
            issued_at=datetime.now(timezone.utc),
            expires_at=expires_at,
            claims=dict(claims),
        )

    def _extract_capabilities(self, claims: dict[str, Any]) -> frozenset[str]:
        return extract_capabilities_from_claims(
            claims=claims,
            claim_mapping=self._claim_mapping,
        )


def extract_capabilities_from_claims(
    *,
    claims: dict[str, Any],
    claim_mapping: ClaimMapping,
) -> frozenset[str]:
    capabilities: list[str] = []
    for capability in _claim_values(
        claims=claims,
        claim_name=claim_mapping.capabilities,
        claim_label="capabilities",
    ):
        _append_unique(capabilities, capability)
    for permission in _claim_values(
        claims=claims,
        claim_name=claim_mapping.permissions_claim,
        claim_label="permissions",
    ):
        mapped = PERMISSION_CAPABILITY_MAP.get(permission)
        if mapped is not None:
            _append_capability_mapping(capabilities, mapped)
    for role in _claim_values(
        claims=claims,
        claim_name=claim_mapping.roles_claim,
        claim_label="roles",
    ):
        mapped = ROLE_CAPABILITY_MAP.get(role)
        if mapped is not None:
            _append_capability_mapping(capabilities, mapped)
    return frozenset(capabilities)


def _claim_values(
    *,
    claims: dict[str, Any],
    claim_name: str | None,
    claim_label: str,
) -> tuple[str, ...]:
    if claim_name is None:
        return ()
    raw = claims.get(claim_name)
    if raw is None:
        return ()
    if isinstance(raw, str):
        # OAuth2 ``scope`` style — space-separated.
        return tuple(token for token in raw.split() if token)
    if isinstance(raw, (list, tuple)):
        values: list[str] = []
        raw_items = cast(list[object] | tuple[object, ...], raw)
        for item in raw_items:
            if not isinstance(item, str):
                raise AuthenticationError(
                    f"{claim_label} claim {claim_name!r} must be "
                    f"a string or array of strings (got element "
                    f"of type {type(item).__name__})"
                )
            values.append(item)
        return tuple(values)
    raise AuthenticationError(
        f"{claim_label} claim {claim_name!r} must be a string or "
        f"array of strings (got {type(raw).__name__})"
    )


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _append_capability_mapping(
    values: list[str],
    mapped: CapabilityMappingValue,
) -> None:
    if isinstance(mapped, str):
        _append_unique(values, mapped)
        return
    for value in mapped:
        _append_unique(values, value)


__all__ = [
    "ClaimMapping",
    "DEFAULT_CLAIM_MAPPING",
    "JWTProvider",
    "PERMISSION_CAPABILITY_MAP",
    "ROLE_CAPABILITY_MAP",
    "extract_capabilities_from_claims",
]
