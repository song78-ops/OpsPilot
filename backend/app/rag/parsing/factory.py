"""Parser selection based on a validated file suffix."""

from pathlib import Path

from app.rag.parsing.docx import parse_docx
from app.rag.parsing.pdf import parse_pdf
from app.rag.parsing.text import read_text_document
from app.rag.types import ParsedSection

SUPPORTED_EXTENSIONS = frozenset({".pdf", ".docx", ".txt", ".md", ".markdown"})


def parse_document(path: Path, extension: str) -> list[ParsedSection]:
    """Dispatch to the parser for a supported lower-case extension."""
    if extension == ".pdf":
        return parse_pdf(path)
    if extension == ".docx":
        return parse_docx(path)
    if extension in {".txt", ".md", ".markdown"}:
        return read_text_document(path)
    raise ValueError(f"No parser registered for extension: {extension}")

