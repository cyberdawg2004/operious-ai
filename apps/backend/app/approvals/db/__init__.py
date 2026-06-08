"""Case approval ORM package."""

from app.approvals.db.models import (
    CaseApprovalOutboxRow,
    CaseApprovalRecordRow,
)

__all__ = ["CaseApprovalOutboxRow", "CaseApprovalRecordRow"]
