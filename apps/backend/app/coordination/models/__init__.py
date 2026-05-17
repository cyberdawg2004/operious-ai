"""Coordination value-object models.

Internal data shapes used by the runtime + envelope contract:

* `payload`       — `CoordinationPayload` (typed message body).
* `recipients`    — `CoordinationRecipient` (typed recipient identity).
* `participants`  — `CoordinationParticipant` (registry entry shape).

These are pure value objects — frozen, slotted, JSON-serialisable.
They never reach across substrate boundaries except through the
`contracts/` request / result shapes.
"""

from app.coordination.models.participants import CoordinationParticipant
from app.coordination.models.payload import CoordinationPayload
from app.coordination.models.recipients import CoordinationRecipient

__all__ = [
    "CoordinationPayload",
    "CoordinationRecipient",
    "CoordinationParticipant",
]
