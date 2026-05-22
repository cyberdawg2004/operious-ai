from pydantic import BaseModel


class DispatchRequest(BaseModel):
    ingress_id: str


class DispatchResponse(BaseModel):
    dispatch_id: str
    session_id: str | None = None
    execution_id: str | None = None
    governance_decision_id: str | None = None
    verdict: str
    arbitration_evaluation_id: str | None = None
    arbitration_outcome: str | None = None
    halted: bool = False
    halt_reason: str | None = None
