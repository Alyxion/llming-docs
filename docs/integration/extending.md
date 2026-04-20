# Adding a new document type

End-to-end checklist for introducing a new document type — e.g. `kanban`, `diagram`, `mindmap`. No changes are needed in host chat frameworks if every step below is completed.

## 1. Validator — `validators.py`

Define the structural checks. Keep errors actionable.

```python
def _validate_kanban(data: Any) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if not isinstance(data, dict):
        return [_err("invalid_root", "kanban data must be an object",
                     "Wrap the payload in a JSON object")]

    columns = data.get("columns")
    if not isinstance(columns, list):
        errors.append(_err("missing_columns", "'columns' must be a list",
                           "Add a 'columns' array with objects", path="columns"))
        return errors

    for i, col in enumerate(columns):
        if not isinstance(col, dict):
            errors.append(_err("invalid_column", "Each column must be an object",
                               "Replace with {id, name, cards: [...]}",
                               path=f"columns/{i}"))
            continue
        if "id" not in col:
            errors.append(_err("missing_id", "Column is missing 'id'",
                               "Add a unique 'id' string",
                               path=f"columns/{i}/id"))
    return errors

_VALIDATORS["kanban"] = _validate_kanban
```

## 2. Embed behavior — `render.py`

Declare how kanban boards behave when embedded in other documents. Required — skipping this makes embeds silently render as placeholders.

```python
EMBED_BEHAVIOR["kanban"] = EmbedBehavior(mode="graphic", aspect=1.6)
```

Pick `mode`:

- `graphic` — most visual types. Requires a client-side rasteriser.
- `table` — only if the data is genuinely tabular and would fit a Word/PowerPoint table.
- `text` — for structured text documents that flow in a host document's body.

## 3. (Optional) Type-specific MCP — `kanban_mcp.py`

Skip this entirely if `UnifiedDocumentMCP` covers the editing story — most new types can start without a per-type MCP.

```python
from llming_models.tools.mcp import InProcessMCPServer
from llming_docs.document_store import DocumentSessionStore

class KanbanDocumentMCP(InProcessMCPServer):
    def __init__(self, store: DocumentSessionStore) -> None:
        self._store = store

    async def list_tools(self) -> list[dict]:
        return [
            {
                "name": "kanban_add_card",
                "displayName": "Add Kanban Card",
                "icon": "add_card",
                "description": "Add a card to a kanban column.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {"type": "string"},
                        "column_id":   {"type": "string"},
                        "title":       {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["document_id", "column_id", "title"],
                },
            },
        ]

    async def call_tool(self, name: str, arguments: dict) -> str:
        if name == "kanban_add_card":
            doc = self._store.get(arguments["document_id"])
            if not doc:
                return json.dumps({"error": "not_found",
                                   "message": "Document not found"})
            # ... apply edit, call self._store.update(...), return JSON
```

Always wrap `store.update()` in the `isinstance(result, list)` validation pattern.

## 4. Register with `DocPluginManager` — `manager.py`

```python
ALL_DOC_PLUGIN_TYPES.append("kanban")

_PREAMBLE_LINES["kanban"] = (
    "- ```kanban — Kanban board "
    "(JSON: {columns: [{id, name, cards: [{id, title, description}]}]})"
)

# Only if step 3 was done:
_MCP_SERVERS["kanban"] = {
    "module": "llming_docs.kanban_mcp",
    "class_name": "KanbanDocumentMCP",
    "label": "Kanban Boards",
    "description": "Edit kanban board documents",
}
TYPE_TOOL_PREFIXES["kanban"] = "kanban_"
```

Run:

```python
from llming_docs import DocPluginManager
mgr = DocPluginManager(enabled_types=["kanban"])
print(mgr.get_preamble())
```

The preamble should mention kanban and `list(mgr.iter_mcp_servers())` should include the new MCP (if step 3 was done).

## 5. Client-side renderer — `frontend/static/plugins/doc-plugins.js`

The **client** rendering code also lives in llming-docs now. Add your plugin object + registration call to `doc-plugins.js` (the IIFE bundle):

```javascript
// Inside the IIFE
const kanbanPlugin = {
  inline: true,
  sidebar: true,
  fencedBlockAllowed: false,   // tool-only policy
  render: async (container, rawData, blockId) => {
    const spec = _parseJSON(rawData);
    if (!spec) { container.textContent = rawData; return; }

    const root = document.createElement('div');
    root.className = 'ldoc-kanban';                  // ldoc- prefix, not cv2-
    root.dataset.ldocScrollable = '1';               // host preserves scroll
    root.dataset.ldocCacheKey = 'kanban:edits';      // optional cache marker
    // ...build DOM from spec.columns...
    container.appendChild(root);
  },
};

// At the bottom of the file, add to the registration function:
window.registerLlmingDocPlugins = function(registry) {
  // ... existing registrations ...
  registry.register('kanban', { ...kanbanPlugin, fencedBlockAllowed: false });
};
```

If your plugin caches per-doc state client-side, listen for the host's
cache-invalidation event:

```javascript
document.addEventListener('ldoc:invalidate-cache', (ev) => {
  if (ev.detail?.docId !== _docId) return;
  try { localStorage.removeItem('kanban:edits:' + _docId); } catch (_) {}
});
```

See [Frontend Assets](frontend-assets.md) for the full contract (class
naming, data attributes, CustomEvents, CSS variables) and
[Principles #0a](../principles.md#0a-format-code-is-100-in-llming-docs)
for the policy that keeps the host free of format knowledge.

## 6. (Optional) Exporter — `kanban_exporter.py`

If the type needs a native export format beyond PNG, add an exporter:

```python
def export_to_html(spec: dict) -> bytes:
    # Build an HTML representation
    return html.encode("utf-8")
```

Wire it into `render.render_to`:

```python
RENDER_CAPABILITIES["kanban"] = {"html", "png"}

def _render_kanban(spec, target_format, context):
    if target_format == "html":
        return RenderResult(
            data=export_to_html(spec),
            mime_type="text/html",
            filename=f"{spec.get('title', 'kanban')}.html",
        )
    ...
```

## 7. Tests

At minimum:

```python
def test_kanban_validator_rejects_non_dict():
    errors = validate_document("kanban", [])
    assert any(e.code == "invalid_root" for e in errors)

def test_kanban_embed_behavior_registered():
    from llming_docs import EMBED_BEHAVIOR
    assert "kanban" in EMBED_BEHAVIOR

def test_kanban_in_manager():
    mgr = DocPluginManager(enabled_types=["kanban"])
    assert "kanban" in mgr.enabled_types
    assert any("kanban" in line for line in mgr.get_preamble().split("\n"))
```

If the type got a per-type MCP, add a test that creates, edits, reads, and undoes a kanban doc end-to-end through the tool interface.

## Common mistakes

- **Forgetting `register_embed_behavior`.** The type works standalone but silently degrades when embedded in a text_doc or presentation.
- **Skipping validation.** The LLM will eventually generate an almost-right payload; without a validator, the doc store happily persists it and every subsequent edit propagates the bug.
- **Writing the type-specific MCP before needing it.** Most edits can be expressed via `UnifiedDocumentMCP`'s path language. Start without a per-type MCP; add one only when specific tools prove awkward to express as generic path ops.
- **Baking HTML into `doc.data`.** Breaks rule #1 ([Principles](../principles.md)). Data is pure JSON; the renderer builds HTML.
