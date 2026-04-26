"""TextDocMCP -- in-process MCP server for editing text documents.

Mutation-handler contract
-------------------------
Every handler that changes the document MUST work on a deep copy of
``doc.data`` and only hand the copy to ``store.update``. Mutating
``doc.data`` in place breaks three things at once:

  * validation rollback — ``store.update`` rejects via
    ``validate_document``, but the live doc is already corrupt;
  * history capture — ``store.update`` does ``copy.deepcopy(doc.data)``
    to remember the *old* state, but the mutation already happened, so
    undo would no-op;
  * the response shape — ``store.update`` returns ``list[ValidationError]``
    or ``None`` on failure; ``updated.version`` then crashes with
    ``AttributeError`` and the LLM sees a 500 instead of a structured
    error it can self-correct from.

The :func:`_persist_data_change` helper at the bottom enforces this for
every handler — call it instead of touching ``store.update`` directly.
"""

import copy
import json
import logging
from typing import Any, Dict, List

from llming_models.tools.mcp import InProcessMCPServer
from llming_docs.document_store import DocumentSessionStore

logger = logging.getLogger(__name__)


class TextDocMCP(InProcessMCPServer):
    """MCP server that lets the LLM inspect and edit text documents."""

    def __init__(self, store: DocumentSessionStore) -> None:
        self._store = store

    async def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "text_doc_list_sections",
                "displayName": "List Sections",
                "displayDescription": "List all sections of a text document",
                "icon": "list_alt",
                "description": (
                    "List all sections in a text document. "
                    "Returns the id, type, and a short content preview for each section."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "The document ID of the text document",
                        },
                    },
                    "required": ["document_id"],
                },
            },
            {
                "name": "text_doc_get_section",
                "displayName": "Get Section",
                "displayDescription": "Get a section by id or index",
                "icon": "article",
                "description": (
                    "Get the full content of a specific section in a text document. "
                    "Specify either section_id or a zero-based index."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "The document ID of the text document",
                        },
                        "section_id": {
                            "type": "string",
                            "description": "ID of the section to retrieve",
                        },
                        "index": {
                            "type": "integer",
                            "description": "Zero-based index of the section to retrieve",
                        },
                    },
                    "required": ["document_id"],
                },
            },
            {
                "name": "text_doc_update_section",
                "displayName": "Update Section",
                "displayDescription": "Update a section's content or properties",
                "icon": "edit",
                "description": (
                    "Update a section in a text document. You can change its content, "
                    "type (heading, paragraph, list, table), level (for headings), "
                    "and other properties."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "The document ID of the text document",
                        },
                        "section_id": {
                            "type": "string",
                            "description": "ID of the section to update",
                        },
                        "updates": {
                            "type": "object",
                            "description": (
                                "Properties to update: content (string), type "
                                "(heading/paragraph/list/table), level (int for "
                                "headings), etc."
                            ),
                        },
                    },
                    "required": ["document_id", "section_id", "updates"],
                },
            },
            {
                "name": "text_doc_add_section",
                "displayName": "Add Section",
                "displayDescription": "Add a new section to the document",
                "icon": "add_circle",
                "description": (
                    "Add a new section to a text document. "
                    "Types: heading, paragraph, list, table, embed. "
                    "To include a chart or table from the conversation, use type='embed' "
                    "with ref=<document_id>. Do NOT copy/fetch the data — just reference it."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "The document ID of the text document",
                        },
                        "type": {
                            "type": "string",
                            "enum": ["heading", "paragraph", "list", "table", "embed"],
                            "description": (
                                "Section type. Use 'embed' to reference another "
                                "document (chart, table, etc.) by its ID."
                            ),
                        },
                        "content": {
                            "description": (
                                "Section content. String for heading/paragraph, "
                                "array of strings for list, array of arrays for table. "
                                "Not needed for embed (use $ref instead)."
                            ),
                        },
                        "ref": {
                            "type": "string",
                            "description": (
                                "Document ID to embed (for type 'embed'). "
                                "References any earlier document in the conversation."
                            ),
                        },
                        "position": {
                            "type": "integer",
                            "description": "Zero-based position to insert at (default: end)",
                        },
                        "level": {
                            "type": "integer",
                            "description": "Heading level (1-6), only used for type 'heading'",
                        },
                    },
                    "required": ["document_id", "type"],
                },
            },
            {
                "name": "text_doc_delete_section",
                "displayName": "Delete Section",
                "displayDescription": "Delete a section from the document",
                "icon": "delete",
                "description": "Delete a section from a text document by its ID.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "The document ID of the text document",
                        },
                        "section_id": {
                            "type": "string",
                            "description": "ID of the section to delete",
                        },
                    },
                    "required": ["document_id", "section_id"],
                },
            },
            {
                "name": "text_doc_move_section",
                "displayName": "Move Section",
                "displayDescription": "Move a section to a new position",
                "icon": "swap_vert",
                "description": (
                    "Move a section to a new position within a text document. "
                    "The section is removed from its current position and inserted "
                    "at the specified new_position index."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "The document ID of the text document",
                        },
                        "section_id": {
                            "type": "string",
                            "description": "ID of the section to move",
                        },
                        "new_position": {
                            "type": "integer",
                            "description": "Zero-based target position",
                        },
                    },
                    "required": ["document_id", "section_id", "new_position"],
                },
            },
            {
                "name": "text_doc_search",
                "displayName": "Search Document",
                "displayDescription": "Search document content",
                "icon": "search",
                "description": (
                    "Search the content of a text document for text matching "
                    "a query string. Returns matching sections with their IDs, "
                    "types, and content previews."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "The document ID of the text document",
                        },
                        "query": {
                            "type": "string",
                            "description": "Search query string (case-insensitive)",
                        },
                    },
                    "required": ["document_id", "query"],
                },
            },
        ]

    def _find_section(self, sections: List[Dict], section_id: str) -> tuple[int, Dict | None]:
        """Find a section by ID, returning (index, section) or (-1, None)."""
        for i, s in enumerate(sections):
            if s.get("id") == section_id:
                return i, s
        return -1, None

    def _section_preview(self, section: Dict) -> str:
        """Generate a short preview of a section's content."""
        if section.get("type") == "embed":
            ref = section.get("$ref", "")
            return f"[embed: {ref[:12]}...]" if len(ref) > 12 else f"[embed: {ref}]"
        content = section.get("content", "")
        if isinstance(content, list):
            if content and isinstance(content[0], list):
                # Table: show first row
                return f"[table: {len(content)} rows]"
            return ", ".join(str(item) for item in content[:3]) + ("..." if len(content) > 3 else "")
        text = str(content)
        return text[:80] + ("..." if len(text) > 80 else "")

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        if name == "text_doc_list_sections":
            doc = self._store.get(arguments["document_id"])
            if not doc:
                return json.dumps({"error": "Document not found"})
            if doc.type not in ("text_doc", "word"):
                return json.dumps({"error": f"Document is type '{doc.type}', not 'text_doc'"})
            data = doc.data or {}
            sections = data.get("sections", [])
            result = []
            for s in sections:
                result.append({
                    "id": s.get("id", ""),
                    "type": s.get("type", ""),
                    "preview": self._section_preview(s),
                })
            return json.dumps({
                "document_id": doc.id,
                "section_count": len(sections),
                "sections": result,
            })

        elif name == "text_doc_get_section":
            doc = self._store.get(arguments["document_id"])
            if not doc:
                return json.dumps({"error": "Document not found"})
            if doc.type not in ("text_doc", "word"):
                return json.dumps({"error": f"Document is type '{doc.type}', not 'text_doc'"})
            data = doc.data or {}
            sections = data.get("sections", [])
            section_id = arguments.get("section_id")
            index = arguments.get("index")
            section = None
            if section_id:
                _, section = self._find_section(sections, section_id)
            elif index is not None:
                if 0 <= index < len(sections):
                    section = sections[index]
            else:
                return json.dumps({"error": "Must provide either 'section_id' or 'index'"})
            if not section:
                return json.dumps({"error": "Section not found"})
            return json.dumps({
                "document_id": doc.id,
                "section": section,
            })

        elif name == "text_doc_update_section":
            doc = self._store.get(arguments["document_id"])
            if not doc:
                return json.dumps({"error": "Document not found"})
            if doc.type not in ("text_doc", "word"):
                return json.dumps({"error": f"Document is type '{doc.type}', not 'text_doc'"})
            # Deep-copy before mutation — see module docstring for the
            # reasoning. ``working_data`` is the only place we touch.
            working_data = copy.deepcopy(doc.data or {})
            sections = working_data.get("sections", [])
            idx, section = self._find_section(sections, arguments["section_id"])
            if section is None:
                return json.dumps({"error": f"Section '{arguments['section_id']}' not found"})
            section.update(arguments["updates"])
            return _persist_data_change(
                self._store, doc.id, working_data,
                success_payload={
                    "status": "section_updated",
                    "document_id": doc.id,
                    "section_id": arguments["section_id"],
                },
            )

        elif name == "text_doc_add_section":
            doc = self._store.get(arguments["document_id"])
            if not doc:
                return json.dumps({"error": "Document not found"})
            if doc.type not in ("text_doc", "word"):
                return json.dumps({"error": f"Document is type '{doc.type}', not 'text_doc'"})
            working_data = copy.deepcopy(doc.data or {})
            if "sections" not in working_data:
                working_data["sections"] = []
            sections = working_data["sections"]
            from uuid import uuid4
            sec_type = arguments["type"]
            new_section: Dict[str, Any] = {
                "id": uuid4().hex[:8],
                "type": sec_type,
            }
            if sec_type == "embed":
                ref = arguments.get("ref", "") or arguments.get("$ref", "")
                if not ref:
                    return json.dumps({"error": "embed sections require a 'ref' field"})
                new_section["$ref"] = ref
            else:
                new_section["content"] = arguments.get("content", "")
            if arguments.get("level") is not None:
                new_section["level"] = arguments["level"]
            position = arguments.get("position")
            if position is not None and 0 <= position <= len(sections):
                sections.insert(position, new_section)
            else:
                sections.append(new_section)
            return _persist_data_change(
                self._store, doc.id, working_data,
                success_payload={
                    "status": "section_added",
                    "document_id": doc.id,
                    "section_id": new_section["id"],
                    "section_count": len(sections),
                },
            )

        elif name == "text_doc_delete_section":
            doc = self._store.get(arguments["document_id"])
            if not doc:
                return json.dumps({"error": "Document not found"})
            if doc.type not in ("text_doc", "word"):
                return json.dumps({"error": f"Document is type '{doc.type}', not 'text_doc'"})
            working_data = copy.deepcopy(doc.data or {})
            sections = working_data.get("sections", [])
            idx, section = self._find_section(sections, arguments["section_id"])
            if section is None:
                return json.dumps({"error": f"Section '{arguments['section_id']}' not found"})
            sections.pop(idx)
            return _persist_data_change(
                self._store, doc.id, working_data,
                success_payload={
                    "status": "section_deleted",
                    "document_id": doc.id,
                    "deleted_section_id": arguments["section_id"],
                    "section_count": len(sections),
                },
            )

        elif name == "text_doc_move_section":
            doc = self._store.get(arguments["document_id"])
            if not doc:
                return json.dumps({"error": "Document not found"})
            if doc.type not in ("text_doc", "word"):
                return json.dumps({"error": f"Document is type '{doc.type}', not 'text_doc'"})
            working_data = copy.deepcopy(doc.data or {})
            sections = working_data.get("sections", [])
            idx, section = self._find_section(sections, arguments["section_id"])
            if section is None:
                return json.dumps({"error": f"Section '{arguments['section_id']}' not found"})
            sections.pop(idx)
            new_pos = arguments["new_position"]
            new_pos = max(0, min(new_pos, len(sections)))
            sections.insert(new_pos, section)
            return _persist_data_change(
                self._store, doc.id, working_data,
                success_payload={
                    "status": "section_moved",
                    "document_id": doc.id,
                    "section_id": arguments["section_id"],
                    "new_position": new_pos,
                },
            )

        elif name == "text_doc_search":
            doc = self._store.get(arguments["document_id"])
            if not doc:
                return json.dumps({"error": "Document not found"})
            if doc.type not in ("text_doc", "word"):
                return json.dumps({"error": f"Document is type '{doc.type}', not 'text_doc'"})
            data = doc.data or {}
            sections = data.get("sections", [])
            query = arguments["query"].lower()
            matches = []
            for s in sections:
                content = s.get("content", "")
                content_str = json.dumps(content) if isinstance(content, (list, dict)) else str(content)
                if query in content_str.lower():
                    matches.append({
                        "section_id": s.get("id", ""),
                        "type": s.get("type", ""),
                        "preview": self._section_preview(s),
                    })
            return json.dumps({
                "document_id": doc.id,
                "query": arguments["query"],
                "matches": matches,
                "total_matches": len(matches),
            })

        return json.dumps({"error": f"Unknown tool: {name}"})


def _persist_data_change(
    store: DocumentSessionStore,
    doc_id: str,
    new_data: Dict[str, Any],
    success_payload: Dict[str, Any],
) -> str:
    """Write ``new_data`` to ``doc_id`` and serialize a result for the LLM.

    Centralises the three failure modes ``store.update`` can return so the
    response shape stays consistent and never crashes:

      * ``Document``  — success; merge ``version`` into ``success_payload``.
      * ``list[ValidationError]`` — validation rejected; surface as a
        structured ``validation_failed`` payload the LLM can read and retry.
      * ``None``       — doc was deleted concurrently between read & write.

    The caller is responsible for handing in a *deep copy* of doc.data so
    that a validation failure here doesn't leave the live doc corrupt.
    """
    result = store.update(doc_id, data=new_data)
    if result is None:
        return json.dumps({
            "error": "document_not_found",
            "message": f"Document '{doc_id}' disappeared during update",
            "hint": "The document may have been deleted concurrently.",
        })
    if isinstance(result, list):
        return json.dumps({
            "error": "validation_failed",
            "errors": [
                {"code": e.code, "message": e.message,
                 "hint": e.hint, "path": e.path}
                for e in result
            ],
            "hint": "Batch was rolled back. Fix issues and retry.",
        })
    payload = dict(success_payload)
    payload["version"] = result.version
    return json.dumps(payload)
