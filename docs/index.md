# llming-docs

**Structured documents for LLM chat — validation, delta-based undo, embedding, multi-format export.**

`llming-docs` is the canonical home for document creation and editing logic. It defines what a document *is*, how it's stored, how it's edited by an LLM via MCP tools, and how it exports. Chat frontends (e.g. `llming-lodge`) dock into it — they wire its stores and MCP servers into their session lifecycle but own none of the document logic.

!!! warning "Tool-only policy"
    Documents are created and edited **exclusively** via MCP tools —
    `create_document`, `update_document`, and the per-type edit tools.
    Fenced ` ```text_doc ` / ` ```plotly ` / ` ```table ` / etc. code blocks
    in assistant responses are disabled and will not render. Full rationale
    in [Principles #0](principles.md#0-tool-only-creation).

---

## What's in the box

- **A session-scoped `DocumentSessionStore`** — thread-safe, emits `doc_created` / `doc_updated` / `doc_deleted` events.
- **MCP servers** — `DocumentCreatorMCP` (create/list/get/delete), `UnifiedDocumentMCP` (path-based update/read/undo), plus fine-grained per-type MCPs (`plotly_*`, `table_*`, `text_doc_*`, `presentation_*`, `html_*`, `email_*`).
- **Seven document types** — Plotly charts, tables (multi-sheet), text documents, presentations, HTML sandboxes, LaTeX formulas, email drafts.
- **Validators** — deep structural checks called on every create/update, returning AI-actionable `code`/`message`/`hint`/`path` errors.
- **Version history with undo** — periodic snapshots plus JSON-Pointer deltas for cheap reconstruction of any version.
- **Cross-document embedding** — `{"type": "embed", "$ref": "<id>"}` with a pluggable `EmbedBehavior` registry (graphic / table / text).
- **Exporters** — DOCX, PPTX, XLSX, CSV, HTML — all accepting and returning `bytes` (no disk I/O required).

---

## Quick example

```python
from llming_docs import DocPluginManager

mgr = DocPluginManager(enabled_types=["plotly", "table", "text_doc"])
store = mgr.store

# Create a table
result = store.create(
    type="table", name="Q1 Revenue",
    data={
        "columns": [{"name": "Region"}, {"name": "USD"}],
        "rows": [["EU", 420_000], ["US", 310_000]],
    },
)
# `result` is a Document on success, list[ValidationError] on structural failure.

# Wire store events to whatever UI/transport the host uses
store.set_notify_callback(lambda event, doc: print(event, doc.id, doc.name))

# Register the MCP servers with an LLM session
for mcp in mgr.iter_mcp_servers():
    session.register_mcp(mcp)

# Inject the LLM-facing preamble describing the available types
system_prompt += mgr.get_preamble()
```

---

## Where to go next

- [Principles](principles.md) — the non-negotiable rules that keep this package useful across hosts.
- [Documents vs `__rich_mcp__` envelopes](docs-vs-rich-mcp.md) — the key distinction to make before adding a new tool.
- [Document types](types.md) — the seven supported types, data shapes, and export formats.
- [Docking into a chat frontend](integration/docking.md) — the contract a host chat framework must implement.
- [Extending](integration/extending.md) — how to add a new document type end-to-end.
