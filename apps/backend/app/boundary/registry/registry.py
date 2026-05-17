"""`BoundaryAdapterRegistry` — explicit, deterministic, dual-direction.

* Adapters register explicitly by ``register()`` (no
  auto-discovery, no entry points, no plugin scanning).
* Iteration order is the SORTED `adapter.name` order — never
  registration order.
* Duplicate-name registration is rejected at composition time
  with `BoundaryConfigurationError`.
* Ingress and egress adapters are kept in separate sub-registries
  (an `INGRESS` adapter and an `EGRESS` adapter MAY share a name;
  duplicate names within the same direction are rejected).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from app.boundary.enums import BoundaryDirection
from app.boundary.exceptions import (
    BoundaryConfigurationError,
)


class BoundaryAdapterRegistry:
    """Deterministic registry of ingress + egress adapters."""

    __slots__ = ("_ingress", "_egress")

    def __init__(
        self,
        adapters: Iterable[Any] | None = None,
    ) -> None:
        self._ingress: dict[str, Any] = {}
        self._egress: dict[str, Any] = {}
        if adapters is not None:
            for adapter in adapters:
                self.register(adapter)

    def register(self, adapter: Any) -> None:
        """Register a typed adapter.

        The adapter must declare a ``direction`` attribute resolving
        to a `BoundaryDirection` value, and a non-empty ``name``.
        """
        if not hasattr(adapter, "name") or not adapter.name:
            raise BoundaryConfigurationError(
                "adapter must declare a non-empty `name`"
            )
        if not hasattr(adapter, "direction"):
            raise BoundaryConfigurationError(
                f"adapter {adapter.name!r} missing `direction`"
            )
        direction = adapter.direction
        if not isinstance(direction, BoundaryDirection):
            raise BoundaryConfigurationError(
                f"adapter {adapter.name!r} declares non-typed "
                f"direction {direction!r}"
            )
        bucket = (
            self._ingress
            if direction is BoundaryDirection.INGRESS
            else self._egress
        )
        if adapter.name in bucket:
            raise BoundaryConfigurationError(
                f"duplicate {direction.value} adapter name: "
                f"{adapter.name!r}"
            )
        bucket[adapter.name] = adapter

    def has(
        self,
        name: str,
        *,
        direction: BoundaryDirection,
    ) -> bool:
        bucket = (
            self._ingress
            if direction is BoundaryDirection.INGRESS
            else self._egress
        )
        return name in bucket

    def get(
        self,
        name: str,
        *,
        direction: BoundaryDirection,
    ) -> Any:
        bucket = (
            self._ingress
            if direction is BoundaryDirection.INGRESS
            else self._egress
        )
        try:
            return bucket[name]
        except KeyError as exc:
            raise BoundaryConfigurationError(
                f"unknown {direction.value} adapter: {name!r}"
            ) from exc

    def names(
        self, *, direction: BoundaryDirection
    ) -> tuple[str, ...]:
        bucket = (
            self._ingress
            if direction is BoundaryDirection.INGRESS
            else self._egress
        )
        return tuple(sorted(bucket.keys()))

    def iterate(
        self, *, direction: BoundaryDirection
    ) -> Iterator[Any]:
        for name in self.names(direction=direction):
            bucket = (
                self._ingress
                if direction is BoundaryDirection.INGRESS
                else self._egress
            )
            yield bucket[name]

    def __len__(self) -> int:
        return len(self._ingress) + len(self._egress)


__all__ = ["BoundaryAdapterRegistry"]
