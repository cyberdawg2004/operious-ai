"""Approval review task publisher boundary."""

from __future__ import annotations

from typing import Protocol


class CaseApprovalReviewPublisher(Protocol):
    """Transport boundary for SME review work."""

    async def publish_case_review(
        self,
        *,
        approval_case_id: str,
        tenant_id: str,
    ) -> None: ...


__all__ = ["CaseApprovalReviewPublisher"]
