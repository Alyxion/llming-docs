# MCP Servers

`llming-docs` exposes its functionality to LLMs as MCP (Model Context Protocol) servers. Each server implements `InProcessMCPServer` from `llming-models` — they run in the same process as the chat session (no subprocess, no network).

!!! info "Tool-only policy"
    These MCP servers are the **only** way to create or edit documents. The
    LLM is instructed (via the preamble) not to emit ` ```text_doc ` /
    ` ```plotly ` / ` ```table ` / etc. fenced code blocks in its responses.
    Those blocks are suppressed by the markdown renderer and stripped from
    response text by the server — they never become documents. See
    [Principles #0](../principles.md#0-tool-only-creation).

## Server layout

| Server | Always on? | Scope | Tools |
|---|---|---|---|
| `DocumentCreatorMCP` | Yes | All types | `create_document`, `list_documents`, `get_document`, `delete_document` |
| `UnifiedDocumentMCP` | Yes (when editing enabled) | All types | `update_document`, `read_document`, `undo_document` |
| `PlotlyDocumentMCP` | Opt-in | `plotly` only | `plotly_add_trace`, `plotly_update_trace`, `plotly_update_layout`, `plotly_get_data` |
| `TableDocumentMCP` | Opt-in | `table` only | `table_add_row`, `table_update_cell`, `table_add_sheet`, `table_freeze_panes`, `table_export_xlsx`, `table_export_csv` |
| `TextDocMCP` | Opt-in | `text_doc` only | `text_doc_add_section`, `text_doc_update_section`, `text_doc_move_section`, `text_doc_remove_section`, `text_doc_export_docx` |
| `PresentationMCP` | Opt-in | `presentation` only | `pptx_add_slide`, `pptx_update_element`, `pptx_set_notes`, `pptx_reorder_slides`, `pptx_export` |
| `HtmlDocumentMCP` | Opt-in | `html` only | `html_update_*`, `html_preview`, `html_export` |
| `EmailDraftMCP` | Opt-in | `email_draft` only | `email_update_subject`, `email_update_recipients`, `email_update_body`, `email_add_attachment`, `email_send` |

## Design philosophy

The mix of one-big-unified-MCP and many-small-type-specific-MCPs is deliberate:

- `UnifiedDocumentMCP` handles the 80% of edits that are surgical — set this field, add this list item, remove this slide. Its path language works across every document type.
- Type-specific MCPs handle the 20% where the path language is awkward or where domain knowledge helps. Adding a row to a table is cleaner as `table_add_row(sheet="Q1", row={...})` than as a `set` op on a list index.

**When adding a new tool, prefer extending `UnifiedDocumentMCP`.** Type-specific MCPs are for operations where:

- Many simple fields change together (e.g. creating a new slide with title + layout + elements in one call).
- The operation has domain semantics the unified path language can't express cleanly (e.g. "freeze the first row" on a table).
- The operation is an export or side-effect, not an edit (`table_export_xlsx`, `pptx_export`).

## Activation

`DocPluginManager` decides which MCPs to instantiate based on `enabled_types`:

```python
from llming_docs import DocPluginManager

# All doc types enabled — all MCPs loaded
mgr = DocPluginManager(enabled_types=None)

# Only plotly and table
mgr = DocPluginManager(enabled_types=["plotly", "table"])
# → DocumentCreatorMCP + UnifiedDocumentMCP + PlotlyDocumentMCP + TableDocumentMCP

# None — only creator MCP is loaded (users can still create fenced code blocks
# that the frontend renders inline)
mgr = DocPluginManager(enabled_types=[])
```

## Iterating MCP servers

```python
for mcp in mgr.iter_mcp_servers():
    session.register_mcp(mcp)
```

Each MCP yields `MCPServerConfig(server_instance=<mcp>)` so the host's MCP registration path works identically to external MCP servers.

## The `create_document` tool

`DocumentCreatorMCP.create_document` is the entry point most other tools won't supersede:

```json
{
  "type": "plotly",
  "name": "Q1 Revenue Chart",
  "data": "{\"data\":[{\"type\":\"bar\",\"x\":[...],\"y\":[...]}],\"layout\":{...}}"
}
```

- `type` is one of the seven supported types (plus aliases `word`/`powerpoint`).
- `name` is mandatory — it's the sidebar label and the default export filename. Keep it short and specific ("Q1 Revenue Chart", not "Chart").
- `data` is a **JSON-encoded string** — not a nested object. The LLM has to `JSON.stringify` its payload. This avoids MCP transport ambiguity around deep nested JSON and lets the server return structured parse errors.

On validation failure, returns `{"error": "validation_failed", "errors": [...]}` — see [Validation](validation.md).

## The `update_document` tool (unified)

`UnifiedDocumentMCP.update_document` accepts multiple operations per call, applied atomically:

```json
{
  "document_id": "abc123",
  "operations": [
    {"op": "set",    "path": "slides/s1/title",  "value": "New Title"},
    {"op": "add",    "path": "slides",            "value": {...}, "position": 2},
    {"op": "remove", "path": "slides/s3"},
    {"op": "move",   "path": "slides/s1",         "position": 0}
  ]
}
```

### Path language

The path language is **type-aware**. Tables (XLSX) use openpyxl-native A1
addressing; everything else uses JSON-path navigation against `doc.data`.

**Non-table types** — slash-separated paths against `doc.data`:

- `slides/s1/title` — array lookup by `id` field, then field access.
- `slides/0/elements/2/content` — array lookup by numeric index, nested.
- `sections/abc123/content` — section by id.
- `to`, `subject`, `body_html` — top-level fields (email).
- `data/0/x` — first Plotly trace, x-values.

**Table type** — sheets are referenced by 0-based **index** (not name),
cells by A1 address. The full op vocabulary lives in `xlsx_ops.py`; common
shapes:

- `sheets/0/cells/B3/value` — cell B3 on the first sheet.
- `sheets/0/cells/B3/font` — font dict (bold/italic/color/size).
- `sheets/0/cells/B3/fill` — background fill.
- `sheets/0/rows/-` (`add`, value=list) — append a row.
- `sheets/0/columns/-` (`add`, value=string) — append a column header.
- `sheets/0/columns` (`add`, position=N) — insert column at position N.
- `bulk_set sheets/0/range/A1` with `values: [[...], ...]` — drop a 2D
  block. Cheaper per token than per-cell sets for big tables.

Legacy column-name paths like `sheets/Q1/rows/3/revenue` are gone — the
dispatcher will raise `XlsxOpError` if the LLM emits them.

### Operations

- **`set`** — replace value at path.
- **`add`** — insert; `position` specifies the index (defaults to end).
- **`remove`** — delete.
- **`move`** — reorder (non-table only); `position` is the destination index.
- **`bulk_set`** — table only; `values` is a 2D array placed at `range/<A1>`.

Operations are atomic per call — if any op fails validation or path resolution, none are applied. The tool returns `{"error": "update_failed", "errors": [...]}` with per-op details.

### `read_document`

Returns `doc.data` (or a subtree, via `path`) without mutating. Use this before editing when the LLM needs to inspect current state.

### `undo_document`

Rewinds one version. Returns the restored data. Emits `doc_updated` to the client. See [History & Undo](history-undo.md).

## Registering a per-type MCP

In `manager.py`:

```python
_MCP_SERVERS["kanban"] = {
    "module": "llming_docs.kanban_mcp",
    "class_name": "KanbanDocumentMCP",
    "label": "Kanban Boards",
    "description": "Edit kanban board documents",
}
```

Plus a preamble line:

```python
_PREAMBLE_LINES["kanban"] = (
    "- ```kanban — Kanban board "
    "(JSON: {columns: [{id, name, cards: [{id, title, description}]}]})"
)
```

Plus a tool-name prefix (for preset bulk-toggling):

```python
TYPE_TOOL_PREFIXES["kanban"] = "kanban_"
```

And append to `ALL_DOC_PLUGIN_TYPES`. The manager auto-instantiates the MCP when the type is enabled.

See [Extending](../integration/extending.md) for the full end-to-end flow.
