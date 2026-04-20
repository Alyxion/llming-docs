"""chart — Plotly chart subpackage.

Houses the MCP tools for the ``plotly`` document type. No server-side
exporter — charts render client-side and are embedded into other
documents via the embed registry. Validators still live in the shared
``llming_docs.validators`` module — per-type validator split is planned
for Phase 2C.
"""
from llming_docs.chart import mcp
from llming_docs.chart.mcp import PlotlyDocumentMCP

TYPE = "plotly"
LABEL = "Plotly Charts"
DESCRIPTION = "Edit and refine Plotly chart documents"
TOOL_PREFIX = "plotly_"

__all__ = [
    "TYPE",
    "LABEL",
    "DESCRIPTION",
    "TOOL_PREFIX",
    "PlotlyDocumentMCP",
    "mcp",
]
