from typing import IO, Any, Sequence

class Paragraph:
    text: str

class Document:
    paragraphs: Sequence[Paragraph]
    def __init__(self, docx: IO[bytes] | str | None = None) -> None: ...
