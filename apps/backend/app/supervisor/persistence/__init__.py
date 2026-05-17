"""Supervisor persistence — contracts and in-memory reference impl.

Sprint K ships:

* `records`     — persistable record shapes (frozen + slots,
                   to_dict / from_dict),
* `models`      — `InspectionQuery`, `RecordPage`,
* `repository`  — `BaseSupervisorRepository` Protocol,
* `memory`      — `InMemorySupervisorRepository` reference impl,
* `serializers` — pure result/envelope → records converters.

Future sprints add Postgres / Elasticsearch backends behind the same
Protocol. No migrations are introduced in Sprint K — persistence is
contracts only.
"""

from app.supervisor.persistence.memory import InMemorySupervisorRepository
from app.supervisor.persistence.models import InspectionQuery, RecordPage
from app.supervisor.persistence.records import (
    EscalationDecisionRecord,
    EvaluationEvidenceRecord,
    InspectionRecord,
    QAEvaluationRecord,
    RuntimeFindingRecord,
    SupervisorDecisionRecord,
)
from app.supervisor.persistence.repository import BaseSupervisorRepository
from app.supervisor.persistence.serializers import (
    inspection_envelope_to_records,
    inspection_result_to_records,
)

__all__ = [
    "InspectionQuery",
    "RecordPage",
    "EvaluationEvidenceRecord",
    "RuntimeFindingRecord",
    "QAEvaluationRecord",
    "EscalationDecisionRecord",
    "SupervisorDecisionRecord",
    "InspectionRecord",
    "BaseSupervisorRepository",
    "InMemorySupervisorRepository",
    "inspection_envelope_to_records",
    "inspection_result_to_records",
]
