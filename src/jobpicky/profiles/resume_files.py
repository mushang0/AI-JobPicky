from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath
from typing import cast
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile, is_zipfile

from pydantic import JsonValue
from pypdf import PdfReader

from ..contracts import ErrorCode
from ..contracts.common import JsonObject
from ..errors import ApplicationError

SUPPORTED_RESUME_EXTENSIONS = frozenset({".pdf", ".docx", ".txt", ".md"})
PROFILE_IMPORT_MAX_BYTES = 10 * 1024 * 1024
PROFILE_IMPORT_MAX_PDF_PAGES = 50
PROFILE_IMPORT_MAX_TEXT_CHARS = 50_000
_WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


@dataclass(frozen=True, slots=True)
class ExtractedResume:
    text: str
    warnings: tuple[str, ...] = ()


def extract_resume_text(
    filename: str,
    content: bytes,
    *,
    max_bytes: int,
    max_pdf_pages: int,
    max_text_chars: int,
) -> ExtractedResume:
    if len(content) > max_bytes:
        raise ApplicationError(
            ErrorCode.VALIDATION_ERROR,
            "resume file is too large",
            status_code=413,
            details={"max_bytes": max_bytes},
        )
    if not content:
        raise _parse_error("resume file is empty")

    extension = PurePath(filename).suffix.casefold()
    if extension not in SUPPORTED_RESUME_EXTENSIONS:
        supported_extensions = cast(list[JsonValue], sorted(SUPPORTED_RESUME_EXTENSIONS))
        raise ApplicationError(
            ErrorCode.VALIDATION_ERROR,
            "unsupported resume file format",
            status_code=415,
            details={"supported_extensions": supported_extensions},
        )

    if extension == ".pdf":
        text, warnings = _extract_pdf(content, max_pdf_pages)
    elif extension == ".docx":
        text, warnings = _extract_docx(content, max_text_chars)
    else:
        text, warnings = _extract_plain_text(content), []

    text = _clean_text(text)
    if len(text) < 20:
        raise _parse_error("resume did not contain enough extractable text")
    if len(text) > max_text_chars:
        text = text[:max_text_chars].rstrip()
        warnings.append(
            f"简历文本较长，仅解析了前 {max_text_chars} 个字符，请重点检查后半部分经历。"
        )
    return ExtractedResume(text=text, warnings=tuple(warnings))


def _extract_pdf(content: bytes, max_pdf_pages: int) -> tuple[str, list[str]]:
    if not content.lstrip().startswith(b"%PDF-"):
        raise _parse_error("file extension does not match PDF content")
    try:
        reader = PdfReader(BytesIO(content), strict=False)
        if reader.is_encrypted:
            raise _parse_error("encrypted PDF files are not supported")
        if len(reader.pages) > max_pdf_pages:
            raise _parse_error(
                "PDF exceeds page limit",
                details={"max_pdf_pages": max_pdf_pages},
            )
        page_text = [page.extract_text() or "" for page in reader.pages]
    except ApplicationError:
        raise
    except Exception as exc:
        raise _parse_error("PDF could not be read") from exc

    blank_pages = sum(not value.strip() for value in page_text)
    warnings = []
    if blank_pages:
        warnings.append(f"PDF 中有 {blank_pages} 页未提取到文本，请检查是否包含扫描页。")
    return "\n".join(page_text), warnings


def _extract_docx(content: bytes, max_text_chars: int) -> tuple[str, list[str]]:
    source = BytesIO(content)
    if not is_zipfile(source):
        raise _parse_error("file extension does not match DOCX content")
    source.seek(0)
    try:
        with ZipFile(source) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > max(2_000_000, max_text_chars * 30):
                raise _parse_error("DOCX document content is too large")
            document = archive.read(info)
        root = ElementTree.fromstring(document)
    except ApplicationError:
        raise
    except (BadZipFile, KeyError, ElementTree.ParseError, OSError) as exc:
        raise _parse_error("DOCX could not be read") from exc

    paragraph_tag = f"{{{_WORD_NAMESPACE}}}p"
    text_tag = f"{{{_WORD_NAMESPACE}}}t"
    paragraphs = [
        "".join(node.text or "" for node in paragraph.iter(text_tag))
        for paragraph in root.iter(paragraph_tag)
    ]
    return "\n".join(paragraphs), []


def _extract_plain_text(content: bytes) -> str:
    encodings = ["utf-8-sig"]
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings.append("utf-16")
    encodings.append("gb18030")
    for encoding in encodings:
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise _parse_error("text resume encoding is not supported")


def _clean_text(value: str) -> str:
    lines = [" ".join(line.replace("\x00", "").split()) for line in value.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _parse_error(
    message: str,
    *,
    details: JsonObject | None = None,
) -> ApplicationError:
    error_details: JsonObject = {"stage": "EXTRACT"}
    error_details.update(details or {})
    return ApplicationError(
        ErrorCode.PROFILE_PARSE_FAILED,
        message,
        status_code=422,
        details=error_details,
    )


__all__ = [
    "ExtractedResume",
    "PROFILE_IMPORT_MAX_BYTES",
    "PROFILE_IMPORT_MAX_PDF_PAGES",
    "PROFILE_IMPORT_MAX_TEXT_CHARS",
    "SUPPORTED_RESUME_EXTENSIONS",
    "extract_resume_text",
]
