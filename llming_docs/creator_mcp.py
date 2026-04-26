"""DocumentCreatorMCP — in-process MCP server for creating and managing documents."""

import json
import logging
from typing import Any, Dict, List

from llming_models.tools.mcp import InProcessMCPServer
from llming_docs.document_store import DocumentSessionStore
from llming_docs.ops_dispatcher import (
    apply_operations_to_data,
    empty_data_for,
)

logger = logging.getLogger(__name__)

# Supported document types
DOC_TYPES = ["plotly", "latex", "table", "text_doc", "presentation", "html", "email_draft",
             "word", "powerpoint"]  # old names accepted for backward compat


class DocumentCreatorMCP(InProcessMCPServer):
    """MCP server that lets the LLM create, list, get, and delete documents."""

    def __init__(self, store: DocumentSessionStore) -> None:
        self._store = store

    async def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "create_document",
                "displayName": "Create Document",
                "displayDescription": "Create a rich document",
                "icon": "description",
                "description": (
                    "Create a new document. Use the same operation vocabulary you would "
                    "use with `update_document` to populate it — there is no per-type "
                    "creation payload. Supported types: text_doc, table, plotly, latex, "
                    "presentation, html, email_draft.\n"
                    "\n"
                    "The server creates an empty document of the requested type and applies "
                    "every operation in `operations` (atomically). Examples:\n"
                    "\n"
                    "Text document:\n"
                    "  operations: ["
                    "{op:'add', path:'sections/-', value:{id:'s1', type:'heading', level:1, content:'Title'}},"
                    "{op:'add', path:'sections/-', value:{id:'s2', type:'paragraph', content:'…'}}]\n"
                    "\n"
                    "Spreadsheet (XLSX-backed; use openpyxl-native A1 paths):\n"
                    "  operations: ["
                    "{op:'set', path:'sheets/0/name', value:'Q1'},"
                    "{op:'bulk_set', path:'sheets/0/range/A1', values:[['Product','Revenue'],['Widget',100]]},"
                    "{op:'set', path:'sheets/0/cells/B1/font', value:{bold:true}}]\n"
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": DOC_TYPES,
                            "description": "Document type",
                        },
                        "name": {
                            "type": "string",
                            "description": "Human-readable document name",
                        },
                        "operations": {
                            "type": "array",
                            "description": (
                                "Operations to apply to a freshly-created empty document "
                                "of this type. Same vocabulary as update_document. May be "
                                "empty to create a blank document."
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "op": {"type": "string"},
                                    "path": {"type": "string"},
                                    "value": {},
                                    "values": {},
                                    "position": {"type": "integer"},
                                },
                                "required": ["op", "path"],
                            },
                        },
                    },
                    "required": ["type", "name"],
                },
            },
            {
                "name": "list_documents",
                "displayName": "List Documents",
                "displayDescription": "List all documents",
                "icon": "folder_open",
                "description": (
                    "List all documents in the current conversation. "
                    "Optionally filter by type. Returns id, type, name, version."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": DOC_TYPES,
                            "description": "Filter by document type (optional)",
                        },
                    },
                },
            },
            {
                "name": "get_document",
                "displayName": "Get Document",
                "displayDescription": "Get document details",
                "icon": "article",
                "description": "Get the full data of a specific document by ID.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Document ID",
                        },
                    },
                    "required": ["document_id"],
                },
            },
            {
                "name": "delete_document",
                "displayName": "Delete Document",
                "displayDescription": "Delete a document",
                "icon": "delete",
                "description": "Delete a document by ID.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Document ID",
                        },
                    },
                    "required": ["document_id"],
                },
            },
        ]

    # Backward compat: old type names → new
    _TYPE_ALIASES = {"word": "text_doc", "powerpoint": "presentation"}

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        if name == "create_document":
            doc_type = self._TYPE_ALIASES.get(arguments["type"], arguments["type"])
            operations = arguments.get("operations") or []
            doc_name = arguments["name"]

            # Start from the per-type empty template so the LLM's ops have
            # a known parent to land on (sections/-, sheets/0/cells/A1/value, …).
            initial = empty_data_for(doc_type)

            # Apply ops to the empty data. ``apply_operations_to_data``
            # routes table → openpyxl, everything else → JSON path ops.
            new_data, op_error = apply_operations_to_data(
                doc_type, initial, operations,
            )
            if op_error is not None:
                return json.dumps(op_error)

            # Skip the JSON-shape validator for table — the workbook IS
            # the validator (any invalid op already raised above).
            skip_validation = (doc_type == "table")
            result = self._store.create(
                type=doc_type,
                name=doc_name,
                data=new_data,
                skip_validation=skip_validation,
            )
            if isinstance(result, list):
                return json.dumps({
                    "error": "validation_failed",
                    "errors": [
                        {"code": e.code, "message": e.message, "hint": e.hint, "path": e.path}
                        for e in result
                    ],
                })
            doc = result
            return json.dumps({
                "status": "created",
                "document_id": doc.id,
                "type": doc.type,
                "name": doc.name,
                "version": doc.version,
                "operations_applied": len(operations),
            })

        elif name == "list_documents":
            doc_type = arguments.get("type")
            docs = self._store.list_by_type(doc_type) if doc_type else self._store.list_all()
            return json.dumps([
                {"id": d.id, "type": d.type, "name": d.name, "version": d.version}
                for d in docs
            ])

        elif name == "get_document":
            doc = self._store.get(arguments["document_id"])
            if not doc:
                return json.dumps({"error": "Document not found"})
            return json.dumps(doc.model_dump())

        elif name == "delete_document":
            deleted = self._store.delete(arguments["document_id"])
            return json.dumps({
                "status": "deleted" if deleted else "not_found",
                "document_id": arguments["document_id"],
            })

        return json.dumps({"error": f"Unknown tool: {name}"})
