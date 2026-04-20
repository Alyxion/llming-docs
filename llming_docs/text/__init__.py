"""text — text_doc subpackage (DOCX-like documents).

Houses the MCP tools and DOCX exporter for the ``text_doc`` document
type. Validators still live in the shared ``llming_docs.validators``
module — per-type validator split is planned for Phase 2C. Frontend
assets still live in the shared ``llming_docs/frontend/`` bundle —
per-type frontend split is planned for Phase 2B.
"""
from llming_docs.text import exporter, mcp
from llming_docs.text.exporter import export_docx
from llming_docs.text.mcp import TextDocMCP

TYPE = "text_doc"
LABEL = "Text Documents"
DESCRIPTION = "Edit structured text documents"
TOOL_PREFIX = "text_doc_"

__all__ = [
    "TYPE",
    "LABEL",
    "DESCRIPTION",
    "TOOL_PREFIX",
    "TextDocMCP",
    "export_docx",
    "exporter",
    "mcp",
]
