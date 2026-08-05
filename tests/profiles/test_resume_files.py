from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

import pypdfium2 as pdfium
import pytest

from jobpicky.contracts import ErrorCode
from jobpicky.errors import ApplicationError
from jobpicky.profiles.resume_files import (
    PROFILE_IMPORT_MAX_PDF_PAGES,
    extract_resume_text,
    render_pdf_pages,
)


def test_renders_pdf_pages_as_ephemeral_png_images() -> None:
    rendered = render_pdf_pages(
        "resume.pdf",
        _blank_pdf(),
        max_bytes=1_000_000,
        max_pdf_pages=5,
    )

    assert len(rendered.image_pages) == 1
    assert rendered.image_pages[0].startswith(b"\x89PNG\r\n\x1a\n")


def test_extracts_docx_and_plain_text_without_persisting_files() -> None:
    docx = extract_resume_text(
        "resume.docx",
        _docx_with_text("使用 FastAPI 开发后端接口和异步任务服务"),
        max_bytes=1_000_000,
        max_text_chars=1000,
    )
    text = extract_resume_text(
        "resume.txt",
        "熟悉 PostgreSQL 和异步任务开发。".encode(),
        max_bytes=1_000_000,
        max_text_chars=1000,
    )

    assert docx.text == "使用 FastAPI 开发后端接口和异步任务服务"
    assert text.text == "熟悉 PostgreSQL 和异步任务开发。"


def test_rejects_unsupported_oversized_and_non_text_resumes() -> None:
    with pytest.raises(ApplicationError) as unsupported:
        extract_resume_text(
            "resume.doc",
            b"legacy word content",
            max_bytes=100,
            max_text_chars=1000,
        )
    assert unsupported.value.code == str(ErrorCode.VALIDATION_ERROR)
    assert unsupported.value.status_code == 415

    with pytest.raises(ApplicationError) as oversized:
        extract_resume_text(
            "resume.txt",
            b"x" * 101,
            max_bytes=100,
            max_text_chars=1000,
        )
    assert oversized.value.status_code == 413

    with pytest.raises(ApplicationError) as invalid_pdf:
        render_pdf_pages(
            "resume.pdf",
            b"%PDF-not-a-real-pdf",
            max_bytes=1_000_000,
            max_pdf_pages=5,
        )
    assert invalid_pdf.value.code == str(ErrorCode.PROFILE_PARSE_FAILED)


def test_enforces_pdf_page_and_model_text_limits() -> None:
    with pytest.raises(ApplicationError) as too_many_pages:
        render_pdf_pages(
            "resume.pdf",
            _blank_pdf(page_count=PROFILE_IMPORT_MAX_PDF_PAGES + 1),
            max_bytes=1_000_000,
            max_pdf_pages=PROFILE_IMPORT_MAX_PDF_PAGES,
        )
    assert too_many_pages.value.code == str(ErrorCode.PROFILE_PARSE_FAILED)
    assert too_many_pages.value.details["max_pdf_pages"] == 4

    truncated = extract_resume_text(
        "resume.md",
        ("Python FastAPI PostgreSQL " * 4).encode(),
        max_bytes=1_000_000,
        max_text_chars=30,
    )
    assert len(truncated.text) <= 30
    assert any("仅解析" in warning for warning in truncated.warnings)


def _blank_pdf(page_count: int = 1) -> bytes:
    document = pdfium.PdfDocument.new()
    for _ in range(page_count):
        document.new_page(width=612, height=792)
    with TemporaryDirectory() as directory:
        path = Path(directory) / "resume.pdf"
        document.save(path)
        content = path.read_bytes()
    document.close()
    return content


def _docx_with_text(text: str) -> bytes:
    output = BytesIO()
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    )
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", document)
    return output.getvalue()
