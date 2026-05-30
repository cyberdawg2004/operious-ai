"""Knowledge re-index publication boundary."""

from __future__ import annotations

from typing import Any, cast

from app.workers.knowledge_tasks import reindex_knowledge_document


class CeleryKnowledgeReindexPublisher:
    """Publish knowledge document re-index work to Celery."""

    def publish_reindex(
        self,
        *,
        document_id: str,
        tenant_id: str,
    ) -> None:
        cast(Any, reindex_knowledge_document).delay(
            document_id=document_id,
            tenant_id=tenant_id,
        )


__all__ = ["CeleryKnowledgeReindexPublisher"]
