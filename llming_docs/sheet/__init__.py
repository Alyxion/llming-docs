"""sheet — table / spreadsheet subpackage (XLSX + CSV).

Houses the MCP tools and XLSX/CSV exporters for the ``table`` document
type. Validators still live in the shared ``llming_docs.validators``
module — per-type validator split is planned for Phase 2C.
"""
from llming_docs.sheet import exporter, mcp
from llming_docs.sheet.exporter import export_csv, export_xlsx
from llming_docs.sheet.mcp import TableDocumentMCP

TYPE = "table"
LABEL = "Tables"
DESCRIPTION = "Edit table and spreadsheet documents"
TOOL_PREFIX = "table_"

__all__ = [
    "TYPE",
    "LABEL",
    "DESCRIPTION",
    "TOOL_PREFIX",
    "TableDocumentMCP",
    "export_csv",
    "export_xlsx",
    "exporter",
    "mcp",
]
