# Principles

These are the non-negotiable rules that keep `llming-docs` useful across hosts and resilient to style changes. Code reviews here bounce anything that breaks one of them without a written justification.

## 0a. Format code is 100% in llming-docs

**Every byte of format-specific code lives in `llming-docs`.** That includes:

- **MCPs** (creator, unified, per-type edit tools).
- **Validators** — per-type structural checks.
- **Exporters** — DOCX, PPTX, XLSX, CSV, HTML, PNG.
- **Client plugin renderers** — the JS that turns `doc.data` into DOM.
- **Per-type CSS** — styling that's specific to one doc type.
- **Format metadata** — `DOC_ICONS`, `FORBIDDEN_FENCED_DOC_LANGS`, labels, aliases, vendor-lib requirements.

Host chat frameworks (`llming-lodge` et al.) **dock** into llming-docs — they import the metadata, mount the static asset dir at a URL, register the MCPs with their chat session. They never name a doc type in their own source.

**Why:** adding a new document type is a one-package change. Spinning up llming-docs in a non-chat host (batch CLI, REST API, electron app) carries the full visual surface with it. Format bugs are investigated in one repo.

**How it shows up:**

- `from llming_docs import FORBIDDEN_FENCED_DOC_LANGS, DOC_ICONS, get_static_dir, get_manifest` — the host's entire interface.
- `llming_docs/frontend/__init__.py` is the authoritative `MANIFEST` — adding a new type appends one entry.
- `llming_docs/frontend/static/` holds the JS/CSS assets. The host serves them verbatim.
- Per-type MCPs register themselves via `DocPluginManager.iter_mcp_servers()`.

See the [Docking guide](integration/docking.md) for the full host contract.

## 0. Tool-only creation

**Documents are created and edited EXCLUSIVELY via MCP tools** — `create_document`, `update_document`, and the per-type edit tools (`text_doc_update_section`, `plotly_add_trace`, `table_add_row`, …). Fenced code blocks (` ```text_doc `, ` ```plotly `, ` ```table `, etc.) are **forbidden** in assistant responses.

**Why:** multiple paths to create the same thing produces duplicates, id drift, and stale previews. The LLM routinely fired *both* the `create_document` tool AND emitted a fenced block with its own UUID, producing two docs with the same name and different ids. There's one path now.

**How it shows up:**

- `manager.get_preamble()` tells the LLM: *tool-only, fenced blocks are disabled, they will NOT render.*
- The client's `DocPluginRegistry` marks doc-type plugins with `fencedBlockAllowed: false`; the markdown renderer returns an empty comment for those languages and never calls the plugin.
- The chat server strips any fenced doc-type blocks from assistant text at response completion (`_strip_fenced_doc_blocks` in `chat_session_api.py`) — policing in case the LLM emits them anyway.
- Tool-driven rendering (client receives `doc_created` → `_injectToolDocBlock`) still renders inline previews — the plugin is called directly, bypassing the fenced-block path.

**Ephemeral render plugins that aren't documents** (`mermaid`, `rich_mcp`, `kantini_result`, `followup`) keep `fencedBlockAllowed: true` — they're not persistent documents and fenced-block rendering is their legitimate transport.

## 1. Data only, never presentation

Document `data` is pure JSON — no HTML, CSS, or JS baked in. Presentation is built at render time by the frontend plugin or the exporter.

**Why:** style fixes and improvements automatically apply to historic conversations. Storage stays compact. No stale rendering code gets frozen into saved documents. When a Plotly axis default changes, every old chart in every old conversation picks it up on reload.

**How it shows up in code:**

- `Document.data` never contains literal HTML or CSS strings.
- Frontend plugins (`plugins/builtin-plugins.js` in the host) build HTML from `data` at render time.
- Exporters (`word_exporter`, `pptx_exporter`, `table_exporter`) translate `data` to the target format — they don't read pre-baked HTML.

!!! warning
    This rule applies equally to `__rich_mcp__` envelopes. If you're tempted to return HTML from a tool, stop — return structured data and teach the client renderer to handle it.

## 2. Standalone

`llming-docs` never imports from a chat frontend. It exposes stores + MCP servers; the host wires them into its session.

**Why:** the same package runs in a chat session, a batch export job, a CLI that renders a deck, a REST API that returns a PPTX. Any dependency on a specific chat framework would leak that framework into every consumer.

**How it shows up in code:**

- No `from llming_lodge.…` or `from <chat_host>.…` imports anywhere in `llming_docs/`.
- The `notify_callback` on `DocumentSessionStore` is a plain function — the host decides whether to push events over WebSocket, call a database, or discard them.
- MCP servers subclass `InProcessMCPServer` from `llming-models` (the transport layer), not anything from the chat frontend.

## 3. Validate on write

`DocumentSessionStore.create()` and `.update()` return **either** a `Document` **or** `list[ValidationError]`. Callers MUST check `isinstance(result, list)` and surface the errors — never silently persist garbage.

**Why:** LLM-generated JSON is frequently almost-right. Catching structural problems at write time lets the tool result carry a concrete `code`/`message`/`hint`/`path` the LLM can fix on one retry. Persisting an invalid document would corrupt the conversation for the rest of its lifetime.

**How it shows up in code:**

- MCP tools (`creator_mcp.py`, `unified_mcp.py`, per-type MCPs) all follow the same pattern:

```python
result = self._store.create(type=t, name=n, data=d)
if isinstance(result, list):
    return json.dumps({
        "error": "validation_failed",
        "errors": [{"code": e.code, "message": e.message,
                    "hint": e.hint, "path": e.path} for e in result],
    })
doc = result
```

- Trusted callers (tests, internal migrations) pass `skip_validation=True` explicitly. Never skip validation from a code path an LLM can reach.

## 4. Undo is cheap

`DocumentHistory` stores periodic full snapshots plus JSON-Pointer deltas between them. Any version can be reconstructed in O(snapshot_interval) ops.

**Why:** LLMs make mistakes and users ask to revert. A reliable one-step undo (and potential multi-step in the future) has to be free enough that nobody hesitates to use it. Storing a full snapshot per edit would blow up storage on documents with many small incremental edits (e.g. a slide deck under iteration).

**How it shows up in code:**

- `store.update()` records a delta against the previous version automatically.
- Snapshots are taken every N versions or when the delta would exceed ~60% of the full document.
- `store.undo(doc_id)` rewinds one step and emits `doc_updated` with the restored data.
- `compute_delta(old, new)` / `apply_delta(data, delta)` are exported for callers that need to diff arbitrary JSON.

## 5. Embed by reference

Cross-document embeds (`{"type": "embed", "$ref": "<id>"}`) never duplicate data. The render/export pipeline resolves references at render time using the `EmbedBehavior` registry.

**Why:** duplication drifts. If a Plotly chart is embedded in three Word documents and one email draft, edits to the chart should show up everywhere — automatically — without the LLM having to chase every copy. The host document never even needs to know *what* it's embedding.

**How it shows up in code:**

- `EMBED_BEHAVIOR` in `render.py` maps each doc type to an `EmbedBehavior(mode, aspect)` — `"graphic"` (rasterise to PNG), `"table"` (native table), or `"text"` (inline paragraphs).
- Host documents (`text_doc`, `presentation`) emit `{"type": "embed", "$ref": "<id>"}` and the exporter looks up the behavior.
- Adding a new document type requires registering its embed behavior — otherwise it silently exports as a placeholder.

## 6. No disk I/O

Exporters accept `bytes`, return `bytes`. The store never writes to disk. The package never creates temp files.

**Why:** server-side code runs in multi-worker containers where writing to local disk leaks state between workers and causes problems on restart. Callers that actually want a file on disk write it themselves once.

**How it shows up in code:**

- `render_to(...)` returns `RenderResult(data=<bytes>, mime_type=..., filename=...)`.
- Exporters use `BytesIO` internally, never `tempfile` or `Path.write_bytes`.
- Extraction/parsing helpers accept either `bytes | Path` — callers pass `bytes` server-side.

## 7. Restore replaces, does not merge

`DocumentSessionStore.restore_from_list(docs)` clears the existing store before loading. This is intentional — a client reconnect or conversation switch sends the authoritative doc list.

**Why:** merging would leak stale docs from a previous conversation into the current one. The client's IndexedDB (or equivalent) per-conversation store is the source of truth on reconnect; the server-side store is an ephemeral cache built from that.

**How it shows up in code:**

- `restore_from_list` first calls `self._docs.clear()` and `self._histories.clear()`.
- The host's `doc_restore` WebSocket handler always sends the full doc list for the current conversation — never an incremental patch.
- If additive behavior is ever needed, call `store.create(skip_validation=True, ...)` in a loop instead of extending `restore_from_list`.

## 8. No framework-specific attribute access

`llming-docs` follows the parent project's rule: never use `getattr` / `hasattr`. Access attributes directly; if something might not exist, give it a default on the class or use `isinstance` for type narrowing.

**Why:** `getattr`/`hasattr` hides type errors, makes refactors brittle, and produces unreadable code. Pydantic models make "missing attribute" an impossible state — lean on that.

## 9. No customer-specific names

Nothing under `llming-docs` may reference "Lechler" or any specific customer. This package is meant to be reused across products; customer branding stays in the host.
