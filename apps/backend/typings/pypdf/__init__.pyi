from typing import IO, Any, Sequence

class PageObject:
    def extract_text(self) -> str: ...

class PdfReader:
    pages: Sequence[PageObject]
    def __init__(self, stream: IO[bytes] | bytes, **kwargs: Any) -> None: ...
