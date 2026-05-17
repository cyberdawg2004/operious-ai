"""Reference adapters — normalisation examples only.

These adapters are intentionally MINIMAL. They cover the canonical
fields needed for replay-safety + lineage continuity testing and
demonstrate the substrate's translation contract.

Production deployments are expected to register their own subclasses
of `BaseIngressAdapter` / `BaseEgressAdapter` with deeper validation
and signature schemes.
"""

from app.boundary.adapters.builtin.twilio_voice import (
    TwilioVoiceAdapter,
)
from app.boundary.adapters.builtin.whatsapp import (
    WhatsAppWebhookAdapter,
)
from app.boundary.adapters.builtin.zendesk import (
    ZendeskWebhookAdapter,
)

__all__ = [
    "TwilioVoiceAdapter",
    "WhatsAppWebhookAdapter",
    "ZendeskWebhookAdapter",
]
