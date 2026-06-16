"""Document-upload parsing: magic-byte validation, text extraction."""

from __future__ import annotations

import io
import zipfile

# ── Magic-byte signatures ────────────────────────────────────────────────────
_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"
_DOCX_MEMBER = "word/document.xml"
_EXE_MAGIC = b"MZ"

_MIN_EXTRACTED_CHARS = 50

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


def _sniff_content_type(raw: bytes) -> str:
    """Return a canonical MIME type based on magic bytes only.

    Rejects the client-supplied Content-Type entirely — the extension or
    MIME type claimed by the uploader is never trusted.
    """
    if raw[:5] == _PDF_MAGIC:
        return "application/pdf"
    if raw[:2] == _EXE_MAGIC:
        raise KnowledgeUploadTypeError(
            "Executable binary rejected (MZ magic bytes detected)"
        )
    if raw[:4] == _ZIP_MAGIC:
        # DOCX is a ZIP archive that must contain word/document.xml
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                names = zf.namelist()
        except zipfile.BadZipFile as exc:
            raise KnowledgeUploadTypeError(
                f"File has ZIP magic bytes but is not a valid ZIP archive: {exc}"
            ) from exc
        if _DOCX_MEMBER not in names:
            raise KnowledgeUploadTypeError(
                "ZIP archive does not contain word/document.xml — not a valid .docx"
            )
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
        pass
    raise KnowledgeUploadTypeError(
        "File does not match any supported type "
        "(expected PDF, DOCX, UTF-8 plain text, or Markdown)"
    )


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
