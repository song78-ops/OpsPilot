"""Build shared retrieval units for dense and lexical indexes."""

from app.rag.embeddings.base import EmbeddingProvider
from app.rag.exceptions import EmbeddingTokenLimitError
from app.rag.retrieval.types import RetrievalUnit
from app.rag.types import DocumentRecord


def build_retrieval_units(
    record: DocumentRecord,
    embedding: EmbeddingProvider,
) -> list[RetrievalUnit]:
    """Split every Chunk with the embedding tokenizer exactly once."""
    maximum = embedding.info.max_tokens
    units: list[RetrievalUnit] = []

    for chunk in record.chunks:
        parts = embedding.split_text(chunk.content)
        for part_index, part_text in enumerate(parts, start=1):
            token_count = embedding.count_tokens(part_text)
            if token_count > maximum:
                raise EmbeddingTokenLimitError(token_count, maximum)
            units.append(
                RetrievalUnit(
                    document_id=chunk.document_id,
                    chunk_id=chunk.chunk_id,
                    filename=chunk.filename,
                    page_number=chunk.page_number,
                    chunk_index=chunk.chunk_index,
                    content=part_text,
                    part_index=part_index,
                    part_count=len(parts),
                    original_chunk_char_count=chunk.char_count,
                )
            )
    return units
