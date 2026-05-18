"""Readiness gate composition primitive (P2-E).

The existing :class:`app.services.health_service.HealthService` owns
the canonical readiness pipeline (PostgreSQL + Redis probes). This
module provides a substrate-local **composition primitive** for
declaring ADDITIONAL gates without touching the health service or
its probes.

Adoption pattern (deferred to a future wedge):

    registry = ReadinessRegistry()
    registry.register(_MyCustomGate())
    # health service composes the registry's gates into its
    # ``readiness()`` fan-out

Why typed protocol:

* A :class:`ReadinessGate` is identified by its ``name``; the
  registry rejects duplicate names at composition time so two
  uncoordinated registrations can't silently collide.
* The protocol is ``runtime_checkable`` so duck-typed gates work
  without an import-time inheritance dance.
"""

from __future__ import annotations

from typing import Iterable, Protocol, runtime_checkable


@runtime_checkable
class ReadinessGate(Protocol):
    """Contract every readiness gate satisfies.

    Implementations declare a stable ``name`` (used for trace
    attribution + duplicate-detection) and an async ``check`` method
    that returns ``True`` when the gate is healthy.
    """

    name: str

    async def check(self) -> bool: ...  # noqa: D401, E704


class ReadinessGateRegistrationError(ValueError):
    """Raised when a gate is registered with a name already in use."""


class ReadinessRegistry:
    """Ordered registry of readiness gates.

    Iteration order matches registration order so a downstream
    health service can produce deterministic trace output.
    """

    __slots__ = ("_gates",)

    def __init__(self) -> None:
        self._gates: list[ReadinessGate] = []

    def register(self, gate: ReadinessGate) -> None:
        if not gate.name:
            raise ReadinessGateRegistrationError(
                "ReadinessGate.name must be a non-empty string"
            )
        for existing in self._gates:
            if existing.name == gate.name:
                raise ReadinessGateRegistrationError(
                    f"readiness gate already registered: "
                    f"{gate.name!r}"
                )
        self._gates.append(gate)

    def gates(self) -> tuple[ReadinessGate, ...]:
        return tuple(self._gates)

    def __iter__(self) -> Iterable[ReadinessGate]:  # type: ignore[override]
        return iter(tuple(self._gates))

    def __len__(self) -> int:
        return len(self._gates)


__all__ = [
    "ReadinessGate",
    "ReadinessGateRegistrationError",
    "ReadinessRegistry",
]
