"""Boundary adapters.

* `base`     — `BaseIngressAdapter`, `BaseEgressAdapter` ABCs.
* `builtin`  — reference adapters (Zendesk / WhatsApp / Twilio Voice).

Reference adapters are **normalisation examples**. They cover the
canonical shapes well enough for replay-safety + audit testing
but are NOT full production integrations. Production deployments
register their own subclasses against the same ABCs.
"""

from app.boundary.adapters.base import (
    BaseEgressAdapter,
    BaseIngressAdapter,
)
from app.boundary.adapters.channel_webhooks import (
    ChannelWebhookSecurityContext,
    EmailWebhookAdapter,
    LarkWebhookAdapter,
    ShulexWebhookAdapter,
    TenantWhatsAppWebhookAdapter,
    canonical_channel_payload_keys,
    extract_routing_address,
    extract_webhook_security_context,
    normalize_routing_address,
)
from app.boundary.adapters.email_ses import SesEmailWebhookAdapter
from app.boundary.adapters.builtin import (
    TwilioVoiceAdapter,
    WhatsAppWebhookAdapter,
    ZendeskWebhookAdapter,
)

__all__ = [
    "BaseEgressAdapter",
    "BaseIngressAdapter",
    "ChannelWebhookSecurityContext",
    "EmailWebhookAdapter",
    "LarkWebhookAdapter",
    "SesEmailWebhookAdapter",
    "ShulexWebhookAdapter",
    "TenantWhatsAppWebhookAdapter",
    "TwilioVoiceAdapter",
    "WhatsAppWebhookAdapter",
    "ZendeskWebhookAdapter",
    "canonical_channel_payload_keys",
    "extract_routing_address",
    "extract_webhook_security_context",
    "normalize_routing_address",
]
