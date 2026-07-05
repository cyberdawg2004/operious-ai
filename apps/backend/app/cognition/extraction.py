"""Structured extraction schema.

The fixed e-commerce field set remains as the v1 default
(EXTRACTED_ORDER_FIELD_NAMES / ExtractedOrderFields) and is used when no
tenant-configured extraction_schema is present.  All new code should prefer
the tenant-configured ExtractionSchema when available.

Lives as a leaf module (no imports from app.runtime / app.agents) to avoid
circular imports.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

logger = logging.getLogger(__name__)

ExtractionConfidence = Literal["high", "medium", "low"]
ExtractionSource = Literal["text", "document", "none"]

# ---------------------------------------------------------------------------
# Legacy fixed field set — kept for backward compatibility with e-commerce
# tenants that have not yet migrated to ExtractionSchema.
# ---------------------------------------------------------------------------
EXTRACTED_ORDER_FIELD_NAMES: tuple[str, ...] = (
    "order_id",
    "product_sku",
    "purchase_date",
    "seller",
    "amount",
    "currency",
)

# ---------------------------------------------------------------------------
# Tenant-configurable extraction schema — domain-agnostic.
# ---------------------------------------------------------------------------

ExtractionFieldType = Literal["string", "date", "integer", "decimal", "enum"]


@dataclass(frozen=True, slots=True)
class ExtractionFieldSpec:
    """Specification for one tenant-configured extraction field."""

    name: str
    field_type: ExtractionFieldType = "string"
    display_name: str = ""
    description: str = ""
    required_for_auto: bool = False
    enum_values: tuple[str, ...] = field(default_factory=tuple)
    identity_field: bool = False

    def effective_display_name(self) -> str:
        return self.display_name if self.display_name else self.name.replace("_", " ")

    def prompt_annotation(self) -> str:
        """One-line annotation for the extraction prompt: type and description."""
        parts = [self.field_type]
        if self.field_type == "enum" and self.enum_values:
            parts.append(f"one of: {', '.join(self.enum_values)}")
        if self.description:
            parts.append(self.description)
        return "; ".join(parts)


@dataclass(frozen=True, slots=True)
class ExtractionSchema:
    """Ordered collection of per-tenant extraction field specs.

    ``fields`` preserves declaration order for prompt rendering.
    ``_by_name`` is the O(1) lookup index.
    """

    fields: tuple[ExtractionFieldSpec, ...]
    _by_name: dict[str, ExtractionFieldSpec] = field(
        default_factory=dict, compare=False, repr=False
    )

    def __post_init__(self) -> None:
        # build the lookup index after frozen dataclass construction
        object.__setattr__(
            self,
            "_by_name",
            {spec.name: spec for spec in self.fields},
        )

    def field_names(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self.fields)

    def required_for_auto(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self.fields if spec.required_for_auto)

    def identity_fields(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self.fields if spec.identity_field)

    def get(self, name: str) -> ExtractionFieldSpec | None:
        return self._by_name.get(name)

    def prompt_field_list(self) -> str:
        """Comma-separated list for the extraction instruction in the LLM prompt."""
        return ", ".join(spec.name for spec in self.fields)


def parse_extraction_schema(
    raw: object,
) -> ExtractionSchema | None:
    """Parse an extraction_schema object from a tenant policy record.

    Returns None (not an error) when ``raw`` is absent or None — the caller
    falls back to the legacy fixed field set.  Raises
    ExtractionSchemaParseError on structurally invalid input so the caller
    can fail-closed to REQUIRE_APPROVAL rather than silently proceeding.
    """
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ExtractionSchemaParseError("extraction_schema must be an object")
    raw_mapping: Mapping[str, object] = raw  # type: ignore[assignment]
    specs: list[ExtractionFieldSpec] = []
    for field_name, field_cfg in raw_mapping.items():
        if not field_name.strip():
            raise ExtractionSchemaParseError(
                "extraction_schema keys must be non-empty strings"
            )
        spec = _parse_field_spec(field_name.strip(), field_cfg)
        specs.append(spec)
    return ExtractionSchema(fields=tuple(specs))


def _parse_field_spec(name: str, raw: object) -> ExtractionFieldSpec:
    if not isinstance(raw, Mapping):
        raise ExtractionSchemaParseError(
            f"extraction_schema.{name} must be an object"
        )
    cfg: Mapping[str, object] = raw  # type: ignore[assignment]

    raw_type = cfg.get("type", "string")
    if raw_type not in ("string", "date", "integer", "decimal", "enum"):
        raise ExtractionSchemaParseError(
            f"extraction_schema.{name}.type must be one of "
            "'string', 'date', 'integer', 'decimal', 'enum'"
        )
    field_type: ExtractionFieldType = raw_type  # type: ignore[assignment]

    display_name = cfg.get("display_name", "")
    if not isinstance(display_name, str):
        raise ExtractionSchemaParseError(
            f"extraction_schema.{name}.display_name must be a string"
        )

    description = cfg.get("description", "")
    if not isinstance(description, str):
        raise ExtractionSchemaParseError(
            f"extraction_schema.{name}.description must be a string"
        )

    required_for_auto = cfg.get("required_for_auto", False)
    if not isinstance(required_for_auto, bool):
        raise ExtractionSchemaParseError(
            f"extraction_schema.{name}.required_for_auto must be a boolean"
        )

    identity_field = cfg.get("identity_field", False)
    if not isinstance(identity_field, bool):
        raise ExtractionSchemaParseError(
            f"extraction_schema.{name}.identity_field must be a boolean"
        )

    enum_values: tuple[str, ...] = ()
    if field_type == "enum":
        raw_values = cfg.get("values")
        if not isinstance(raw_values, Sequence) or isinstance(raw_values, str | bytes):
            raise ExtractionSchemaParseError(
                f"extraction_schema.{name}.values must be a non-empty list for enum type"
            )
        enum_values = tuple(
            v for v in raw_values if isinstance(v, str) and v.strip()
        )
        if not enum_values:
            raise ExtractionSchemaParseError(
                f"extraction_schema.{name}.values must contain at least one non-empty string"
            )

    return ExtractionFieldSpec(
        name=name,
        field_type=field_type,
        display_name=display_name,
        description=description,
        required_for_auto=required_for_auto,
        identity_field=identity_field,
        enum_values=enum_values,
    )


class ExtractionSchemaParseError(ValueError):
    """Raised when a tenant's extraction_schema entry is structurally invalid."""


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
    """Extraction result model.

    The six legacy e-commerce fields are declared explicitly for backward
    compatibility.  Tenant-configured verticals that declare additional
    fields in their extraction_schema will have those extra fields stored
    under ``model_extra`` (extra="allow").

    ``ExtractedOrderFields()`` is the canonical "nothing extracted" sentinel —
    used whenever extraction wasn't attempted, failed to parse, or genuinely
    found nothing.
    """

    model_config = ConfigDict(extra="allow")

    order_id: ExtractedField = ExtractedField()
    product_sku: ExtractedField = ExtractedField()
    purchase_date: ExtractedField = ExtractedField()
    seller: ExtractedField = ExtractedField()
    amount: ExtractedField = ExtractedField()
    currency: ExtractedField = ExtractedField()

    def get_field(self, name: str) -> ExtractedField | None:
        """Return the named field whether declared or in model_extra.

        Returns None when the field name is not present at all — distinct
        from a present-but-absent-value ExtractedField (which is present
        but has value=None).
        """
        # Declared legacy e-commerce fields — access via class-level model_fields
        if name in ExtractedOrderFields.model_fields:
            return getattr(self, name)  # type: ignore[return-value]
        # Extra (tenant-custom) fields live in model_extra
        extra = self.model_extra or {}
        raw = extra.get(name)
        if raw is None:
            return None
        if isinstance(raw, ExtractedField):
            return raw
        # model_extra stores dicts for nested models when validated; coerce lazily
        try:
            return ExtractedField.model_validate(raw)
        except Exception:
            return None


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


def parse_extracted_fields_against_schema(
    raw: Mapping[str, Any] | None,
    schema: ExtractionSchema,
) -> ExtractedOrderFields:
    """Parse and validate extracted fields against the tenant's declared schema.

    Fields the LLM returned that are NOT in the tenant's schema are silently
    dropped before parsing — the model must only return fields it was asked
    to extract. Fields that ARE in the schema but absent from the LLM output
    remain absent (all-absent ExtractedField). Fail-closed: any parse error
    after schema-gating yields the all-absent sentinel, same as
    parse_extracted_fields.

    This enforces the "no hallucinated fields" property per-tenant-schema.
    For legacy tenants (schema=None), callers fall back to parse_extracted_fields.
    """
    if raw is None:
        return ExtractedOrderFields()
    allowed = schema.field_names()
    gated: dict[str, Any] = {k: v for k, v in raw.items() if k in allowed}
    if len(gated) < len(raw):
        extra_keys = sorted(k for k in raw if k not in allowed)
        logger.warning(
            "extracted_fields_out_of_schema_dropped",
            extra={"dropped_keys": extra_keys, "schema_fields": list(allowed)},
        )
    # Normalise field dicts returned by schema-aware LLM prompts:
    # - Strip "type" key: _schema_appendix embeds field types; the model
    #   echoes them back, but ExtractedField has extra="forbid".
    # - Coerce non-null "value" to str: integer/date schema fields yield
    #   Python int/float values, but ExtractedField.value is str | None.
    cleaned: dict[str, Any] = {}
    for k, v in gated.items():
        if isinstance(v, dict):
            entry: dict[str, Any] = {key: val for key, val in v.items() if key != "type"}
            if entry.get("value") is not None and not isinstance(entry["value"], str):
                entry["value"] = str(entry["value"])
            v = entry
        cleaned[k] = v
    return parse_extracted_fields(cleaned)


__all__ = [
    "EXTRACTED_ORDER_FIELD_NAMES",
    "ExtractedField",
    "ExtractedOrderFields",
    "ExtractionConfidence",
    "ExtractionFieldSpec",
    "ExtractionFieldType",
    "ExtractionSchema",
    "ExtractionSchemaParseError",
    "ExtractionSource",
    "parse_extracted_fields",
    "parse_extracted_fields_against_schema",
    "parse_extraction_schema",
]
