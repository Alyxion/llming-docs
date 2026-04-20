# Documents vs `__rich_mcp__` envelopes

Two mechanisms in the chat stack both produce rich inline output. Know which one you want before adding a new tool — the wrong choice is hard to undo once the feature ships.

!!! warning "Tool-only policy for documents"
    Documents are created and edited **exclusively** through MCP tools
    (`create_document`, `update_document`, per-type edit tools). Fenced
    ` ```text_doc ` / ` ```plotly ` / ` ```table ` / etc. code blocks in
    assistant responses are **disabled** — the markdown renderer does not
    render them, and the server strips them from response text. See
    [Principles #0](principles.md#0-tool-only-creation).

## Side-by-side

| | **Document** (this package) | **`__rich_mcp__` envelope** |
|---|---|---|
| Where it lives | `DocumentSessionStore`, synced to client IDB per conversation | Inside a tool-call result (message-scoped) |
| User-visible | Sidebar Documents panel, preview card, downloadable | Rendered inline in the assistant message only |
| Editable | Yes — `update_document` with path-based ops | No — one-shot output |
| Persistent | Yes — survives reloads, conversation switches, session restarts | As long as the message content exists |
| History / undo | Yes — delta-based `undo_document` | No |
| Cross-referenced | Yes — `{"$ref": "<id>"}` in any other document | No |
| Export formats | DOCX, PPTX, XLSX, CSV, HTML, PNG | None (whatever the inline renderer produces) |
| Where it's implemented | `llming-docs` (this package) | Tool author + client renderer (in `builtin-plugins.js`) |

## When to pick a Document

Produce a Document if **any** of these is true:

- The user might open it again later (“show me that chart”).
- The user might ask for edits (“change the title”, “add a row”).
- The user wants to download it (“export as PPTX”).
- It can be embedded in another document (chart in a Word doc, table in a slide).
- Two tool calls might want to reference the same data.
- It has a name worth showing in the sidebar.

Default bias: when in doubt, make it a Document. Upgrading rich_mcp output into a Document later is a breaking change.

## When to pick `__rich_mcp__`

Use `__rich_mcp__` if **all** of these are true:

- The output is self-contained and won't be referenced again.
- It's genuinely throwaway — regenerating from the prompt is fine.
- No one would ever say “open that again”.

Real examples currently using `__rich_mcp__`:

- **MathMCP `rich_output=True`** (`llming_lodge/tools/math_mcp.py`) — step-by-step algebra with LaTeX. The steps are a render of the tool's reasoning; persisting them adds no value.
- **Browser MCP / bolt-based droplets** (`chat-bolts.js`) — Worker-sandboxed JS tools that return rich preview data (e.g. 3D plots, specialised viewers). These deliberately don't participate in the Documents sidebar.

## What an `__rich_mcp__` envelope looks like

```python
{
    "__rich_mcp__": {
        "version": "1.0",
        "min_viewer_version": "1.0",
        "render": {
            "type": "math_result",   # frontend renderer picks this
            "title": "Solve x² - 5x + 6 = 0",
            "latex": "x = 2, \\; x = 3",
            "steps": [...],
        },
        "llm_summary": "x = 2, x = 3",  # what goes into history
    }
}
```

Key points:

- The envelope is **data only**. The client builds HTML/CSS/JS from `render.*` at render time. This is the same rule as Documents.
- On save, the host replaces the full envelope with `llm_summary` in the persisted tool_call `result` to keep history compact. Large payloads (e.g. 3D plot traces) disappear from storage — they're regenerated if the user asks for the data again.
- Vendor libs (Plotly, KaTeX) are referenced via `render.vendor_libs: ["plotly", "katex_js", "katex_css"]` and inlined into a sandboxed iframe by the client.

## Common mistakes

- **Returning a Document disguised as rich_mcp.** If the tool creates a thing the user will edit later, just create a Document. Rich_mcp envelopes that carry a `document_id` are a code smell — either commit to Documents or commit to ephemeral.
- **Returning rich_mcp disguised as a Document.** If the tool's output has no meaningful name, no edit story, and no export path, don't stuff it into `DocumentSessionStore`. Sidebar noise devalues the Documents panel.
- **HTML in rich_mcp render data.** Same rule as Documents: data only, no presentation. Old conversations break when the styling evolves otherwise.
