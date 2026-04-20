"""PDF read + render subpackage.

Permissively-licensed PDF support for llming-docs. Uses pypdfium2
(Apache-2.0) for rendering and pdfplumber (MIT) for text/layout/image
extraction. Never uses pymupdf/fitz — that library is AGPL and forbidden
everywhere in this repo.

Public API:
    open_pdf(source) -> PdfHandle
    render_page(handle, page_index, scale=2.0, crop=None) -> bytes (PNG)
    extract_text(handle, page_index=None) -> str
    extract_images(handle, page_index=None) -> list[PdfImage]
    page_count(handle) -> int

A *source* is either ``bytes`` or a ``str``/``Path`` filesystem path.
"""
from llming_docs.pdf.reader import (
    PdfHandle,
    PdfImage,
    PdfWord,
    extract_images,
    extract_text,
    extract_words,
    open_pdf,
    page_count,
    page_size,
    render_page,
)

__all__ = [
    "PdfHandle",
    "PdfImage",
    "PdfWord",
    "extract_images",
    "extract_text",
    "extract_words",
    "open_pdf",
    "page_count",
    "page_size",
    "render_page",
]
