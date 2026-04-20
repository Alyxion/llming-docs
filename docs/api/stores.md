# Stores & Manager API

Reference for the core persistence classes. All are importable directly from the top-level package:

```python
from llming_docs import Document, DocumentSessionStore, DocPluginManager
```

---

## `Document`

Pydantic model representing a single document within a conversation.

```python
class Document(BaseModel):
    id: str                          # 12-char uuid hex, auto-generated
    conversation_id: str = ""        # Set by caller; client stamps on IDB write
    type: str = ""                   # plotly | table | text_doc | ...
    name: str = ""                   # Human-readable, used as sidebar label
    data: Any = None                 # Type-specific JSON payload
    version: int = 1                 # Increments on each update
    created_at: float                # Unix timestamp
    updated_at: float                # Unix timestamp

    source: str = "created"          # "created" | "uploaded" | "nudge"
    editable: bool = True            # False for uploaded/nudge-attached docs
    inject_mode: str = "none"        # "none" | "full" | "summary" | "on_demand"
```

### Lifecycle fields

- `source` — how the document came into the store:
    - `"created"` — the LLM (or a tool on behalf of it) created the doc.
    - `"uploaded"` — the user uploaded a file (PDF, DOCX, XLSX) that was extracted into a document.
    - `"nudge"` — a nudge/preset attached the doc as a pre-loaded knowledge item.
- `editable` — when `False`, `update_document` refuses to modify and the UI hides edit controls. Uploaded / nudge-attached docs are non-editable by default.
- `inject_mode` — governs prompt injection:
    - `"none"` — doc is available to tools but never injected into the system prompt.
    - `"full"` — full content injected on every turn.
    - `"summary"` — a generated summary injected.
    - `"on_demand"` — only injected when the LLM explicitly asks via a tool.

### Identity rules

- `id` is generated server-side (`uuid4().hex[:12]`) unless the caller provides one.
- The LLM is instructed (via `DocPluginManager.get_preamble()`) to reuse the same `id` when updating an existing document via a fenced code block. This keeps continuity across `create_document` → `update_document` → re-render cycles.

---

## `DocumentSessionStore`

Thread-safe in-memory document store scoped to a session. One instance per chat session.

```python
store = DocumentSessionStore()
```

### CRUD

```python
def create(
    self,
    type: str,
    name: str,
    data: Any,
    conversation_id: str = "",
    source: str = "created",
    editable: bool = True,
    inject_mode: str = "none",
    skip_validation: bool = False,
) -> Document | list[ValidationError]
```

Returns a `Document` on success or a `list[ValidationError]` on structural failure. Callers MUST check `isinstance(result, list)`. Emits `doc_created` on success.

```python
def update(
    self,
    doc_id: str,
    data: Any = None,
    name: str | None = None,
    skip_validation: bool = False,
) -> Document | list[ValidationError] | None
```

Returns `None` if the doc doesn't exist; otherwise `Document` or `list[ValidationError]`. Records history automatically (see [History & Undo](../concepts/history-undo.md)). Emits `doc_updated`.

```python
def delete(self, doc_id: str) -> bool
```

Returns `True` if deleted. Emits `doc_deleted`.

```python
def undo(self, doc_id: str) -> Document | None
```

Rewinds one version. Emits `doc_updated` with the restored data.

### Query

```python
def get(self, doc_id: str) -> Document | None
def list_all(self) -> list[Document]
def list_by_type(self, doc_type: str) -> list[Document]
def list_by_source(self, source: str) -> list[Document]
```

### Lifecycle

```python
def set_notify_callback(self, callback: Callable[[str, Document], None]) -> None
```

Register a callback invoked on every `doc_created` / `doc_updated` / `doc_deleted`. The host uses this to push events to the client WebSocket.

```python
def restore_from_list(self, docs_data: list[dict]) -> None
```

**Replaces** the store contents with the given list (clearing existing docs and history first). Called on reconnect / conversation switch.

```python
def clear(self) -> None
```

Drops all documents and history without emitting events. Rarely needed directly — `restore_from_list([])` is usually the right call because it preserves the event expectation of downstream code.

---

## `DocPluginManager`

Orchestrates a `DocumentSessionStore` plus the relevant MCP servers for a session.

```python
mgr = DocPluginManager(
    enabled_types=None,                  # None=all, []=none, list=subset
    presentation_templates=None,         # list of templates for PPTX
    requires_providers=None,             # list of provider names to gate activation
)
```

### Attributes

- `mgr.store` — the `DocumentSessionStore`.
- `mgr.enabled_types` — currently enabled type list.
- `mgr.presentation_templates` — PPTX templates in use.

### Methods

```python
def set_enabled_types(self, types: list[str] | None) -> None
```

Change enabled types mid-session (e.g. when a nudge activates). Re-register MCPs after calling.

```python
def get_preamble(self) -> str
```

Build the LLM-facing system prompt fragment. Empty string if no types are enabled. Describes:

- Which fenced code block languages render as documents.
- The data shape for each type.
- Rules for id/name, updates, cross-block references, embedding.
- The `update_document` path language.

```python
def iter_mcp_servers(self) -> Iterator[MCPServerConfig]
```

Yields `MCPServerConfig` objects ready for registration with a chat session.

---

## Public constants & aliases

```python
from llming_docs import ALL_DOC_PLUGIN_TYPES

# ["plotly", "latex", "table", "text_doc", "presentation", "html", "email_draft"]
```

Backward-compat type aliases accepted by `create_document` and `restore_from_list`:

| Old name | New name |
|---|---|
| `word` | `text_doc` |
| `powerpoint` | `presentation` |

These are transparent — the stored `doc.type` is always the new name, but the LLM can still request the old name if it appears in older conversations.
