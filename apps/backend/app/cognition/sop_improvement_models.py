"""Structured LLM output for SOP improvement synthesis."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SOPImprovementLLMOutput(BaseModel):
    """Strict schema for LLM-synthesized SOP improvement proposals."""

    model_config = ConfigDict(extra="forbid")

    improvement_title: str = Field(min_length=1)
    problem_statement: str = Field(min_length=1)
    proposed_sop_addition: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    affected_sop_section: str | None = None
    confidence: float

    @field_validator(
        "improvement_title",
        "problem_statement",
        "proposed_sop_addition",
        "rationale",
    )
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be blank")
        return stripped

    @field_validator("affected_sop_section")
    @classmethod
    def section_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("confidence")
    @classmethod
    def confidence_in_range(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be 0.0-1.0")
        return value


__all__ = ["SOPImprovementLLMOutput"]
