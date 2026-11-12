"""PDF text extraction."""

from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.rag.exceptions import DocumentParseError
from app.rag.types import ParsedSection


def parse_pdf(path: Path) -> list[ParsedSection]:
    """Extract text page by page, preserving one-based page numbers."""
    with path.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise DocumentParseError("The uploaded file is not a valid PDF.")

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            raise DocumentParseError("Encrypted PDF files are not supported.")

        sections: list[ParsedSection] = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                sections.append(
                    ParsedSection(text=text, page_number=page_number)
                )
    except DocumentParseError:
        raise
    except (PdfReadError, OSError, ValueError) as exc:
        raise DocumentParseError(
            "The PDF is damaged or its text could not be extracted."
        ) from exc

    if not sections:
        raise DocumentParseError(
            "No extractable text was found in the PDF. "
            "Scanned PDFs require OCR, which is not enabled yet."
        )
    return sections

