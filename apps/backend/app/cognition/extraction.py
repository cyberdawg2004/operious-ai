"""Structured extraction schema (Phase B3).

Fixed common field set for v1 — tenant-configurable schemas are deferred
until a second vertical actually needs different fields (see the approved
B3 spec). Lives as its own leaf module (no imports from app.runtime /
app.agents) so app.runtime.resolution_runtime and app.agents.tools.* can
depend on it without introducing a circular import back into
app.cognition.diagnostic_runtime.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

logger = logging.getLogger(__name__)

ExtractionConfidence = Literal["high", "medium", "low"]
ExtractionSource = Literal["text", "document", "none"]

EXTRACTED_ORDER_FIELD_NAMES: tuple[str, ...] = (
    "order_id",
    "product_sku",
    "purchase_date",
    "seller",
    "amount",
    "currency",
)


class ExtractedField(BaseModel):
    """One extracted field. ``value is None`` is the ONLY absence state —

    never a placeholder string like "unknown_sku". confidence/source are
    only meaningful when a value is present; both are forced to their
    "absent" form otherwise so there is exactly one way to represent
    "not found", not a value-present-but-confidence-missing limbo state
    a caller could misread as data.
    """

    model_config = ConfigDict(extra="forbid")

    value: str | None = None
    confidence: ExtractionConfidence | None = None
    source: ExtractionSource = "none"

    @model_validator(mode="after")
    def _absence_is_total(self) -> "ExtractedField":
        if self.value is None:
            if self.confidence is not None:
                raise ValueError("confidence must be None when value is None")
            if self.source != "none":
                raise ValueError("source must be 'none' when value is None")
        else:
            if self.confidence is None:
                raise ValueError("confidence is required when value is present")
            if self.source == "none":
                raise ValueError("source must not be 'none' when value is present")
        return self


class ExtractedOrderFields(BaseModel):
    """Fixed v1 schema. Every field defaults to a fully-absent
    ExtractedField — ExtractedOrderFields() is the canonical "nothing
    extracted" sentinel, used whenever extraction wasn't attempted,
    failed to parse, or genuinely found nothing."""

    model_config = ConfigDict(extra="forbid")

    order_id: ExtractedField = ExtractedField()
    product_sku: ExtractedField = ExtractedField()
    purchase_date: ExtractedField = ExtractedField()
    seller: ExtractedField = ExtractedField()
    amount: ExtractedField = ExtractedField()
    currency: ExtractedField = ExtractedField()


def parse_extracted_fields(raw: Mapping[str, Any] | None) -> ExtractedOrderFields:
    """Fail-closed: any parse/validation error yields the all-absent
    sentinel, never raises into the diagnostic pipeline and never
    fabricates a value. A categorization-confident-but-extraction-
    malformed model response must not crash diagnostic reasoning — it
    degrades to "extraction unavailable", which the resolution gate
    already treats as "missing" for any field a recommended action
    depends on.
    """
    if raw is None:
        return ExtractedOrderFields()
    try:
        return ExtractedOrderFields.model_validate(raw)
    except ValidationError as exc:
        logger.warning(
            "extracted_fields_parse_failed",
            extra={"error": str(exc)[:500]},
        )
        return ExtractedOrderFields()


__all__ = [
    "EXTRACTED_ORDER_FIELD_NAMES",
    "ExtractedField",
    "ExtractedOrderFields",
    "ExtractionConfidence",
    "ExtractionSource",
    "parse_extracted_fields",
]
