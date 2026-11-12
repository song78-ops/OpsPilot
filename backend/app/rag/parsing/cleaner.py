"""Conservative whitespace cleanup that preserves paragraph boundaries."""

import re
import unicodedata


_CONTROL_CHARACTERS = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"
)
_INLINE_WHITESPACE = re.compile(r"[^\S\n]+")
_EXCESSIVE_NEWLINES = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    """Normalize text without removing meaningful paragraph separators."""
    if not text:
        return ""

    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\u00ad", "").replace("\xa0", " ")
    normalized = _CONTROL_CHARACTERS.sub("", normalized)
    normalized = _INLINE_WHITESPACE.sub(" ", normalized)

    lines = [line.strip() for line in normalized.split("\n")]
    normalized = "\n".join(lines)
    normalized = _EXCESSIVE_NEWLINES.sub("\n\n", normalized)
    return normalized.strip()

