"""DOCX paragraph and table extraction."""

from pathlib import Path

from docx import Document
from docx.opc.exceptions import PackageNotFoundError

from app.rag.exceptions import DocumentParseError
from app.rag.types import ParsedSection


def parse_docx(path: Path) -> list[ParsedSection]:
    """Extract document paragraphs and simple table cell text."""
    with path.open("rb") as handle:
        if handle.read(4) != b"PK\x03\x04":
            raise DocumentParseError("The uploaded file is not a valid DOCX.")

    try:
        document = Document(str(path))
    except (PackageNotFoundError, OSError, ValueError, KeyError) as exc:
        raise DocumentParseError(
            "The DOCX is damaged or its text could not be extracted."
        ) from exc

    blocks = [
        paragraph.text.strip()
        for paragraph in document.paragraphs
        if paragraph.text.strip()
    ]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            row_text = " | ".join(cell for cell in cells if cell)
            if row_text:
                blocks.append(row_text)

    text = "\n\n".join(blocks)
    if not text.strip():
        raise DocumentParseError("The DOCX contains no extractable text.")
    return [ParsedSection(text=text)]

