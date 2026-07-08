"""Manager Assistant transport schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.services.manager_assistant_service import AssistantAnswer


class ManagerAssistantRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    question: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = None


class ManagerAssistantResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    answer: str
    chart_type: str
    chart_data: dict[str, Any] = Field(default_factory=dict)
    query_key: str
    cannot_answer: bool
    invocation_id: str

    @classmethod
    def from_domain(cls, a: AssistantAnswer) -> "ManagerAssistantResponse":
        return cls(
            answer=a.answer,
            chart_type=a.chart_type,
            chart_data=a.chart_data,
            query_key=a.query_key,
            cannot_answer=a.cannot_answer,
            invocation_id=a.invocation_id,
        )


__all__ = ["ManagerAssistantRequest", "ManagerAssistantResponse"]
