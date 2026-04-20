# llming-docs — assistant guide

Canonical location for the document system (Plotly, tables, text docs, presentations, HTML, LaTeX, email drafts). Chat frontends dock into this package; all document logic must live here.

See `README.md` for the full architecture and public API. This file is the short list of non-obvious rules when editing code here.

## Hard rules

- **Tool-only creation.** Documents are created/edited EXCLUSIVELY via the MCP tools (`create_document`, `update_document`, per-type tools). Fenced ``` ```text_doc ``` / ``` ```plotly ``` / ``` ```table ``` / etc. in assistant responses are forbidden — they don't render on the client and are stripped server-side. Never add preamble wording that says "prefer fenced blocks" or similar. Every doc-type plugin in the client registry is marked `fencedBlockAllowed: false`; don't flip that flag.
- **No imports from chat frontends.** Never `from llming_lodge.…` or from customer-specific packages. `llming-docs` stays standalone so it runs in batch jobs, CLI tools, and non-chat hosts.
- **No customer names.** Nothing under `dependencies/` may reference any customer by name. Keep wording generic.
- **No disk I/O.** Exporters take `bytes`, return `bytes`. Don't write temp files; let the caller decide.
- **Data only, never presentation.** Document `data` is pure JSON — no HTML, CSS, or JS baked in. Presentation is built at render time by the frontend or the exporter. This rule is what keeps old conversations from breaking when styles change.
- **No `getattr` / `hasattr`.** Same rule as the parent project. Access attributes directly; if something might not exist, give it a default on the class or use `isinstance` narrowing.

## Documents vs `__rich_mcp__` envelopes

Two different mechanisms for showing rich output in chat. Don't conflate them.

- **Document** — persistent, editable, shows up in the sidebar. Created via `DocumentSessionStore.create()` (or the `create_document` MCP tool, or a fenced ````plotly` / ````table` etc. code block the frontend maps to `create`). Use this for anything the user might revisit.
- **`__rich_mcp__` envelope** — a one-shot tool result that the frontend renders inline (math steps, 3D preview plots from droplets). Ephemeral — not stored in the document sidebar, not editable, not in IDB beyond the message content. Use this only for transient output.

Rule of thumb: if the user would ever say "open that chart again" or "change the title" — it's a Document. Otherwise consider a rich_mcp envelope.

## Validation contract

`DocumentSessionStore.create(...)` and `.update(...)` return **either** a `Document` **or** `list[ValidationError]`. Callers MUST check `isinstance(result, list)` and surface the errors — never silently persist garbage. The MCP tools in this package already do this; follow that pattern in new tools.

Validators should always carry `code`, `message`, `hint`, and `path` so the LLM can self-correct from a single retry.

## Restore semantics

`store.restore_from_list(docs)` **replaces** the store — it does not merge. This is intentional: a client reconnect or conversation switch sends the authoritative doc list, and merging would leak stale docs from a different conversation. If you need additive behavior, loop `store.create(skip_validation=True, ...)` instead.

## Embed registry

Any new document type that can appear inside another document MUST declare its `EmbedBehavior` in `render.py`. Host documents (text_doc, presentation) never branch on what they're embedding — they emit `{"type": "embed", "$ref": "<id>"}` and the export pipeline looks up the behavior. Forgetting to register means the new type silently exports as a placeholder.

## MCP layout

- `creator_mcp.py` — always on; owns `create_document`, `list_documents`, `get_document`, `delete_document`.
- `unified_mcp.py` — always on when editing is enabled; owns `update_document`, `read_document`, `undo_document` (path-based, type-agnostic).
- `<type>_mcp.py` — per-type, opt-in via `DocPluginManager(enabled_types=[...])`. Fine-grained tools like `plotly_add_trace`, `table_add_row`.

When adding tools, prefer extending `unified_mcp` (one surgical edit per call) over growing a type-specific MCP. Type-specific MCPs exist for cases where the path language is awkward (e.g. bulk row operations on tables).

## Sync

This package is mirrored at `~/projects/llming-docs/` and pushed/pulled via `scripts/sync/{push,pull}_llming_docs.sh` from the SalesBot repo. Edits made in `dependencies/llming-docs/` must be pushed back with the sync script after the change lands.
