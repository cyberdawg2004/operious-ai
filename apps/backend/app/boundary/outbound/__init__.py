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
from app.boundary.outbound.send_outbox import (
    InMemoryOutboundSendOutboxPersistence,
    OutboundSendOutboxRecord,
    OutboundSendOutboxRuntime,
    OutboundSendOutboxStatus,
    PostgresOutboundSendOutboxPersistence,
)
from app.boundary.outbound.reply_context import (
    OutboundReplyContext,
    extract_outbound_reply_context,
    outbound_reply_context_from_dispatch_body,
)

__all__ = [
    "InMemoryWhatsAppDeliveryRepository",
    "EmailCustomerReplyDeliveryRecord",
    "EmailDeliveryRepository",
    "EmailDeliveryStatus",
    "InMemoryEmailDeliveryRepository",
    "InMemoryOutboundSendOutboxPersistence",
    "OutboundSendOutboxRecord",
    "OutboundSendOutboxRuntime",
    "OutboundSendOutboxStatus",
    "OutboundWebhookAdapter",
    "OutboundWebhookRequest",
    "OutboundWebhookResponse",
    "PostgresEmailDeliveryRepository",
    "PostgresOutboundSendOutboxPersistence",
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
    "OutboundReplyContext",
    "extract_outbound_reply_context",
    "outbound_reply_context_from_dispatch_body",
    "derive_whatsapp_customer_reply_delivery_id",
    "derive_email_customer_reply_delivery_id",
    "format_jira_payload",
    "format_linear_payload",
]
