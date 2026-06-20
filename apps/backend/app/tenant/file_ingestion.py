"""Document-upload parsing: magic-byte validation, text extraction."""

from __future__ import annotations

import io
import zipfile

# ── Magic-byte signatures ────────────────────────────────────────────────────
_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"
_DOCX_MEMBER = "word/document.xml"
_EXE_MAGIC = b"MZ"
_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

_MIN_EXTRACTED_CHARS = 50

# Sentinel returned by detect_content_type() for an executable payload.
# Never appears in any caller's allow-list — there is no legitimate
# document or image type that begins with the MZ header.
EXECUTABLE_CONTENT_TYPE = "application/x-msdownload"

ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "text/markdown",
    }
)


class KnowledgeUploadTypeError(ValueError):
    """Raised when magic bytes do not match a supported type (condition 3)."""


class KnowledgeUploadUnparsableError(ValueError):
    """Raised when a supported-type document cannot be parsed into text."""


class KnowledgeUploadEmptyTextError(ValueError):
    """Raised when extraction succeeds but yields too little text (e.g. scanned PDF)."""


def detect_content_type(raw: bytes) -> str | None:
    """Return a canonical MIME type based on magic bytes only, or ``None``
    if no recognized signature matches.

    This is the single shared detector — callers (knowledge uploads,
    customer attachments) apply their OWN allow-list against the result
    rather than each re-implementing magic-byte parsing. The caller's
    declared Content-Type is never consulted here or anywhere downstream.
    """
    if raw[:5] == _PDF_MAGIC:
        return "application/pdf"
    if raw[:2] == _EXE_MAGIC:
        return EXECUTABLE_CONTENT_TYPE
    if raw[:3] == _JPEG_MAGIC:
        return "image/jpeg"
    if raw[:8] == _PNG_MAGIC:
        return "image/png"
    if raw[:4] == _ZIP_MAGIC:
        # DOCX is a ZIP archive that must contain word/document.xml
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                names = zf.namelist()
        except zipfile.BadZipFile:
            return None
        if _DOCX_MEMBER not in names:
            return None
        return (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    # Text files must be valid UTF-8 — latin-1 is not accepted for type sniffing
    # because latin-1 never raises UnicodeDecodeError (it maps all 256 bytes),
    # which would allow arbitrary binary to slip through as "text/plain".
    try:
        raw.decode("utf-8")
        return "text/plain"
    except UnicodeDecodeError:
        return None


def _sniff_content_type(raw: bytes) -> str:
    """Return a canonical MIME type, restricted to ``ALLOWED_CONTENT_TYPES``.

    Rejects the client-supplied Content-Type entirely — the extension or
    MIME type claimed by the uploader is never trusted.
    """
    detected = detect_content_type(raw)
    if detected == EXECUTABLE_CONTENT_TYPE:
        raise KnowledgeUploadTypeError(
            "Executable binary rejected (MZ magic bytes detected)"
        )
    if detected is None or detected not in ALLOWED_CONTENT_TYPES:
        raise KnowledgeUploadTypeError(
            "File does not match any supported type "
            "(expected PDF, DOCX, UTF-8 plain text, or Markdown)"
        )
    return detected


def _extract_pdf(raw: bytes) -> str:
    import pypdf  # deferred: not imported at module level to keep startup cheap

    reader = pypdf.PdfReader(io.BytesIO(raw))
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        parts.append(text)
    return "\n".join(parts)


def _extract_docx(raw: bytes) -> str:
    import docx  # python-docx; deferred same reason

    doc = docx.Document(io.BytesIO(raw))
    return "\n".join(p.text for p in doc.paragraphs)


def parse_uploaded_document(
    *,
    filename: str,
    raw_bytes: bytes,
) -> tuple[str, str]:
    """Parse raw upload bytes into (canonical_content_type, extracted_text).

    Magic-byte sniffing is authoritative; the caller's Content-Type header
    is intentionally ignored (condition 3).  Raises:
      - KnowledgeUploadTypeError      for unsupported or malicious file types
      - KnowledgeUploadUnparsableError for parse failures on a supported type
      - KnowledgeUploadEmptyTextError  for scanned PDFs / near-empty documents
    """
    canonical_type = _sniff_content_type(raw_bytes)

    try:
        if canonical_type == "application/pdf":
            text = _extract_pdf(raw_bytes)
        elif canonical_type == (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ):
            text = _extract_docx(raw_bytes)
        else:
            # text/plain — may be .txt or .md; both are UTF-8 preferred
            try:
                text = raw_bytes.decode("utf-8")
            except UnicodeDecodeError:
                text = raw_bytes.decode("latin-1")
    except (KnowledgeUploadTypeError, KnowledgeUploadUnparsableError):
        raise
    except Exception as exc:
        raise KnowledgeUploadUnparsableError(
            f"Failed to extract text from '{filename}': {exc}"
        ) from exc

    stripped = text.strip()
    if len(stripped) < _MIN_EXTRACTED_CHARS:
        raise KnowledgeUploadEmptyTextError(
            f"Extracted text is too short ({len(stripped)} chars) — "
            "document may be scanned or empty. OCR is not supported in v1."
        )

    return canonical_type, stripped
