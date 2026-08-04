from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from jobpicky.contracts import ErrorCode
from jobpicky.errors import ApplicationError
from jobpicky.profiles.resume_files import extract_resume_text


def test_extracts_pdf_docx_and_plain_text_without_persisting_files() -> None:
    pdf = extract_resume_text(
        "resume.pdf",
        _pdf_with_text("Python backend engineer"),
        max_bytes=1_000_000,
        max_pdf_pages=5,
        max_text_chars=1000,
    )
    docx = extract_resume_text(
        "resume.docx",
        _docx_with_text("使用 FastAPI 开发后端接口和异步任务服务"),
        max_bytes=1_000_000,
        max_pdf_pages=5,
        max_text_chars=1000,
    )
    text = extract_resume_text(
        "resume.txt",
        "熟悉 PostgreSQL 和异步任务开发。".encode(),
        max_bytes=1_000_000,
        max_pdf_pages=5,
        max_text_chars=1000,
    )

    assert pdf.text == "Python backend engineer"
    assert docx.text == "使用 FastAPI 开发后端接口和异步任务服务"
    assert text.text == "熟悉 PostgreSQL 和异步任务开发。"


def test_rejects_unsupported_oversized_and_non_text_resumes() -> None:
    with pytest.raises(ApplicationError) as unsupported:
        extract_resume_text(
            "resume.doc",
            b"legacy word content",
            max_bytes=100,
            max_pdf_pages=5,
            max_text_chars=1000,
        )
    assert unsupported.value.code == str(ErrorCode.VALIDATION_ERROR)
    assert unsupported.value.status_code == 415

    with pytest.raises(ApplicationError) as oversized:
        extract_resume_text(
            "resume.txt",
            b"x" * 101,
            max_bytes=100,
            max_pdf_pages=5,
            max_text_chars=1000,
        )
    assert oversized.value.status_code == 413

    with pytest.raises(ApplicationError) as empty_pdf:
        extract_resume_text(
            "resume.pdf",
            _blank_pdf(),
            max_bytes=1_000_000,
            max_pdf_pages=5,
            max_text_chars=1000,
        )
    assert empty_pdf.value.code == str(ErrorCode.PROFILE_PARSE_FAILED)


def test_enforces_pdf_page_and_model_text_limits() -> None:
    with pytest.raises(ApplicationError) as too_many_pages:
        extract_resume_text(
            "resume.pdf",
            _blank_pdf(page_count=2),
            max_bytes=1_000_000,
            max_pdf_pages=1,
            max_text_chars=1000,
        )
    assert too_many_pages.value.code == str(ErrorCode.PROFILE_PARSE_FAILED)

    truncated = extract_resume_text(
        "resume.md",
        ("Python FastAPI PostgreSQL " * 4).encode(),
        max_bytes=1_000_000,
        max_pdf_pages=5,
        max_text_chars=30,
    )
    assert len(truncated.text) <= 30
    assert any("仅解析" in warning for warning in truncated.warnings)


def _pdf_with_text(text: str) -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = stream
    writer.write(output)
    return output.getvalue()


def _blank_pdf(page_count: int = 1) -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=612, height=792)
    writer.write(output)
    return output.getvalue()


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
