from typing import Annotated, Literal

from pydantic import BaseModel, Field

# Per-field ceilings bound LLM payload cost and per-request DoS surface
# independently of the global 1 MiB body limit.  A single field consuming
# the full body budget could starve other fields of parsing or drive
# disproportionate LLM token cost.
_MAX_CONTENT_BYTES = 100_000  # 100 KB — covers any real customer message
_MAX_ID_BYTES = 1_024  # 1 KB — external IDs are never long
_MAX_LANGUAGE_BYTES = 32  # BCP-47 tags are at most ~12 chars


class TicketIngressRequest(BaseModel):
    external_id: Annotated[str, Field(max_length=_MAX_ID_BYTES)]
    channel: Literal["email", "whatsapp", "voice"]
    raw_content: Annotated[str, Field(max_length=_MAX_CONTENT_BYTES)]
    language_code: Annotated[str, Field(max_length=_MAX_LANGUAGE_BYTES)] = "en"


class TicketIngressResponse(BaseModel):
    ingress_id: str | None = None
    canonical_envelope_id: str | None = None
    quarantine_id: str | None = None
    status: str = "received"


class TicketIngressWebhookResponse(BaseModel):
    ingress_id: str | None = None
    canonical_envelope_id: str | None = None
    status: Literal[
        "received",
        "duplicate_delivery_acknowledged",
        "subscription_confirmed",
    ] = "received"
