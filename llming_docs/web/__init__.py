"""web — HTML document subpackage.

Houses the MCP tools and HTML exporter for the ``html`` document type.
The Python package name is ``web`` because ``html`` is a Python
standard-library module and we must not shadow it. The document type
string remains ``"html"``. Validators still live in the shared
``llming_docs.validators`` module — per-type validator split is planned
for Phase 2C.
"""
from llming_docs.web import exporter, mcp
from llming_docs.web.exporter import export_html
from llming_docs.web.mcp import HtmlDocumentMCP

TYPE = "html"
LABEL = "Website"
DESCRIPTION = "Create and edit websites, web apps, and interactive HTML/CSS/JS projects"
TOOL_PREFIX = "html_"

__all__ = [
    "TYPE",
    "LABEL",
    "DESCRIPTION",
    "TOOL_PREFIX",
    "HtmlDocumentMCP",
    "export_html",
    "exporter",
    "mcp",
]
