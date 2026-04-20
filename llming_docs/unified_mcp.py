"""UnifiedDocumentMCP -- single MCP server replacing all type-specific document MCPs.

Provides three tools (update_document, read_document, undo_document) that work
across all document types using a slash-separated path language for surgical edits.
"""

import copy
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from llming_models.tools.mcp import InProcessMCPServer
from llming_docs.document_store import DocumentSessionStore, Document

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _resolve_path(data: Any, path_str: str) -> Tuple[Any, Any]:
    """Resolve a slash-separated path against document data.

    Returns ``(parent, key)`` where ``parent[key]`` is the target value.

    For each path segment the resolution strategy is:
    1. If *current* is a list and *segment* is a numeric string -> int index
    2. If *current* is a list of dicts -> match first item whose ``id`` field
       equals *segment*, then try ``name`` field
    3. If *current* is a dict -> direct key access

    Raises ``ValueError`` with a descriptive message when resolution fails.
    """
    if not path_str:
        raise ValueError("Path cannot be empty")

    segments = path_str.split("/")
    current = data
    parent: Any = None
    key: Any = None

    for depth, segment in enumerate(segments):
        parent = current
        partial = "/".join(segments[: depth + 1])

        if isinstance(current, list):
            # Numeric index
            if segment.isdigit() or (segment.startswith("-") and segment[1:].isdigit()):
                idx = int(segment)
                if idx < 0 or idx >= len(current):
                    raise ValueError(
                        f"Index {idx} out of range at '{partial}' "
                        f"(array length {len(current)})"
                    )
                key = idx
                current = current[idx]
                continue

            # Named lookup: try 'id' field, then 'name' field
            matched = False
            for i, item in enumerate(current):
                if isinstance(item, dict):
                    if item.get("id") == segment or str(item.get("id")) == segment:
                        key = i
                        current = current[i]
                        matched = True
                        break
            if not matched:
                for i, item in enumerate(current):
                    if isinstance(item, dict):
                        if item.get("name") == segment or str(item.get("name")) == segment:
                            key = i
                            current = current[i]
                            matched = True
                            break
            if not matched:
                ids = []
                for item in current:
                    if isinstance(item, dict):
                        item_id = item.get("id")
                        item_name = item.get("name")
                        label = str(item_id) if item_id is not None else str(item_name) if item_name is not None else None
                        if label is not None:
                            ids.append(label)
                available = ", ".join(ids[:10]) if ids else "(no id/name fields)"
                raise ValueError(
                    f"No item with id or name '{segment}' at '{partial}'. "
                    f"Available: {available}"
                )
            continue

        if isinstance(current, dict):
            if segment not in current:
                raise ValueError(
                    f"Key '{segment}' not found at '{partial}'. "
                    f"Available keys: {', '.join(list(current.keys())[:15])}"
                )
            key = segment
            current = current[segment]
            continue

        raise ValueError(
            f"Cannot traverse into {type(current).__name__} at '{partial}'"
        )

    return parent, key


def _resolve_parent_path(data: Any, path_str: str) -> Tuple[Any, str]:
    """Resolve all segments except the last, returning (parent_container, last_segment).

    Used by add/remove/move where the last segment identifies the target
    within its parent container rather than a value to descend into.
    """
    segments = path_str.split("/")
    if len(segments) == 1:
        return data, segments[0]

    parent_path = "/".join(segments[:-1])
    parent, parent_key = _resolve_path(data, parent_path)
    # The resolved value is parent[parent_key]
    container = parent[parent_key]
    return container, segments[-1]


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

def _apply_set(data: Any, path: str, value: Any) -> None:
    """Replace the value at *path*."""
    parent, key = _resolve_path(data, path)
    parent[key] = value


def _apply_add(data: Any, path: str, value: Any, position: Optional[int]) -> None:
    """Insert *value* into a list at *path* (at *position*), or set a dict key.

    When *path* resolves to an existing list, the value is inserted into that
    list.  When the parent of the last segment is a dict and the key does not
    yet exist, it is created.
    """
    # First, try to resolve the full path.  If it points to a list we insert
    # into that list directly.
    try:
        parent, key = _resolve_path(data, path)
        target = parent[key]
        if isinstance(target, list):
            idx = position if position is not None else len(target)
            if idx < 0 or idx > len(target):
                raise ValueError(
                    f"Insert position {idx} out of range for array of length "
                    f"{len(target)} at '{path}'"
                )
            target.insert(idx, value)
            return
    except ValueError:
        # Path doesn't fully resolve — fall through to parent-based add
        pass

    # Path doesn't point to a list (or doesn't exist yet).
    # Resolve the parent and use the last segment as key.
    segments = path.split("/")
    if len(segments) == 1:
        container = data
        last_seg = segments[0]
    else:
        parent_path = "/".join(segments[:-1])
        parent, parent_key = _resolve_path(data, parent_path)
        container = parent[parent_key]
        last_seg = segments[-1]

    if isinstance(container, dict):
        container[last_seg] = value
    elif isinstance(container, list):
        idx = position if position is not None else len(container)
        if idx < 0 or idx > len(container):
            raise ValueError(
                f"Insert position {idx} out of range for array of length "
                f"{len(container)} at '{path}'"
            )
        container.insert(idx, value)
    else:
        raise ValueError(
            f"Cannot add to {type(container).__name__} at '{path}'; "
            f"expected a list or dict"
        )


def _apply_remove(data: Any, path: str) -> None:
    """Remove the item at *path*."""
    parent, key = _resolve_path(data, path)
    if isinstance(parent, list):
        parent.pop(key)
    elif isinstance(parent, dict):
        del parent[key]
    else:
        raise ValueError(
            f"Cannot remove from {type(parent).__name__} at '{path}'"
        )


def _apply_move(data: Any, path: str, position: int) -> None:
    """Move an array item at *path* to *position*."""
    parent, key = _resolve_path(data, path)
    if not isinstance(parent, list):
        raise ValueError(
            f"Move only works on array items; parent at '{path}' is "
            f"{type(parent).__name__}"
        )
    if position < 0 or position >= len(parent):
        raise ValueError(
            f"Move target position {position} out of range "
            f"(array length {len(parent)}) at '{path}'"
        )
    item = parent.pop(key)
    parent.insert(position, item)


def _apply_operation(data: Any, op: Dict[str, Any]) -> None:
    """Apply a single operation dict to *data* (mutates in-place)."""
    op_type = op["op"]
    path = op["path"]

    if op_type == "set":
        if "value" not in op:
            raise ValueError("'set' operation requires a 'value' field")
        _apply_set(data, path, op["value"])
    elif op_type == "add":
        if "value" not in op:
            raise ValueError("'add' operation requires a 'value' field")
        _apply_add(data, path, op["value"], op.get("position"))
    elif op_type == "remove":
        _apply_remove(data, path)
    elif op_type == "move":
        if "position" not in op:
            raise ValueError("'move' operation requires a 'position' field")
        _apply_move(data, path, op["position"])
    else:
        raise ValueError(f"Unknown operation type '{op_type}'")


# ---------------------------------------------------------------------------
# Recursive text search
# ---------------------------------------------------------------------------

def _search_strings(data: Any, query: str, prefix: str = "") -> List[Dict[str, str]]:
    """Recursively search all string values, returning matching paths + snippets."""
    results: List[Dict[str, str]] = []
    query_lower = query.lower()

    if isinstance(data, dict):
        for k, v in data.items():
            child_path = f"{prefix}/{k}" if prefix else k
            results.extend(_search_strings(v, query, child_path))
    elif isinstance(data, list):
        for i, v in enumerate(data):
            child_path = f"{prefix}/{i}" if prefix else str(i)
            results.extend(_search_strings(v, query, child_path))
    elif isinstance(data, str):
        if query_lower in data.lower():
            # Create a snippet around the match
            lower = data.lower()
            idx = lower.find(query_lower)
            start = max(0, idx - 40)
            end = min(len(data), idx + len(query) + 40)
            snippet = data[start:end]
            if start > 0:
                snippet = "..." + snippet
            if end < len(data):
                snippet = snippet + "..."
            results.append({"path": prefix, "snippet": snippet})

    return results


# ---------------------------------------------------------------------------
# Structural summaries
# ---------------------------------------------------------------------------

def _summarize_table(data: Dict[str, Any]) -> Dict[str, Any]:
    """Structural summary for table documents."""
    if "sheets" in data:
        sheets = []
        for sheet in data["sheets"]:
            columns = sheet.get("columns", [])
            col_names = []
            for c in columns:
                if isinstance(c, dict):
                    col_names.append(c.get("key", c.get("label", "?")))
                elif isinstance(c, str):
                    col_names.append(c)
            sheets.append({
                "name": sheet.get("name", ""),
                "columns": col_names,
                "row_count": len(sheet.get("rows", [])),
            })
        return {"type": "table", "multi_sheet": True, "sheets": sheets}
    columns = data.get("columns", [])
    col_names = []
    for c in columns:
        if isinstance(c, dict):
            col_names.append(c.get("key", c.get("label", "?")))
        elif isinstance(c, str):
            col_names.append(c)
    return {
        "type": "table",
        "multi_sheet": False,
        "columns": col_names,
        "row_count": len(data.get("rows", [])),
    }


def _summarize_presentation(data: Dict[str, Any]) -> Dict[str, Any]:
    """Structural summary for presentation documents."""
    slides = []
    for slide in data.get("slides", []):
        slides.append({
            "id": slide.get("id", ""),
            "title": slide.get("title", ""),
            "element_count": len(slide.get("elements", [])),
        })
    return {"type": "presentation", "slide_count": len(slides), "slides": slides}


def _summarize_text_doc(data: Dict[str, Any]) -> Dict[str, Any]:
    """Structural summary for text documents."""
    sections = []
    for section in data.get("sections", []):
        entry: Dict[str, Any] = {
            "id": section.get("id", ""),
            "type": section.get("type", ""),
        }
        if section.get("type") == "heading":
            entry["text"] = section.get("content", section.get("text", ""))
        sections.append(entry)
    return {"type": "text_doc", "section_count": len(sections), "sections": sections}


def _summarize_email(data: Dict[str, Any]) -> Dict[str, Any]:
    """Structural summary for email drafts."""
    return {
        "type": "email_draft",
        "to": data.get("to", []),
        "cc": data.get("cc", []),
        "bcc": data.get("bcc", []),
        "subject": data.get("subject", ""),
        "body_length": len(data.get("body_html", "")),
        "attachment_count": len(data.get("attachments", [])),
    }


def _summarize_plotly(data: Dict[str, Any]) -> Dict[str, Any]:
    """Structural summary for Plotly charts."""
    traces = []
    for i, trace in enumerate(data.get("data", [])):
        entry: Dict[str, Any] = {"index": i, "type": trace.get("type", "")}
        if "name" in trace:
            entry["name"] = trace["name"]
        for dim in ("x", "y", "z", "values", "labels"):
            if dim in trace and isinstance(trace[dim], list):
                entry[f"{dim}_count"] = len(trace[dim])
        traces.append(entry)
    return {"type": "plotly", "trace_count": len(traces), "traces": traces}


def _summarize_html(data: Dict[str, Any]) -> Dict[str, Any]:
    """Structural summary for HTML documents."""
    summary: Dict[str, Any] = {"type": "html"}
    if "title" in data:
        summary["title"] = data["title"]
    for field in ("html", "content", "css", "js"):
        if field in data and isinstance(data[field], str):
            summary[f"{field}_length"] = len(data[field])
    return summary


_SUMMARIZERS: Dict[str, Any] = {
    "table": _summarize_table,
    "presentation": _summarize_presentation,
    "text_doc": _summarize_text_doc,
    "email_draft": _summarize_email,
    "plotly": _summarize_plotly,
    "html": _summarize_html,
}


def _summarize_document(doc: Document) -> Dict[str, Any]:
    """Build a structural summary for any document."""
    data = doc.data
    if not isinstance(data, dict):
        return {"type": doc.type, "data_type": type(data).__name__}
    summarizer = _SUMMARIZERS.get(doc.type)
    if summarizer is not None:
        return summarizer(data)
    # Fallback: top-level keys
    return {"type": doc.type, "top_level_keys": list(data.keys())}


# ---------------------------------------------------------------------------
# Tool descriptions
# ---------------------------------------------------------------------------

_UPDATE_DOCUMENT_DESCRIPTION = """\
Batch-edit a document using surgical operations. All operations are applied \
atomically -- if any operation fails or validation fails afterward, the \
entire batch is rolled back and the document stays unchanged.

PATH LANGUAGE: Paths use slash-separated segments resolved against doc.data:
- Numeric index into arrays: "slides/0", "data/2"
- Named lookup by 'id' field: "slides/s1" (finds slide with id="s1")
- Named lookup by 'name' field: "sheets/Q1" (finds sheet with name="Q1")
- Dict key access: "slides/s1/title", "layout/xaxis/title"
- Deeply nested: "slides/s1/elements/2/content", "sheets/Q1/rows/3/revenue"
- Top-level keys: "to", "subject", "body_html"

OPERATIONS:
- set: Replace value at path.
  Example: {op: "set", path: "slides/s1/title", value: "New Title"}
  Example: {op: "set", path: "sheets/Q1/rows/3/revenue", value: 42000}
  Example: {op: "set", path: "subject", value: "Updated Subject"}
- add: Insert into array (at position, default=end) or add dict key.
  Example: {op: "add", path: "slides", value: {id: "s3", title: "New"}, position: 1}
  Example: {op: "add", path: "data", value: {type: "bar", x: [...], y: [...]}}
- remove: Remove item at path.
  Example: {op: "remove", path: "slides/s2"}
  Example: {op: "remove", path: "sections/sec3"}
- move: Reorder array item to new position.
  Example: {op: "move", path: "slides/s1", position: 0}

COMMON PATTERNS:
- Change a cell: op=set, path="sheets/SheetName/rows/3/column_key"
- Change slide title: op=set, path="slides/s1/title", value="..."
- Add a slide: op=add, path="slides", value={id: "...", title: "...", elements: [...]}
- Remove a trace: op=remove, path="data/2"
- Edit email body: op=set, path="body_html", value="<p>...</p>"
- Add a CC recipient: op=add, path="cc", value="user@example.com"
- Reorder slides: op=move, path="slides/s3", position=0\
"""

_READ_DOCUMENT_DESCRIPTION = """\
Read specific parts of a document, search its content, or get a structural \
summary. Use this to inspect a document before editing.

MODES:
1. Paths mode: Provide 'paths' to read specific values.
   Example paths: ["slides/0", "sheets/Q1/rows/0", "subject", "data/0/x"]
2. Search mode: Provide 'query' to find matching text across the document.
   Returns matching paths and text snippets.
3. Summary mode: Omit both 'paths' and 'query' to get a structural overview.
   Shows slide IDs/titles, sheet names/columns/row counts, section outlines, etc.

PATH LANGUAGE (same as update_document):
- "slides/s1/title" -- slide title by ID
- "sheets/Q1/rows/0" -- first row of sheet named Q1
- "data/0" -- first Plotly trace
- "sections/sec2/content" -- section content by ID
- "to", "subject" -- top-level email fields\
"""

_UNDO_DOCUMENT_DESCRIPTION = """\
Undo the most recent change to a document, restoring the previous version. \
Each call undoes one step. The undo itself creates a new version number. \
Returns error if there is no history to undo.\
"""


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

class UnifiedDocumentMCP(InProcessMCPServer):
    """Unified MCP server for reading, editing, and undoing any document type.

    Replaces the type-specific MCPs (PlotlyDocumentMCP, PresentationMCP,
    TableDocumentMCP, TextDocMCP, HtmlDocumentMCP, EmailDraftMCP) with three
    general-purpose tools that work across all document types.
    """

    def __init__(self, store: DocumentSessionStore) -> None:
        self._store = store

    async def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "update_document",
                "displayName": "Edit Document",
                "displayDescription": "Batch-edit a document with surgical operations",
                "icon": "edit_note",
                "description": _UPDATE_DOCUMENT_DESCRIPTION,
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "ID of the document to update",
                        },
                        "operations": {
                            "type": "array",
                            "description": "List of operations to apply atomically",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "op": {
                                        "type": "string",
                                        "enum": ["set", "add", "remove", "move"],
                                    },
                                    "path": {
                                        "type": "string",
                                        "description": "Slash-separated path into doc.data",
                                    },
                                    "value": {
                                        "description": "New value for set/add operations",
                                    },
                                    "position": {
                                        "type": "integer",
                                        "description": "Target position for add/move in arrays",
                                    },
                                },
                                "required": ["op", "path"],
                            },
                        },
                        "name": {
                            "type": "string",
                            "description": "Optional: rename the document",
                        },
                    },
                    "required": ["document_id", "operations"],
                },
            },
            {
                "name": "read_document",
                "displayName": "Read Document",
                "displayDescription": "Read parts of a document or get a structural summary",
                "icon": "description",
                "description": _READ_DOCUMENT_DESCRIPTION,
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "ID of the document to read",
                        },
                        "paths": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Paths to read, e.g. ['slides/0', 'sheets/Q1/rows/0']"
                            ),
                        },
                        "query": {
                            "type": "string",
                            "description": "Search text across all document content",
                        },
                    },
                    "required": ["document_id"],
                },
            },
            {
                "name": "undo_document",
                "displayName": "Undo",
                "displayDescription": "Restore the previous version of a document",
                "icon": "undo",
                "description": _UNDO_DOCUMENT_DESCRIPTION,
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "ID of the document to undo",
                        },
                    },
                    "required": ["document_id"],
                },
            },
        ]

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        if name == "update_document":
            return self._handle_update(arguments)
        if name == "read_document":
            return self._handle_read(arguments)
        if name == "undo_document":
            return self._handle_undo(arguments)
        return json.dumps({"error": f"Unknown tool: {name}"})

    # ------------------------------------------------------------------
    # update_document
    # ------------------------------------------------------------------

    def _handle_update(self, arguments: Dict[str, Any]) -> str:
        doc_id = arguments["document_id"]
        operations = arguments.get("operations", [])
        new_name = arguments.get("name")

        doc = self._store.get(doc_id)
        if doc is None:
            return json.dumps({
                "error": "document_not_found",
                "message": f"No document with id '{doc_id}'",
                "hint": "Check the document_id. Use the document list to find valid IDs.",
            })

        if not doc.editable:
            return json.dumps({
                "error": "not_editable",
                "message": f"Document '{doc.name}' is not editable (source: {doc.source})",
                "hint": "Uploaded and nudge-provided documents cannot be modified.",
            })

        if not operations and new_name is None:
            return json.dumps({
                "error": "no_operations",
                "message": "No operations or name change provided",
                "hint": "Provide at least one operation or a new name.",
            })

        # Deep copy for atomicity
        working_data = copy.deepcopy(doc.data)

        # Apply each operation
        for i, op in enumerate(operations):
            try:
                _apply_operation(working_data, op)
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                return json.dumps({
                    "error": "operation_failed",
                    "failed_operation": i,
                    "message": str(exc),
                    "hint": "Use read_document to inspect the current structure.",
                })

        # Validate the result via store.update (which calls validators)
        update_kwargs: Dict[str, Any] = {}
        if operations:
            update_kwargs["data"] = working_data
        if new_name is not None:
            update_kwargs["name"] = new_name

        result = self._store.update(doc_id, **update_kwargs)

        # result is None if doc vanished, list if validation errors, Document if OK
        if result is None:
            return json.dumps({
                "error": "document_not_found",
                "message": f"Document '{doc_id}' disappeared during update",
                "hint": "The document may have been deleted concurrently.",
            })

        if isinstance(result, list):
            # Validation errors -- the store did NOT persist the changes
            error_dicts = [
                {"code": e.code, "message": e.message, "hint": e.hint, "path": e.path}
                for e in result
            ]
            return json.dumps({
                "error": "validation_failed",
                "errors": error_dicts,
                "hint": "Batch was rolled back. Fix issues and retry.",
            })

        return json.dumps({
            "status": "updated",
            "document_id": result.id,
            "version": result.version,
            "operations_applied": len(operations),
        })

    # ------------------------------------------------------------------
    # read_document
    # ------------------------------------------------------------------

    def _handle_read(self, arguments: Dict[str, Any]) -> str:
        doc_id = arguments["document_id"]
        paths = arguments.get("paths")
        query = arguments.get("query")

        doc = self._store.get(doc_id)
        if doc is None:
            return json.dumps({
                "error": "document_not_found",
                "message": f"No document with id '{doc_id}'",
                "hint": "Check the document_id.",
            })

        # Paths mode
        if paths:
            values: Dict[str, Any] = {}
            for path in paths:
                try:
                    parent, key = _resolve_path(doc.data, path)
                    values[path] = parent[key]
                except (ValueError, KeyError, IndexError, TypeError) as exc:
                    values[path] = {"error": str(exc)}
            return json.dumps({
                "document_id": doc.id,
                "name": doc.name,
                "type": doc.type,
                "version": doc.version,
                "values": values,
            })

        # Search mode
        if query:
            matches = _search_strings(doc.data, query)
            return json.dumps({
                "document_id": doc.id,
                "name": doc.name,
                "type": doc.type,
                "version": doc.version,
                "query": query,
                "matches": matches,
            })

        # Summary mode
        summary = _summarize_document(doc)
        return json.dumps({
            "document_id": doc.id,
            "name": doc.name,
            "type": doc.type,
            "version": doc.version,
            "editable": doc.editable,
            "source": doc.source,
            "summary": summary,
        })

    # ------------------------------------------------------------------
    # undo_document
    # ------------------------------------------------------------------

    def _handle_undo(self, arguments: Dict[str, Any]) -> str:
        doc_id = arguments["document_id"]

        doc = self._store.get(doc_id)
        if doc is None:
            return json.dumps({
                "error": "document_not_found",
                "message": f"No document with id '{doc_id}'",
                "hint": "Check the document_id.",
            })

        result = self._store.undo(doc_id)
        if result is None:
            return json.dumps({
                "error": "no_history",
                "message": f"No undo history for document '{doc.name}'",
                "hint": "The document has not been modified yet or all history has been undone.",
            })

        return json.dumps({
            "status": "undone",
            "document_id": result.id,
            "version": result.version,
            "name": result.name,
        })
