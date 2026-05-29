"""v1 API surface aggregator.

Combines every v1 sub-router into a single `APIRouter` that the top-level
API aggregator mounts under the configured v1 prefix. Add new v1
sub-routers here so versioning stays explicit and contained.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routers.action_approvals import (
    router as action_approvals_router,
)
from app.api.v1.routers.audit_export import router as audit_export_router
from app.api.v1.routers.arbitration import router as arbitration_router
from app.api.v1.routers.auth import router as auth_router
from app.api.v1.routers.batch_ingest import router as batch_ingest_router
from app.api.v1.routers.boundary import router as boundary_router
from app.api.v1.routers.cognition import router as cognition_router
from app.api.v1.routers.conversation import router as conversation_router
from app.api.v1.routers.coordination import router as coordination_router
from app.api.v1.routers.dispatch import router as dispatch_router
from app.api.v1.routers.escalation import router as escalation_router
from app.api.v1.routers.governance import router as governance_router
from app.api.v1.routers.health import router as health_router
from app.api.v1.routers.ingress import router as ingress_router
from app.api.v1.routers.knowledge import router as knowledge_router
from app.api.v1.routers.observability import router as observability_router
from app.api.v1.routers.operational_events import (
    router as operational_events_router,
)
from app.api.v1.routers.quota_operations import (
    router as quota_operations_router,
)
from app.api.v1.routers.queue_operations import (
    router as queue_operations_router,
)
from app.api.v1.routers.session import router as session_router
from app.api.v1.routers.sop_intelligence import (
    router as sop_intelligence_router,
)
from app.api.v1.routers.supervisor import router as supervisor_router
from app.api.v1.routers.tenant import router as tenant_router
from app.api.v1.routers.voice import router as voice_router

api_router_v1 = APIRouter()
api_router_v1.include_router(health_router)
api_router_v1.include_router(batch_ingest_router)
api_router_v1.include_router(audit_export_router, prefix="/audit")
api_router_v1.include_router(auth_router, prefix="/auth")
api_router_v1.include_router(governance_router, prefix="/governance")
api_router_v1.include_router(coordination_router, prefix="/coordination")
api_router_v1.include_router(dispatch_router, prefix="/coordination")
api_router_v1.include_router(escalation_router, prefix="/escalations")
api_router_v1.include_router(cognition_router, prefix="/cognition")
api_router_v1.include_router(
    action_approvals_router, prefix="/approvals/actions"
)
api_router_v1.include_router(conversation_router, prefix="/conversation")
api_router_v1.include_router(
    sop_intelligence_router, prefix="/sop-intelligence/approvals"
)
api_router_v1.include_router(arbitration_router, prefix="/arbitration")
api_router_v1.include_router(boundary_router, prefix="/boundary")
api_router_v1.include_router(
    ingress_router, prefix="/boundary/translation"
)
api_router_v1.include_router(supervisor_router, prefix="/supervisor")
api_router_v1.include_router(session_router, prefix="/session")
api_router_v1.include_router(tenant_router, prefix="/tenant")
api_router_v1.include_router(knowledge_router, prefix="/knowledge")
api_router_v1.include_router(observability_router, prefix="/observability")
api_router_v1.include_router(
    operational_events_router, prefix="/operational-events"
)
api_router_v1.include_router(quota_operations_router, prefix="/quota")
api_router_v1.include_router(queue_operations_router)
api_router_v1.include_router(voice_router, prefix="/voice")

__all__ = ["api_router_v1"]
