"""latex — LaTeX formula subpackage.

Frontend-rendered only — no MCP server or exporter. Formulas are stored
as ``{"formula": "<latex>"}`` and rendered client-side via KaTeX.
"""

TYPE = "latex"
LABEL = "LaTeX Formula"
DESCRIPTION = "Render LaTeX formulas (client-side via KaTeX)"
TOOL_PREFIX = "latex_"  # reserved — no tools today

__all__ = [
    "TYPE",
    "LABEL",
    "DESCRIPTION",
    "TOOL_PREFIX",
]
