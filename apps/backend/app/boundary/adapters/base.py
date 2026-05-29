"""Adapter ABCs — translation contracts.

Two abstract contracts:

* `BaseIngressAdapter` — translates an `IngressPayload` from a
                          specific external system into a
                          canonical `BoundaryNormalizationResult`.
                          Adapters MAY raise
                          `BoundaryAuthenticationError` /
                          `BoundaryNormalizationError` to signal
                          input rejection; the substrate folds
                          those onto the result.

* `BaseEgressAdapter`  — translates an opaque caller-supplied
                          artifact into a canonical `EgressPayload`.

Adapters are **inspect-only translators**. They MUST NOT:

* invoke any other Operious substrate runtime,
* perform side-effecting I/O (no actual HTTP calls — they
  *describe* what to send),
* mutate the inputs they receive,
* share global mutable state.

Adapters MAY:

* read deterministic, declarative configuration (loaded at
  construction time),
* canonicalise / re-shape data,
* compute / verify cryptographic signatures from material in
  the payload itself,
* declare unsupported message-type subsets via
  `UNSUPPORTED_TYPE`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from app.boundary.enums import (
    BoundaryDirection,
    BoundarySourceType,
)
from app.boundary.models.normalization import (
    BoundaryNormalizationResult,
)
from app.boundary.models.payload import (
    EgressPayload,
    IngressPayload,
)
from app.boundary.models.source import BoundarySource


class BaseIngressAdapter(ABC):
    """Abstract base for ingress adapters."""

    name: str
    source_type: BoundarySourceType
    direction: BoundaryDirection = BoundaryDirection.INGRESS

    def __init__(
        self,
        *,
        name: str,
        source_type: BoundarySourceType,
    ) -> None:
        if not name:
            raise ValueError(
                "BaseIngressAdapter.name must be non-empty"
            )
        self.name = name
        self.source_type = source_type

    @abstractmethod
    def normalize(
        self,
        *,
        source: BoundarySource,
        payload: IngressPayload,
    ) -> BoundaryNormalizationResult:
        """Translate an inbound payload to a canonical result."""


class BaseEgressAdapter(ABC):
    """Abstract base for egress adapters."""

    name: str
    source_type: BoundarySourceType
    direction: BoundaryDirection = BoundaryDirection.EGRESS
    requires_governance_decision_id: ClassVar[bool] = True

    def __init__(
        self,
        *,
        name: str,
        source_type: BoundarySourceType,
    ) -> None:
        if not name:
            raise ValueError(
                "BaseEgressAdapter.name must be non-empty"
            )
        self.name = name
        self.source_type = source_type

    @abstractmethod
    def serialize(
        self,
        *,
        source: BoundarySource,
        artifact: object,
    ) -> EgressPayload:
        """Translate a runtime artifact to an outbound payload."""


__all__ = ["BaseIngressAdapter", "BaseEgressAdapter"]
