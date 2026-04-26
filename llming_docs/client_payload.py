"""Serialize a ``Document`` for the browser, attaching a render view for
binary-backed types.

The frontend table plugin needs a JSON-shaped snapshot to render — but
we deliberately don't ship a heavy XLSX JS library. Instead the server
attaches a pre-rendered view next to the canonical ``xlsx_b64`` so the
browser can read it directly.

This view:
  * is **not** the canonical storage (xlsx_b64 still is);
  * is regenerated on every emit (cheap — it's a sparse dict);
  * never leaves the wire / IDB — when the doc is loaded back, only
    ``xlsx_b64`` is the source of truth, the view is recomputed from it.
"""
from __future__ import annotations

from typing import Any

from llming_docs.document_store import Document


def client_doc_payload(doc: Document) -> dict:
    """Return ``doc.model_dump()`` with a ``data.view`` field attached for
    types that need a derived render shape.

    Lodge's ``_doc_notify`` calls this in place of plain ``model_dump``.
    Hosts that don't render docs in a browser can keep using ``model_dump``
    directly — the view is purely a UI affordance.
    """
    payload = doc.model_dump()
    if doc.type == "table":
        view = _render_view_for_table(doc)
        if view is not None:
            payload.setdefault("data", {})
            # ``data.view`` mirrors the legacy JSON shape (sheets / columns /
            # rows / cells) so the existing renderer reads it without
            # changes — no JS XLSX library needed.
            payload["data"]["view"] = view
    return payload


def _render_view_for_table(doc: Document) -> dict | None:
    """Build a sparse JSON snapshot from the workbook in ``doc.data``.

    Returns None if the doc isn't actually XLSX-backed (e.g. a brand-new
    legacy doc that hasn't been touched yet). The frontend then falls
    back to its legacy renderer for that one doc.
    """
    data = doc.data or {}
    if not isinstance(data, dict) or "xlsx_b64" not in data:
        return None
    from llming_docs.sheet.xlsx_storage import workbook_from_b64
    from llming_docs.sheet.xlsx_view import full_view
    try:
        wb = workbook_from_b64(data["xlsx_b64"])
    except Exception:
        return None
    return full_view(wb)
