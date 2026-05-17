"""`BoundaryAdapterRegistry` discipline."""

from __future__ import annotations

import pytest

from app.boundary.adapters.base import (
    BaseEgressAdapter,
    BaseIngressAdapter,
)
from app.boundary.enums import BoundaryDirection, BoundarySourceType
from app.boundary.exceptions import BoundaryConfigurationError
from app.boundary.models.normalization import (
    BoundaryNormalizationResult,
)
from app.boundary.models.payload import EgressPayload
from app.boundary.registry.registry import (
    BoundaryAdapterRegistry,
)


class _Ingress(BaseIngressAdapter):
    def __init__(self, *, name: str) -> None:
        super().__init__(
            name=name, source_type=BoundarySourceType.GENERIC
        )

    def normalize(self, *, source, payload):  # type: ignore[no-untyped-def]
        return BoundaryNormalizationResult(
            status=__import__(
                "app.boundary.enums", fromlist=["BoundaryNormalizationStatus"]
            ).BoundaryNormalizationStatus.OK
        )


class _Egress(BaseEgressAdapter):
    def __init__(self, *, name: str) -> None:
        super().__init__(
            name=name, source_type=BoundarySourceType.GENERIC
        )

    def serialize(self, *, source, artifact):  # type: ignore[no-untyped-def]
        return EgressPayload(body=artifact)


def test_registers_ingress_and_egress_independently() -> None:
    reg = BoundaryAdapterRegistry()
    reg.register(_Ingress(name="x"))
    reg.register(_Egress(name="x"))
    assert reg.has("x", direction=BoundaryDirection.INGRESS)
    assert reg.has("x", direction=BoundaryDirection.EGRESS)


def test_iteration_is_sorted_regardless_of_registration_order() -> None:
    reg = BoundaryAdapterRegistry(
        [
            _Ingress(name="zebra"),
            _Ingress(name="alpha"),
            _Ingress(name="mike"),
        ]
    )
    assert reg.names(direction=BoundaryDirection.INGRESS) == (
        "alpha",
        "mike",
        "zebra",
    )


def test_duplicate_name_within_direction_rejected() -> None:
    reg = BoundaryAdapterRegistry()
    reg.register(_Ingress(name="x"))
    with pytest.raises(BoundaryConfigurationError):
        reg.register(_Ingress(name="x"))


def test_unknown_direction_lookup_raises() -> None:
    reg = BoundaryAdapterRegistry()
    with pytest.raises(BoundaryConfigurationError):
        reg.get("missing", direction=BoundaryDirection.INGRESS)


def test_constructor_seed_uses_register() -> None:
    reg = BoundaryAdapterRegistry(
        [_Ingress(name="b"), _Ingress(name="a")]
    )
    assert reg.names(direction=BoundaryDirection.INGRESS) == (
        "a",
        "b",
    )


def test_register_rejects_objects_without_direction_or_name() -> None:
    reg = BoundaryAdapterRegistry()
    with pytest.raises(BoundaryConfigurationError):
        reg.register(object())
