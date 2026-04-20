"""email — email draft subpackage.

Houses the MCP tools for the ``email_draft`` document type. No
server-side exporter — drafts are sent via the host's mail pipeline, not
exported to a file. Validators still live in the shared
``llming_docs.validators`` module — per-type validator split is planned
for Phase 2C.
"""
from llming_docs.email import mcp
from llming_docs.email.mcp import EmailDraftMCP

TYPE = "email_draft"
LABEL = "Email Drafts"
DESCRIPTION = "Compose and edit email drafts"
TOOL_PREFIX = "email_"

__all__ = [
    "TYPE",
    "LABEL",
    "DESCRIPTION",
    "TOOL_PREFIX",
    "EmailDraftMCP",
    "mcp",
]
