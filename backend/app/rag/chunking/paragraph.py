"""Paragraph-aware character chunking."""

import re
from collections.abc import Iterator

from app.rag.types import DocumentChunk, ParsedSection

_PARAGRAPH_SEPARATOR = re.compile(r"\n\s*\n")
_SENTENCE_SEPARATOR = re.compile(r"(?<=[。！？!?；;])|(?<=\.)\s+")


class ParagraphChunker:
    """Pack paragraphs and sentences into overlapping character windows."""

    def __init__(self, *, chunk_size: int, chunk_overlap: int) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if chunk_overlap < 0:
            raise ValueError("chunk_overlap must not be negative")
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    def chunk(
        self,
        *,
        document_id: str,
        filename: str,
        sections: list[ParsedSection],
    ) -> list[DocumentChunk]:
        """Create ordered chunks without crossing page boundaries."""
        chunks: list[DocumentChunk] = []
        chunk_index = 1

        for section in sections:
            for content in self._chunk_text(section.text):
                chunks.append(
                    DocumentChunk(
                        document_id=document_id,
                        chunk_id=f"{document_id}:{chunk_index:04d}",
                        filename=filename,
                        page_number=section.page_number,
                        chunk_index=chunk_index,
                        content=content,
                    )
                )
                chunk_index += 1

        return chunks

    def _chunk_text(self, text: str) -> Iterator[str]:
        paragraphs = [
            paragraph.strip()
            for paragraph in _PARAGRAPH_SEPARATOR.split(text)
            if paragraph.strip()
        ]
        if not paragraphs:
            return

        current = ""
        for paragraph in paragraphs:
            if len(paragraph) > self._chunk_size:
                if current:
                    yield current
                    current = ""
                yield from self._split_long_paragraph(paragraph)
                continue

            if not current:
                current = paragraph
                continue

            candidate = f"{current}\n\n{paragraph}"
            if len(candidate) <= self._chunk_size:
                current = candidate
                continue

            previous = current
            yield previous
            overlap = self._overlap_suffix(previous)
            current = (
                f"{overlap}\n\n{paragraph}"
                if overlap and len(overlap) + 2 + len(paragraph) <= self._chunk_size
                else paragraph
            )

        if current:
            yield current

    def _split_long_paragraph(self, paragraph: str) -> Iterator[str]:
        sentences = [
            sentence.strip()
            for sentence in _SENTENCE_SEPARATOR.split(paragraph)
            if sentence.strip()
        ]
        if not sentences:
            return

        current = ""
        for sentence in sentences:
            if len(sentence) > self._chunk_size:
                if current:
                    yield current
                    current = ""
                yield from self._hard_split(sentence)
                continue

            if not current:
                current = sentence
                continue

            candidate = current + sentence
            if len(candidate) <= self._chunk_size:
                current = candidate
                continue

            previous = current
            yield previous
            overlap = self._overlap_suffix(previous)
            current = (
                overlap + sentence
                if overlap and len(overlap) + len(sentence) <= self._chunk_size
                else sentence
            )

        if current:
            yield current

    def _hard_split(self, text: str) -> Iterator[str]:
        start = 0
        while start < len(text):
            end = min(start + self._chunk_size, len(text))
            chunk = text[start:end].strip()
            if chunk:
                yield chunk
            if end >= len(text):
                break
            start = end - self._chunk_overlap

    def _overlap_suffix(self, text: str) -> str:
        if self._chunk_overlap == 0:
            return ""
        overlap = text[-self._chunk_overlap:].strip()
        return re.sub(r"^[\s。！？!?；;，,、.:：]+", "", overlap)

