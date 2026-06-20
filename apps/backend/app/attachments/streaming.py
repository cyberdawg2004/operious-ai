"""Bounded streaming reader for untrusted attachment input.

Aborts the moment cumulative size exceeds the cap, rather than reading the
full body into memory and checking afterward — the
``tenant_knowledge_uploads`` pattern (``file.read(max_bytes + 1)``), which
is acceptable at low-frequency admin-initiated KB-upload volume but not at
per-ticket attachment volume, where a malicious multi-GB "invoice" must
never be fully buffered.
"""

from __future__ import annotations

from collections.abc import Iterable


class AttachmentTooLargeError(ValueError):
    """Raised when streamed content exceeds the configured byte cap.

    ``bytes_read`` is how much was actually buffered before the abort —
    always close to ``max_bytes``, never the full size of an oversized
    source, which is the property the streaming-abort break-control proves.
    """

    def __init__(self, max_bytes: int, bytes_read: int) -> None:
        self.max_bytes = max_bytes
        self.bytes_read = bytes_read
        super().__init__(
            f"attachment exceeds {max_bytes} byte limit "
            f"(aborted after buffering {bytes_read} bytes)"
        )


def read_bounded(chunks: Iterable[bytes], *, max_bytes: int) -> bytes:
    """Consume ``chunks`` into memory, aborting as soon as the cumulative
    size exceeds ``max_bytes``. Never pulls another chunk from the source
    once the cap is exceeded.
    """
    buf = bytearray()
    for chunk in chunks:
        buf += chunk
        if len(buf) > max_bytes:
            raise AttachmentTooLargeError(max_bytes, len(buf))
    return bytes(buf)
