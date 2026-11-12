"""Common parser interface."""

from pathlib import Path
from typing import Protocol

from app.rag.types import ParsedSection


class DocumentParser(Protocol):
    """Extract ordered text sections from a local file."""

    def parse(self, path: Path) -> list[ParsedSection]:
        """Return non-reordered document sections."""
        ...

