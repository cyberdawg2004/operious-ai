"""Outbound webhook boundary adapters."""

from app.boundary.outbound.adapter import (
    OutboundWebhookAdapter,
    OutboundWebhookRequest,
    OutboundWebhookResponse,
)
from app.boundary.outbound.formatters import (
    format_jira_payload,
    format_linear_payload,
)
from app.boundary.outbound.whatsapp import (
    WhatsAppGraphAPIError,
    WhatsAppGraphSender,
    WhatsAppTextMessageRequest,
    WhatsAppTextMessageResponse,
)
from app.boundary.outbound.email_ses import (
    SesEmailSendRequest,
    SesEmailSendResponse,
    SesV2EmailSender,
    SesV2SendError,
)
from app.boundary.outbound.email_delivery import (
    EmailCustomerReplyDeliveryRecord,
    EmailDeliveryRepository,
    EmailDeliveryStatus,
    InMemoryEmailDeliveryRepository,
    PostgresEmailDeliveryRepository,
    derive_email_customer_reply_delivery_id,
)
from app.boundary.outbound.whatsapp_delivery import (
    InMemoryWhatsAppDeliveryRepository,
    PostgresWhatsAppDeliveryRepository,
    WhatsAppCustomerReplyDeliveryRecord,
    WhatsAppDeliveryRepository,
    WhatsAppDeliveryStatus,
    derive_whatsapp_customer_reply_delivery_id,
)

__all__ = [
    "InMemoryWhatsAppDeliveryRepository",
    "EmailCustomerReplyDeliveryRecord",
    "EmailDeliveryRepository",
    "EmailDeliveryStatus",
    "InMemoryEmailDeliveryRepository",
    "OutboundWebhookAdapter",
    "OutboundWebhookRequest",
    "OutboundWebhookResponse",
    "PostgresEmailDeliveryRepository",
    "PostgresWhatsAppDeliveryRepository",
    "SesEmailSendRequest",
    "SesEmailSendResponse",
    "SesV2EmailSender",
    "SesV2SendError",
    "WhatsAppCustomerReplyDeliveryRecord",
    "WhatsAppDeliveryRepository",
    "WhatsAppDeliveryStatus",
    "WhatsAppGraphAPIError",
    "WhatsAppGraphSender",
    "WhatsAppTextMessageRequest",
    "WhatsAppTextMessageResponse",
    "derive_whatsapp_customer_reply_delivery_id",
    "derive_email_customer_reply_delivery_id",
    "format_jira_payload",
    "format_linear_payload",
]
