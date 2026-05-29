"""Voice persistence ORM rows."""

from app.boundary.voice.db.models import (
    VoiceEgressRecordRow,
    VoiceIngressRecordRow,
)

__all__ = [
    "VoiceEgressRecordRow",
    "VoiceIngressRecordRow",
]
