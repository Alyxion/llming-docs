"""PDF reader — wraps pypdfium2 (Apache-2.0) + pdfplumber (MIT).

Call sites across the project should use this module instead of pymupdf
(which is AGPL and forbidden). The API covers the few things we actually
do: open a PDF from bytes/path, render a page (optionally cropped) to
PNG bytes, extract text, and extract embedded images.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Union

Source = Union[bytes, str, Path]


@dataclass
class PdfHandle:
    """Opaque handle returned by ``open_pdf``.

    Carries both the raw bytes (for pdfplumber) and a pypdfium2 document
    object (for rendering). Keep the handle alive until all rendering is
    done; close it explicitly with ``close()`` or let it garbage-collect.
    """
    raw: bytes
    _pdfium_doc: object = None  # pypdfium2.PdfDocument

    def close(self) -> None:
        doc = self._pdfium_doc
        self._pdfium_doc = None
        if doc is not None:
            doc.close()


@dataclass
class PdfImage:
    """An image extracted from a PDF page."""
    page_index: int
    data: bytes            # raw image bytes (PNG or original embedded format)
    mime: str              # e.g. "image/png", "image/jpeg"
    width: int
    height: int
    bbox: tuple[float, float, float, float] | None = None  # (x0, y0, x1, y1)
    name: str = ""


def _to_bytes(source: Source) -> bytes:
    if isinstance(source, bytes):
        return source
    return Path(source).read_bytes()


def open_pdf(source: Source) -> PdfHandle:
    """Open a PDF from bytes or a filesystem path.

    The returned handle is safe to pass to every other function in this
    module. pypdfium2's PdfDocument is created lazily on first render to
    keep pure-text extraction cheap.
    """
    return PdfHandle(raw=_to_bytes(source))


def _ensure_pdfium(handle: PdfHandle):
    if handle._pdfium_doc is None:
        import pypdfium2 as pdfium
        handle._pdfium_doc = pdfium.PdfDocument(handle.raw)
    return handle._pdfium_doc


def page_count(handle: PdfHandle) -> int:
    doc = _ensure_pdfium(handle)
    return len(doc)


def render_page(
    handle: PdfHandle,
    page_index: int = 0,
    scale: float = 2.0,
    crop: tuple[float, float, float, float] | None = None,
) -> bytes:
    """Render a page to PNG bytes.

    Args:
        handle: open PDF handle.
        page_index: zero-based page index.
        scale: render scale factor (2.0 ≈ 144 DPI; pypdfium2 default is 1.0 = 72 DPI).
        crop: optional ``(x0, y0, x1, y1)`` in PDF points. Coordinates use
            PDF convention (origin bottom-left). If supplied, the returned
            image is the cropped region only.

    Returns:
        PNG-encoded bytes.
    """
    doc = _ensure_pdfium(handle)
    page = doc[page_index]

    bitmap = page.render(scale=scale)
    pil = bitmap.to_pil()

    if crop is not None:
        x0, y0, x1, y1 = crop
        page_h = page.get_height()
        # Convert PDF (bottom-left origin) -> PIL (top-left origin).
        left = int(x0 * scale)
        top = int((page_h - y1) * scale)
        right = int(x1 * scale)
        bottom = int((page_h - y0) * scale)
        pil = pil.crop((left, top, right, bottom))

    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return buf.getvalue()


def extract_text(handle: PdfHandle, page_index: int | None = None) -> str:
    """Extract text from the whole document or a single page.

    Uses pdfplumber which preserves reading order better than pypdfium2's
    raw text extraction. Returns an empty string if the PDF has no text
    (e.g. scanned image-only PDFs).
    """
    import pdfplumber
    out: list[str] = []
    with pdfplumber.open(io.BytesIO(handle.raw)) as pdf:
        pages = [pdf.pages[page_index]] if page_index is not None else pdf.pages
        for p in pages:
            txt = p.extract_text() or ""
            out.append(txt)
    return "\n".join(out)


@dataclass
class PdfWord:
    """A text word with its bounding box and font metadata."""
    page_index: int
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    font_name: str = ""
    font_size: float = 0.0


def extract_words(
    handle: PdfHandle,
    page_index: int | None = None,
    include_font_info: bool = False,
) -> list[PdfWord]:
    """Extract words with bounding boxes (pdfplumber).

    Coordinates use PDF point units with the top-left origin that
    pdfplumber returns (``x0,top,x1,bottom``). Font name/size are only
    populated when ``include_font_info=True`` to keep the common case fast.
    """
    import pdfplumber
    extras = ["fontname", "size"] if include_font_info else []
    out: list[PdfWord] = []
    with pdfplumber.open(io.BytesIO(handle.raw)) as pdf:
        indices = [page_index] if page_index is not None else range(len(pdf.pages))
        for idx in indices:
            page = pdf.pages[idx]
            words = page.extract_words(extra_attrs=extras) if extras else page.extract_words()
            for w in words or []:
                if not w.get("text"):
                    continue
                out.append(PdfWord(
                    page_index=idx,
                    text=w["text"],
                    x0=float(w["x0"]),
                    y0=float(w["top"]),
                    x1=float(w["x1"]),
                    y1=float(w["bottom"]),
                    font_name=str(w.get("fontname") or ""),
                    font_size=float(w.get("size") or 0),
                ))
    return out


def page_size(handle: PdfHandle, page_index: int = 0) -> tuple[float, float]:
    """Return ``(width, height)`` in PDF points for *page_index*."""
    doc = _ensure_pdfium(handle)
    page = doc[page_index]
    return float(page.get_width()), float(page.get_height())


def extract_images(
    handle: PdfHandle,
    page_index: int | None = None,
) -> list[PdfImage]:
    """Extract embedded images from the whole document or a single page.

    Images are returned in reading order per page. The raw bytes are
    always PNG-encoded (pdfplumber renders the image region) so callers
    can consume them uniformly.
    """
    import pdfplumber
    result: list[PdfImage] = []
    with pdfplumber.open(io.BytesIO(handle.raw)) as pdf:
        indices = [page_index] if page_index is not None else range(len(pdf.pages))
        for idx in indices:
            page = pdf.pages[idx]
            for img in page.images:
                bbox = (
                    float(img["x0"]),
                    float(img["top"]),
                    float(img["x1"]),
                    float(img["bottom"]),
                )
                cropped = page.crop(bbox).to_image(resolution=200)
                buf = io.BytesIO()
                cropped.save(buf, format="PNG")
                result.append(PdfImage(
                    page_index=idx,
                    data=buf.getvalue(),
                    mime="image/png",
                    width=int(bbox[2] - bbox[0]),
                    height=int(bbox[3] - bbox[1]),
                    bbox=bbox,
                    name=img.get("name", "") or "",
                ))
    return result
