from pydantic import BaseModel


class DispatchRequest(BaseModel):
    ingress_id: str


class DispatchResponse(BaseModel):
    dispatch_id: str
    session_id: str
    execution_id: str
    governance_decision_id: str
    verdict: str
