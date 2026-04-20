# Docking into a chat frontend

"Docking" means wiring `llming-docs` into a host chat framework's session lifecycle. `llming-lodge` is the reference implementation; the contract below is what any host must satisfy.

!!! info "See also"
    [Frontend Assets](frontend-assets.md) documents the specific files the
    host mounts, the registration entry points, the CSS class naming
    convention (`ldoc-*` vs `cv2-*`), and the host-agnostic DOM conventions
    (`data-ldoc-scrollable`, `ldoc:invalidate-cache` CustomEvent) that
    plugins use to communicate without format knowledge in the host.

## Client UI: documents workspace (reference implementation)

`llming-lodge`'s chat page renders documents in a **right-hand workspace panel** — never inline in the message transcript.

**Tab strip.** VS-Code-style, `flex-wrap: wrap` for multi-row overflow. One tab per open document, each with the doc's material icon, name (truncated with tooltip), version badge, and close button. The close button hides the tab — the document stays in the store and is still reachable via the other docs in the strip or the sidebar listing.

**Body.** The active tab's document renders into the panel body via the regular doc plugin registry — **as the full editor** (toolbar + contentEditable body), not a read-only preview. This is achieved by having the panel body under `.cv2-workspace-body` and extending the CSS allowlist that unhides `.cv2-rich-toolbar` inside `.cv2-doc-plugin-block` (originally only enabled in `.cv2-preview-windowed` / `.cv2-preview-maximized`). Every doc type's plugin already produces a full editor when rendered; the panel just makes it visible.

**Dock / undock.** The panel header carries two buttons:

- An **undock** icon (`open_in_new`) that pops the panel out of the chat-app's flex row into a floating, draggable, resizable window over the chat. When undocked the icon flips to `push_pin` (re-dock). Drag is wired to the header via `pointerdown` / `pointermove`; `resize: both` on the panel plus a box-shadow gives the window feel.
- A **close** (`×`) that collapses the panel entirely (state returns to docked when re-opened).

State model on the chat app (see `chat-documents.js`):

- `workspaceOpen: bool` — is the panel visible at all.
- `workspaceFloating: bool` — is it in the floating state (else docked).
- `openTabIds: string[]` — ordered list of doc ids that have tabs.
- `activeTabId: string | null` — currently shown doc.

Life cycle events:

- `doc_created` → add tab, activate, auto-open the panel.
- `doc_updated` → activate that doc's tab, re-render body with fresh data.
- `doc_deleted` → close tab, activate next or collapse the panel.
- Conversation switch → seed tabs from restored docs, activate the most recently updated one, auto-open.

**Mobile (≤ 720px viewport).** The undock button is hidden via CSS media query so touch users can't accidentally trigger a floating window on a small screen. The panel still opens, but always as a full-width overlay on top of the chat. The floating state is also defensively overridden in the same media query so programmatic toggles no-op visually.

**Why not render the document inline in the transcript?** Documents grow and change across turns. An inline preview per edit turn either stacks up (N duplicates of the same doc) or sits at the create-turn and forces the user to scroll. A stable, docked editor keeps the doc in one place, at full size, with the real toolbar. Inline preview injection was removed as part of this — the chat transcript shows prose only.

## Per-session setup

```python
from llming_docs import DocPluginManager

def create_session(user_config, preset):
    mgr = DocPluginManager(
        enabled_types=preset.doc_plugins,   # None = all, [] = none
        presentation_templates=preset.templates,
    )
    store = mgr.store

    # 1. Forward store events to the client
    store.set_notify_callback(lambda event, doc: ws.send({
        "type": event,              # "doc_created" | "doc_updated" | "doc_deleted"
        "document": doc.model_dump(),
    }))

    # 2. Register MCPs with the LLM session
    for mcp_config in mgr.iter_mcp_servers():
        session.register_mcp(mcp_config)

    # 3. Inject the LLM preamble
    session.base_system_prompt += mgr.get_preamble()

    return SessionEntry(mgr=mgr, store=store, session=session)
```

That's the setup. Nothing else is required to start persisting documents from LLM tool calls.

## WebSocket message types

The host is responsible for the following message types on the chat WebSocket:

### Server → client

| Type | Payload | Meaning |
|---|---|---|
| `doc_created` | `{document: Document}` | A new document was created. Add to sidebar + IDB. |
| `doc_updated` | `{document: Document}` | Document data changed. Replace in sidebar + IDB. |
| `doc_deleted` | `{document: {id: str}}` | Document was deleted. Remove from sidebar + IDB. |
| `doc_list` | `{documents: [Document]}` | Full snapshot (response to `doc_list_request`). |

### Client → server

| Type | Payload | Meaning |
|---|---|---|
| `doc_restore` | `{documents: [Document]}` | On reconnect/conversation-switch: replace server store with this list. |
| `doc_list_request` | `{}` | Ask the server to send a fresh `doc_list`. |

## Reconnect / conversation switch flow

The client's IDB is the source of truth for which documents belong to which conversation. On reconnect, the client sends the authoritative list:

```
client                                    server
  |                                         |
  |-- load_conversation {id, messages} ---->|  (rehydrate history)
  |-- doc_restore {documents: [...]} ----->|  store.restore_from_list(docs)
  |                                         |   → replaces store, clears history
  |                                         |
  |<-- (subsequent doc_updated events) -----|  (as the LLM edits)
```

Important:

- `store.restore_from_list(docs)` **replaces** the store. Send the full current list, not a delta.
- Always send `doc_restore` after `load_conversation`, even if the list is empty — an empty list explicitly clears stale docs from the previous conversation.
- The client's IDB keyed on `conversation_id` is the canonical store. The server's `DocumentSessionStore` is an ephemeral cache rebuilt from that.

## Persisting documents client-side

Whatever the host uses for client-side storage (IDB in a browser, SQLite on desktop), it needs to:

1. On `doc_created` / `doc_updated` — save the document keyed by `(conversation_id, doc.id)`. Stamp `conversation_id` with the active conversation before writing, so the index is correct even if the server initially returns `conversation_id=""`.
2. On `doc_deleted` — remove by id.
3. On conversation switch — load all docs for the target conversation, set the in-memory `documents` array, send `doc_restore` to the server.
4. On conversation save — include the current `documents` array in the saved conversation blob (optional — for faster cold reloads).

## Preset / nudge awareness

When a nudge or project is activated mid-conversation, its `doc_plugins` field may restrict the enabled types:

```python
mgr.set_enabled_types(preset.doc_plugins)
```

After this call, `mgr.get_preamble()` returns the reduced preamble and `mgr.iter_mcp_servers()` yields only the relevant MCPs. The host should re-register MCPs and update the system prompt.

Documents that were created with a type now disabled remain accessible (they're still in the store) but can't be edited with per-type tools. `update_document` still works on them.

## Exports

The host exposes export endpoints that call `render_to`:

```python
from llming_docs import render_to, RenderContext

@router.post("/api/llming/export/{doc_id}")
async def export_doc(doc_id: str, format: str, entry=Depends(get_session)):
    doc = entry.store.get(doc_id)
    if not doc:
        return Response(status_code=404)

    result = render_to(
        doc_type=doc.type,
        spec=doc.data,
        target_format=format,  # "docx" | "pptx" | "xlsx" | "csv" | "html" | "png"
        context=RenderContext(resolve_embed=entry.store.get),
    )
    return Response(
        content=result.data,
        media_type=result.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{result.filename}"'},
    )
```

`RenderContext.resolve_embed` is a callable `(doc_id) -> Document | None` that the embed pipeline uses to look up referenced documents. Usually just `store.get`.

For client-rendered formats (PNG rasterisation of Plotly/HTML), the host coordinates with the frontend — the exporter returns a placeholder and the client rasterises before final delivery. `llming-lodge` has utility JS for this flow.

## Lifecycle cleanup

On WebSocket disconnect (or session end), the host disposes the session — including `mgr`. `DocumentSessionStore` has no resources beyond memory (no file handles, no threads beyond the lock), so GC is sufficient. No explicit `close()` is required.
