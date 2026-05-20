from typing import Literal

from pydantic import BaseModel


class TicketIngressRequest(BaseModel):
    external_id: str
    channel: Literal["email", "whatsapp", "voice"]
    raw_content: str
    language_code: str = "en"


class TicketIngressResponse(BaseModel):
    ingress_id: str
    canonical_envelope_id: str
    status: str = "received"
