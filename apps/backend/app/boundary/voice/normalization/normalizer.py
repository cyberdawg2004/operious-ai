"""Pure transcript normalisation.

The voice substrate normalises STT transcripts before handing
them off to the translation substrate. Normalisation:

* applies Unicode NFC,
* trims leading/trailing whitespace,
* collapses runs of whitespace,
* rejects NUL bytes.

Normalisation is observational — it never invents content.
"""

from __future__ import annotations

import unicodedata


def normalize_transcript(text: str) -> str:
    if "\x00" in text:
        raise ValueError(
            "VoiceNormalizer.text contains NUL bytes"
        )
    nfc = unicodedata.normalize("NFC", text)
    trimmed = nfc.strip()
    out: list[str] = []
    last_space = False
    for ch in trimmed:
        if ch.isspace():
            if not last_space:
                out.append(" ")
                last_space = True
        else:
            out.append(ch)
            last_space = False
    return "".join(out)


class VoiceNormalizer:
    __slots__ = ()

    def normalize(self, text: str) -> str:
        return normalize_transcript(text)


__all__ = ["VoiceNormalizer", "normalize_transcript"]
