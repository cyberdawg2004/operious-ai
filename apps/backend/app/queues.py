"""Queue name constants for Operious AI queue topology.

This is the single source of truth for all queue names.
No bare string queue names are permitted in queue publishers or worker
tasks. All task declarations and publishers must import from this
neutral module.
"""

# Ingress queues -- one per channel
QUEUE_INGRESS_EMAIL = "ingress.email"
QUEUE_INGRESS_WHATSAPP = "ingress.whatsapp"
QUEUE_INGRESS_SHOPIFY = "ingress.shopify"
QUEUE_INGRESS_VOICE = "ingress.voice"

# Diagnostic queues -- priority-ordered
QUEUE_DIAGNOSTIC_HIGH = "diagnostic.high"
QUEUE_DIAGNOSTIC_NORMAL = "diagnostic.normal"
QUEUE_DIAGNOSTIC_RETRY = "diagnostic.retry"

# Agent queues
QUEUE_ESCALATION = "escalation"
QUEUE_SUPERVISOR = "supervisor"
QUEUE_QA = "qa"
QUEUE_SOP_INTELLIGENCE = "sop_intelligence"
QUEUE_KNOWLEDGE_INDEXING = "knowledge_indexing"

# Maintenance queues
QUEUE_WEBHOOK_MAINTENANCE = "webhook_maintenance"
QUEUE_DEAD_LETTER = "dead_letter"
# Frozen queue -- no auto-retry, operator release only.
QUEUE_SEMANTIC_QUARANTINE = "semantic_quarantine"

# Ordered tuple for priority consumption -- diagnostic workers consume in this order
DIAGNOSTIC_QUEUE_PRIORITY: tuple[str, ...] = (
    QUEUE_DIAGNOSTIC_HIGH,
    QUEUE_DIAGNOSTIC_NORMAL,
    QUEUE_DIAGNOSTIC_RETRY,
)

# All queues -- used for health checks and observability
ALL_QUEUES: tuple[str, ...] = (
    QUEUE_INGRESS_EMAIL,
    QUEUE_INGRESS_WHATSAPP,
    QUEUE_INGRESS_SHOPIFY,
    QUEUE_INGRESS_VOICE,
    QUEUE_DIAGNOSTIC_HIGH,
    QUEUE_DIAGNOSTIC_NORMAL,
    QUEUE_DIAGNOSTIC_RETRY,
    QUEUE_ESCALATION,
    QUEUE_SUPERVISOR,
    QUEUE_QA,
    QUEUE_SOP_INTELLIGENCE,
    QUEUE_KNOWLEDGE_INDEXING,
    QUEUE_WEBHOOK_MAINTENANCE,
    QUEUE_DEAD_LETTER,
    QUEUE_SEMANTIC_QUARANTINE,
)
