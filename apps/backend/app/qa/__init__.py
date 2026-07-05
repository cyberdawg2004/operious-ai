"""QA agent substrate.

The QA agent is observational: it reads persisted supervisor evidence,
scores quality dimensions, and writes only ``QAScoreRecord`` rows.
"""

from app.qa.enums import QA_SCORE_DIMENSIONS, QAScoreDimension, SemanticGroundingVerdict
from app.qa.exceptions import QAError, QAEvaluationError, QAPersistenceError
from app.qa.identity import QAScoreId, as_qa_score_id, derive_qa_score_id
from app.qa.persistence import (
    InMemoryQAPersistence,
    PostgresQAPersistence,
    QAPersistenceProtocol,
    QAScorePage,
    QAScoreQuery,
    QAScoreRecord,
)
from app.qa.runtime import QAAgentRuntime, build_qa_score_record

__all__ = [
    "InMemoryQAPersistence",
    "PostgresQAPersistence",
    "QAAgentRuntime",
    "QAPersistenceProtocol",
    "QAError",
    "QAEvaluationError",
    "QAPersistenceError",
    "QA_SCORE_DIMENSIONS",
    "QAScoreDimension",
    "SemanticGroundingVerdict",
    "QAScoreId",
    "QAScorePage",
    "QAScoreQuery",
    "QAScoreRecord",
    "as_qa_score_id",
    "build_qa_score_record",
    "derive_qa_score_id",
]
