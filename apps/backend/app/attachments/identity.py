"""Strong identity type for attachment rows."""

from __future__ import annotations

import uuid
from typing import NewType

AttachmentId = NewType("AttachmentId", uuid.UUID)
