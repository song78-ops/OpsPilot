"""Document upload, parsing, chunking, and persistence tests."""

import io
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from docx import Document

from app.api.deps import get_document_service
from app.main import app
from app.rag.service import DocumentService
from app.rag.storage.local import LocalDocumentStore

FIXTURES = Path(__file__).parent / "fixtures" / "documents"


def make_service(
    root: Path,
    *,
    max_upload_bytes: int = 2 * 1024 * 1024,
    chunk_size: int = 160,
    chunk_overlap: int = 30,
) -> DocumentService:
    return DocumentService(
        store=LocalDocumentStore(root),
        max_upload_bytes=max_upload_bytes,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )


def override_document_service(service: DocumentService) -> None:
    app.dependency_overrides[get_document_service] = lambda: service


async def upload(
    client: httpx.AsyncClient,
    *,
    filename: str,
    content: bytes,
    content_type: str = "application/octet-stream",
) -> httpx.Response:
    return await client.post(
        "/api/v1/documents/upload",
        files={"file": (filename, content, content_type)},
    )


def make_docx_bytes() -> bytes:
    document = Document()
    document.add_heading("OpsPilot DOCX 测试", level=1)
    document.add_paragraph(
        "这是第一段 DOCX 文本，用于验证段落提取和文本切块。"
    )
    document.add_paragraph(
        "这是第二段 DOCX 文本，用于确认多个段落会保持顺序。"
    )
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "字段"
    table.cell(0, 1).text = "示例值"

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def make_pdf_bytes(text: str | None = "PDF extracted paragraph.") -> bytes:
    stream = (
        f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
        if text
        else b""
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(stream)
        + stream
        + b"\nendstream",
    ]

    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(body)
        output.extend(b"\nendobj\n")

    xref_offset = len(output)
    output.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size 6 /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)


async def test_upload_txt_returns_chunks_and_metadata(
    client: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    override_document_service(make_service(tmp_path))
    content = (FIXTURES / "sample.txt").read_bytes()

    response = await upload(
        client,
        filename="sample.txt",
        content=content,
        content_type="text/plain",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "sample.txt"
    assert body["extension"] == ".txt"
    assert body["chunk_count"] >= 2
    assert body["chunks"][0]["document_id"] == body["document_id"]
    assert body["chunks"][0]["chunk_index"] == 1
    assert body["chunks"][0]["page_number"] is None
    assert body["chunks"][0]["filename"] == "sample.txt"
    assert body["chunks"][0]["char_count"] == len(
        body["chunks"][0]["content"]
    )

    list_response = await client.get("/api/v1/documents")
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert "chunks" not in list_response.json()["items"][0]

    detail_response = await client.get(
        f"/api/v1/documents/{body['document_id']}"
    )
    assert detail_response.status_code == 200
    assert detail_response.json()["chunks"] == body["chunks"]


async def test_markdown_upload_is_supported(
    client: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    override_document_service(make_service(tmp_path))
    content = (FIXTURES / "sample.md").read_bytes()

    response = await upload(
        client,
        filename="knowledge.md",
        content=content,
        content_type="text/markdown",
    )

    assert response.status_code == 201
    assert response.json()["extension"] == ".md"
    assert "OpsPilot 知识库说明" in response.json()["chunks"][0]["content"]


async def test_docx_upload_extracts_paragraphs_and_table(
    client: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    override_document_service(make_service(tmp_path))

    response = await upload(
        client,
        filename="manual.docx",
        content=make_docx_bytes(),
        content_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
    )

    assert response.status_code == 201
    extracted = "\n".join(
        chunk["content"] for chunk in response.json()["chunks"]
    )
    assert "第一段 DOCX 文本" in extracted
    assert "第二段 DOCX 文本" in extracted
    assert "字段 | 示例值" in extracted


async def test_pdf_upload_preserves_page_number(
    client: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    override_document_service(make_service(tmp_path))

    response = await upload(
        client,
        filename="page.pdf",
        content=make_pdf_bytes("Paragraph from PDF page one."),
        content_type="application/pdf",
    )

    assert response.status_code == 201
    assert response.json()["chunks"][0]["page_number"] == 1
    assert "Paragraph from PDF page one." in response.json()["chunks"][0][
        "content"
    ]


async def test_uploaded_document_persists_for_a_new_store(
    client: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    override_document_service(service)
    content = (FIXTURES / "sample.txt").read_bytes()
    response = await upload(client, filename="persist.txt", content=content)
    document_id = response.json()["document_id"]

    restarted_service = make_service(tmp_path)
    original = await service.get_document(document_id)
    records = await restarted_service.list_documents()
    restored = await restarted_service.get_document(document_id)

    assert [record.document_id for record in records] == [document_id]
    assert restored.filename == "persist.txt"
    assert restored.chunks == original.chunks


async def test_filename_traversal_is_sanitized(
    client: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    override_document_service(make_service(tmp_path))
    content = (FIXTURES / "sample.txt").read_bytes()

    response = await upload(
        client,
        filename="../../outside.txt",
        content=content,
    )

    assert response.status_code == 201
    assert response.json()["filename"] == "outside.txt"
    stored_files = list(tmp_path.rglob("*"))
    assert all(tmp_path.resolve() in path.resolve().parents for path in stored_files)


async def test_empty_document_returns_clear_error(
    client: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    override_document_service(make_service(tmp_path))

    response = await upload(client, filename="empty.txt", content=b"")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "DOCUMENT_VALIDATION_ERROR"


async def test_scanned_pdf_without_text_is_rejected(
    client: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    override_document_service(make_service(tmp_path))

    response = await upload(
        client,
        filename="scan.pdf",
        content=make_pdf_bytes(None),
        content_type="application/pdf",
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DOCUMENT_PARSE_ERROR"
    assert "OCR" in response.json()["error"]["message"]


async def test_corrupted_pdf_and_docx_do_not_crash_service(
    client: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    override_document_service(make_service(tmp_path))

    pdf_response = await upload(
        client,
        filename="broken.pdf",
        content=b"%PDF-1.4\nthis is not a complete PDF",
    )
    docx_response = await upload(
        client,
        filename="broken.docx",
        content=b"PK\x03\x04broken",
    )
    health_response = await client.get("/api/v1/health")

    assert pdf_response.status_code == 422
    assert docx_response.status_code == 422
    assert health_response.status_code == 200


async def test_unsupported_and_oversized_files_are_rejected(
    client: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    override_document_service(make_service(tmp_path, max_upload_bytes=10))

    unsupported = await upload(
        client,
        filename="data.csv",
        content=b"a,b\n1,2",
    )
    oversized = await upload(
        client,
        filename="large.txt",
        content=b"01234567890",
    )

    assert unsupported.status_code == 415
    assert oversized.status_code == 413


async def test_missing_document_returns_404(client: httpx.AsyncClient, tmp_path: Path) -> None:
    override_document_service(make_service(tmp_path))

    response = await client.get(f"/api/v1/documents/{'f' * 32}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


async def test_parser_accepts_bytes_iterator_directly(tmp_path: Path) -> None:
    service = make_service(tmp_path)

    async def content() -> AsyncIterator[bytes]:
        yield b"First paragraph.\n\nSecond paragraph."

    record = await service.ingest(
        filename="direct.txt",
        content_type="text/plain",
        content=content(),
    )

    assert record.filename == "direct.txt"
    assert record.chunks[0].content == (
        "First paragraph.\n\nSecond paragraph."
    )

