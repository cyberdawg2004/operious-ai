"""Service layer for trainer recommendations."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.trainer.persistence import (
    TrainingRecommendationPage,
    TrainingRecommendationRepository,
)
from app.trainer.records import (
    TrainingRecommendationRecord,
    TrainingRecommendationStatus,
)


class TrainerRecommendationNotFoundError(RuntimeError):
    """Raised when a recommendation is absent or tenant-invisible."""


class TrainerRecommendationLifecycleError(RuntimeError):
    """Raised when an unsupported recommendation transition is requested."""


class TrainerRecommendationService:
    def __init__(
        self,
        *,
        repository: TrainingRecommendationRepository,
        session: AsyncSession,
    ) -> None:
        self._repository = repository
        self._session = session

    async def list_recommendations(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
        status: str | None,
        limit: int,
        offset: int,
    ) -> TrainingRecommendationPage:
        _assert_tenant(tenant_id, expected_tenant_id)
        normalized_status = None if status in (None, "all") else status
        return await self._repository.list(
            expected_tenant_id=expected_tenant_id,
            status=normalized_status,
            limit=limit,
            offset=offset,
        )

    async def update_status(
        self,
        *,
        recommendation_id: str,
        tenant_id: str,
        expected_tenant_id: str,
        status: TrainingRecommendationStatus,
    ) -> TrainingRecommendationRecord:
        _assert_tenant(tenant_id, expected_tenant_id)
        if status not in ("acknowledged", "dismissed"):
            raise TrainerRecommendationLifecycleError(
                "only acknowledged or dismissed status updates are supported"
            )
        record = await self._repository.update_status(
            recommendation_id,
            expected_tenant_id=expected_tenant_id,
            status=status,
        )
        if record is None:
            raise TrainerRecommendationNotFoundError(recommendation_id)
        await self._session.commit()
        return record


def _assert_tenant(tenant_id: str, expected_tenant_id: str) -> None:
    if tenant_id != expected_tenant_id:
        raise TrainerRecommendationNotFoundError("tenant mismatch")


__all__ = [
    "TrainerRecommendationLifecycleError",
    "TrainerRecommendationNotFoundError",
    "TrainerRecommendationService",
]
