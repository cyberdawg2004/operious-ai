"""Transport contracts for live conversation endpoints."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.services.conversation_service import (
    ConversationMessageSubmission,
    ConversationOperatorReplySubmission,
)


class ConversationMessageRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str = Field(min_length=1)


class ConversationMessageResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    turn_id: str
    phase_a_response: str
    execution_id: str

    @classmethod
    def from_submission(
        cls,
        submission: ConversationMessageSubmission,
    ) -> "ConversationMessageResponse":
        return cls(
            turn_id=submission.turn_id,
            phase_a_response=submission.phase_a_response,
            execution_id=submission.execution_id,
        )


class ConversationOperatorReplyRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str = Field(min_length=1)


class ConversationOperatorReplyResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    turn_id: str
    channel: str
    provider_message_id: str | None = None

    @classmethod
    def from_submission(
        cls,
        submission: ConversationOperatorReplySubmission,
    ) -> "ConversationOperatorReplyResponse":
        return cls(
            turn_id=submission.turn_id,
            channel=submission.channel,
            provider_message_id=submission.provider_message_id,
        )


__all__ = [
    "ConversationMessageRequest",
    "ConversationMessageResponse",
    "ConversationOperatorReplyRequest",
    "ConversationOperatorReplyResponse",
]
