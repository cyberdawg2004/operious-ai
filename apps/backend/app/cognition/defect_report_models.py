"""Structured LLM output for defect report synthesis."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DefectReportLLMOutput(BaseModel):
    """Strict engineering report schema produced by the synthesis LLM."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    executive_summary: str = Field(min_length=1)
    affected_category: str = Field(min_length=1)
    incident_count: int = Field(ge=1)
    failure_pattern: str = Field(min_length=1)
    customer_impact: str = Field(min_length=1)
    technical_root_cause_hypothesis: str = Field(min_length=1)
    recommended_actions: list[str] = Field(min_length=1)
    confidence: float
    evidence_quality: str

    @field_validator(
        "title",
        "executive_summary",
        "affected_category",
        "failure_pattern",
        "customer_impact",
        "technical_root_cause_hypothesis",
    )
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be blank")
        return stripped

    @field_validator("recommended_actions")
    @classmethod
    def recommended_actions_must_not_be_blank(
        cls,
        value: list[str],
    ) -> list[str]:
        actions = [action.strip() for action in value]
        if any(not action for action in actions):
            raise ValueError("recommended_actions must not contain blanks")
        return actions

    @field_validator("confidence")
    @classmethod
    def confidence_in_range(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be 0.0-1.0")
        return value

    @field_validator("evidence_quality")
    @classmethod
    def evidence_quality_valid(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ("high", "medium", "low"):
            raise ValueError("evidence_quality must be high/medium/low")
        return normalized


__all__ = ["DefectReportLLMOutput"]
