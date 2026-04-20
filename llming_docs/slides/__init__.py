"""slides — presentation subpackage (PPTX).

Houses the MCP tools and PPTX exporter for the ``presentation``
document type. Validators still live in the shared
``llming_docs.validators`` module — per-type validator split is planned
for Phase 2C.
"""
from llming_docs.slides import exporter, mcp
from llming_docs.slides.exporter import export_pptx
from llming_docs.slides.mcp import PresentationMCP

TYPE = "presentation"
LABEL = "Presentations"
DESCRIPTION = "Edit presentation slide decks"
TOOL_PREFIX = "pptx_"

__all__ = [
    "TYPE",
    "LABEL",
    "DESCRIPTION",
    "TOOL_PREFIX",
    "PresentationMCP",
    "export_pptx",
    "exporter",
    "mcp",
]
