"""Plain text and Markdown extraction."""

from pathlib import Path

from app.rag.exceptions import DocumentParseError
from app.rag.types import ParsedSection


def read_text_document(path: Path) -> list[ParsedSection]:
    """Decode common local text encodings and return one section."""
    raw = path.read_bytes()
    if b"\x00" in raw:
        raise DocumentParseError("The text document contains binary data.")

    text: str | None = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue

    if text is None:
        raise DocumentParseError(
            "The text document could not be decoded as UTF-8 or GB18030."
        )

    return [ParsedSection(text=text)]

