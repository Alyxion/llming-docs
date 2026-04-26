"""Type-aware op dispatcher.

The ``creator_mcp.create_document`` and ``unified_mcp.update_document``
tools both apply LLM-emitted ops to a document. The vocabulary differs
by type:

  * ``table`` → openpyxl-native A1 paths handled by :mod:`sheet.xlsx_ops`
  * everything else → JSON-path ops handled by :func:`unified_mcp._apply_operation`

This module is the single dispatch point. Both tools call into it so the
unified ``operations`` payload Just Works regardless of doc type.
"""
from __future__ import annotations

import copy
import json
from typing import Any

from llming_docs.sheet.xlsx_ops import XlsxOpError, apply_operations as _apply_xlsx_ops
from llming_docs.sheet.xlsx_storage import (
    new_empty_workbook,
    workbook_from_b64,
    workbook_to_b64,
)


# ---------------------------------------------------------------------------
# Empty-doc templates per type
# ---------------------------------------------------------------------------
#
# ``create_document`` always starts from one of these, then applies the
# ``operations`` payload on top. Per-type empty shapes ensure that ops
# like ``set sections/-`` or ``add slides/-`` can land on a known parent
# container without the LLM having to bootstrap the whole structure
# itself.

def _empty_table_data() -> dict:
    """An empty XLSX workbook with one default sheet, base64-encoded."""
    return {"xlsx_b64": workbook_to_b64(new_empty_workbook())}


_EMPTY_TEMPLATES = {
    "text_doc":     lambda: {"sections": []},
    "table":        _empty_table_data,
    "plotly":       lambda: {"data": [], "layout": {}},
    "latex":        lambda: {"formula": ""},
    "html":         lambda: {"html": "", "css": "", "js": "", "title": ""},
    "presentation": lambda: {"slides": []},
    "email_draft":  lambda: {
        "subject": "", "to": [], "cc": [], "bcc": [],
        "body_html": "", "attachments": [],
    },
}


def empty_data_for(doc_type: str) -> dict:
    """Return the empty starting payload for ``doc_type``.

    Unknown types fall back to ``{}``; the validator will reject downstream
    if that's not appropriate, but this keeps the dispatcher generic.
    """
    factory = _EMPTY_TEMPLATES.get(doc_type)
    return factory() if factory else {}


# ---------------------------------------------------------------------------
# Apply operations — type-aware
# ---------------------------------------------------------------------------


def apply_operations_to_data(
    doc_type: str,
    data: Any,
    operations: list,
) -> tuple[Any, dict | None]:
    """Apply ``operations`` to ``data`` (deep-copied for atomicity).

    Returns ``(new_data, error_dict_or_None)``. When the second element is
    not None the caller MUST NOT persist ``new_data`` — the batch failed
    midway and we don't want partial state to land on the doc.

    Type-specific routing:

    * ``table`` — operations are openpyxl-native A1 paths. ``data`` must
      carry ``xlsx_b64`` (legacy JSON shapes should have been migrated
      before reaching this function).
    * everything else — ops are JSON-path ops dispatched through
      :func:`unified_mcp._apply_operation`.
    """
    if not isinstance(operations, list):
        return data, {
            "error": "invalid_operations",
            "message": "operations must be a list",
        }

    if doc_type == "table":
        return _apply_table_ops(data, operations)
    return _apply_json_ops(data, operations)


def _apply_table_ops(data: Any, operations: list) -> tuple[Any, dict | None]:
    """Apply XLSX ops to a table doc.

    Accepts either the canonical ``{xlsx_b64: ...}`` payload or a legacy
    ``{sheets: [...]}`` JSON shape. In the latter case the migration runs
    inline so the user's edit lands on the migrated workbook in one shot —
    the doc emerges in the new shape with the edit already applied. This
    is the catch-all for legacy docs that weren't migrated at the store
    boundary (e.g. a doc the client held in IDB from before this change
    and edited before the server saw it via ``restore_from_list``).
    """
    from llming_docs.sheet.xlsx_migrate import (
        is_legacy_json_table,
        migrate_legacy_json_to_workbook,
    )
    if isinstance(data, dict) and "xlsx_b64" in data:
        try:
            wb = workbook_from_b64(data["xlsx_b64"])
        except Exception as exc:
            return data, {
                "error": "xlsx_load_failed",
                "message": f"could not load workbook: {exc}",
                "hint": "Document data appears corrupt; ask the user to re-upload.",
            }
    elif is_legacy_json_table(data):
        wb = migrate_legacy_json_to_workbook(data)
    else:
        # Truly empty / unknown — start from a blank workbook.
        wb = new_empty_workbook()

    try:
        _apply_xlsx_ops(wb, operations)
    except XlsxOpError as exc:
        return data, {
            "error": "operation_failed",
            "message": str(exc),
            "hint": "Use read_document or query_cells to inspect the workbook.",
        }

    return {"xlsx_b64": workbook_to_b64(wb)}, None


def _apply_json_ops(data: Any, operations: list) -> tuple[Any, dict | None]:
    """Apply JSON-path ops to a non-table doc."""
    # Lazy import — avoids a circular dep with unified_mcp.
    from llming_docs.unified_mcp import _apply_operation

    working = copy.deepcopy(data)
    for i, op in enumerate(operations):
        try:
            _apply_operation(working, op)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            return data, {
                "error": "operation_failed",
                "failed_operation": i,
                "message": str(exc),
                "hint": "Use read_document to inspect the current structure.",
            }
    return working, None
