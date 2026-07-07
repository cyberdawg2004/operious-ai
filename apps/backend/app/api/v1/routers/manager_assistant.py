"""Manager Assistant endpoint — natural-language analytics for tenant managers.

POST /manager-assistant/query
    Body: {question, session_id?}
    Returns: {answer, chart_type, chart_data, query_key, cannot_answer}
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.schemas.manager_assistant import (
    ManagerAssistantRequest,
    ManagerAssistantResponse,
)
from app.dependencies.authority import (
    require_tenant_operations_read,
    require_tenant_scope,
)
from app.dependencies.services import get_manager_assistant_service
from app.services.manager_assistant_service import ManagerAssistantService

router = APIRouter(tags=["manager-assistant"])


@router.post(
    "/query",
    response_model=ManagerAssistantResponse,
    dependencies=[Depends(require_tenant_operations_read)],
)
async def query_manager_assistant(
    request: ManagerAssistantRequest,
    service: ManagerAssistantService = Depends(get_manager_assistant_service),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> ManagerAssistantResponse:
    if not request.question.strip():
        raise HTTPException(status_code=400, detail={"code": "question_empty"})
    answer = await service.answer(
        question=request.question.strip(),
        tenant_id=expected_tenant_id,
        session_id=request.session_id,
    )
    return ManagerAssistantResponse.from_domain(answer)


__all__ = ["router"]
