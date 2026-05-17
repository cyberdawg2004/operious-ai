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
from app.boundary.adapters.builtin import (
    TwilioVoiceAdapter,
    WhatsAppWebhookAdapter,
    ZendeskWebhookAdapter,
)

__all__ = [
    "BaseEgressAdapter",
    "BaseIngressAdapter",
    "TwilioVoiceAdapter",
    "WhatsAppWebhookAdapter",
    "ZendeskWebhookAdapter",
]
