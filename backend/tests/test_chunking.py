"""Paragraph-aware chunking behavior tests."""

from app.rag.chunking.paragraph import ParagraphChunker
from app.rag.types import ParsedSection


def test_short_paragraphs_stay_together_when_they_fit() -> None:
    chunker = ParagraphChunker(chunk_size=80, chunk_overlap=10)

    chunks = chunker.chunk(
        document_id="a" * 32,
        filename="sample.txt",
        sections=[
            ParsedSection(
                text="第一段说明。\n\n第二段也较短。\n\n第三段同样较短。"
            )
        ],
    )

    assert len(chunks) == 1
    assert chunks[0].content == "第一段说明。\n\n第二段也较短。\n\n第三段同样较短。"
    assert chunks[0].chunk_index == 1


def test_overlong_paragraph_is_split_with_overlap() -> None:
    text = "".join(chr(ord("a") + (index % 26)) for index in range(130))
    chunker = ParagraphChunker(chunk_size=50, chunk_overlap=10)

    chunks = chunker.chunk(
        document_id="b" * 32,
        filename="long.txt",
        sections=[ParsedSection(text=text)],
    )

    assert len(chunks) >= 3
    assert all(len(chunk.content) <= 50 for chunk in chunks)
    assert chunks[1].content.startswith(chunks[0].content[-10:])


def test_chunks_do_not_cross_page_boundaries() -> None:
    chunker = ParagraphChunker(chunk_size=60, chunk_overlap=10)

    chunks = chunker.chunk(
        document_id="c" * 32,
        filename="pages.pdf",
        sections=[
            ParsedSection(text="第一页内容。\n\n第一页第二段。", page_number=1),
            ParsedSection(text="第二页内容。\n\n第二页第二段。", page_number=2),
        ],
    )

    assert [chunk.page_number for chunk in chunks] == [1, 2]
    assert [chunk.chunk_index for chunk in chunks] == [1, 2]
    assert "第二页内容" not in chunks[0].content
    assert "第一页内容" not in chunks[1].content


def test_overlap_does_not_begin_with_orphan_punctuation() -> None:
    first = "甲" * 70 + "。"
    second = "乙" * 50 + "。"
    chunker = ParagraphChunker(chunk_size=80, chunk_overlap=20)

    chunks = chunker.chunk(
        document_id="d" * 32,
        filename="overlap.txt",
        sections=[ParsedSection(text=f"{first}\n\n{second}")],
    )

    assert len(chunks) == 2
    assert not chunks[1].content.startswith(("。", "，", "；"))

