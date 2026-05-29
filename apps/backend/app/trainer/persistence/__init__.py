"""Trainer recommendation persistence surface."""

from app.trainer.persistence.memory import (
    InMemoryTrainingRecommendationRepository,
)
from app.trainer.persistence.postgres import (
    PostgresTrainingRecommendationRepository,
)
from app.trainer.persistence.protocol import (
    TrainingFailurePattern,
    TrainingRecommendationPage,
    TrainingRecommendationRepository,
)

__all__ = [
    "InMemoryTrainingRecommendationRepository",
    "PostgresTrainingRecommendationRepository",
    "TrainingFailurePattern",
    "TrainingRecommendationPage",
    "TrainingRecommendationRepository",
]
