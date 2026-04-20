"""Document plugin system — rich document creation, editing, and export.

Provides a plugin architecture for creating and editing structured documents
(Plotly charts, tables, text documents, presentations, HTML sandboxes, email
drafts) via MCP tools.  Includes validation, version history (undo), and
multiple export formats (PPTX, DOCX, XLSX, CSV, HTML).

Designed to run in any environment — not tied to any particular chat frontend.
"""

from llming_docs.document_store import Document, DocumentSessionStore
from llming_docs.frontend import (
    DOC_ICONS,
    FORBIDDEN_FENCED_DOC_LANGS,
    DocTypeFrontend,
    get_manifest,
    get_mcp_group_labels,
    get_static_dir,
)
from llming_docs.history import DocumentHistory, HistoryEntry, compute_delta, apply_delta
from llming_docs.manager import DocPluginManager, ALL_DOC_PLUGIN_TYPES
from llming_docs.render import (
    EmbedBehavior,
    EMBED_BEHAVIOR,
    RenderResult,
    RenderContext,
    RENDER_CAPABILITIES,
    EMBED_RULES,
    render_to,
    can_render,
    can_embed,
    get_embed_format,
    get_embed_behavior,
    register_embed_behavior,
)
from llming_docs.unified_mcp import UnifiedDocumentMCP
from llming_docs.validators import ValidationError, validate_document
from llming_docs import pdf

__all__ = [
    # Frontend manifest (client-side assets owned by llming-docs)
    "DOC_ICONS",
    "FORBIDDEN_FENCED_DOC_LANGS",
    "DocTypeFrontend",
    "get_manifest",
    "get_mcp_group_labels",
    "get_static_dir",
    # Core models
    "Document",
    "DocumentSessionStore",
    # Version history
    "DocumentHistory",
    "HistoryEntry",
    "compute_delta",
    "apply_delta",
    # Validation
    "ValidationError",
    "validate_document",
    # Manager
    "DocPluginManager",
    "ALL_DOC_PLUGIN_TYPES",
    # Render / export
    "EmbedBehavior",
    "EMBED_BEHAVIOR",
    "RenderResult",
    "RenderContext",
    "RENDER_CAPABILITIES",
    "EMBED_RULES",
    "render_to",
    "can_render",
    "can_embed",
    "get_embed_format",
    "get_embed_behavior",
    "register_embed_behavior",
    # Unified MCP (replaces type-specific MCPs)
    "UnifiedDocumentMCP",
    # PDF read/render subpackage (pypdfium2 + pdfplumber — no AGPL)
    "pdf",
]
