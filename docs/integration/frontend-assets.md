# Client-Side Frontend Assets

All client code for rendering and editing documents is owned by `llming-docs`. Host chat frameworks mount the asset directory as a static route and load a few well-known scripts — no format-specific knowledge on the host side.

## Layout

```
llming_docs/frontend/
├── __init__.py             # MANIFEST + metadata helpers (Python API)
└── static/
    ├── plugins/
    │   ├── doc-plugin-registry.js   # DocPluginRegistry class
    │   ├── block-data-store.js      # cross-block refs + $ref resolver
    │   ├── ai-edit-shared.js        # AI inline-edit helper (text_doc + email_draft)
    │   └── doc-plugins.js           # all 7 doc-type plugin bundles
    ├── css/
    │   └── doc-plugins.css          # every format-specific stylesheet
    └── vendor/                      # reserved for future bundled vendor libs
```

## Host contract (minimum requirements)

### 1. Python — mount the static dir

```python
from llming_docs import get_static_dir
from starlette.staticfiles import StaticFiles

app.mount("/doc-static", StaticFiles(directory=str(get_static_dir())), name="doc-static")
```

### 2. Python — include format metadata in the frontend config

The host never hard-codes a list of document types, icons, or labels. It reads everything from llming-docs at startup:

```python
from llming_docs import DOC_ICONS, get_mcp_group_labels

frontend_config = ChatFrontendConfig(
    # ... host-specific fields ...
    doc_icons=dict(DOC_ICONS),              # {type: material-icon-name}
    doc_group_labels=get_mcp_group_labels(), # {type: MCP-group-label}
)
```

This is serialised as `window.__CHAT_CONFIG__` on the client; JS reads:

- `window.__CHAT_CONFIG__.docIcons` — for sidebar / tab icons.
- `window.__CHAT_CONFIG__.docGroupLabels` — for auto-enabling MCP tool groups on `doc_created`.

### 3. HTML — script load order

Load in two phases so the registry is available before plugins try to register:

```html
<!-- Phase 1: foundation (available as window.DocPluginRegistry, window.BlockDataStore, resolveBlockRefs, applyCrossTypeCompat) -->
<script src="/doc-static/plugins/doc-plugin-registry.js"></script>
<script src="/doc-static/plugins/block-data-store.js"></script>

<!-- Phase 2: plugin bundle + shared AI edit helper -->
<script src="/doc-static/plugins/ai-edit-shared.js"></script>
<script src="/doc-static/plugins/doc-plugins.js"></script>

<!-- Stylesheet -->
<link rel="stylesheet" href="/doc-static/css/doc-plugins.css">
```

### 4. JS — register plugins with the host registry

```javascript
const registry = new window.DocPluginRegistry();
registry.setBlockStore(new window.BlockDataStore());
// The host's own plugins first (mermaid, rich_mcp, etc.):
if (window.registerBuiltinPlugins) window.registerBuiltinPlugins(registry);
// Then the llming-docs-owned document plugins:
if (window.registerLlmingDocPlugins) window.registerLlmingDocPlugins(registry);
```

After these two calls, `registry.has('text_doc')` / `registry.render('table', container, data, blockId)` / etc. work for every llming-docs type.

---

## Host-agnostic conventions

Format plugins communicate with the host through a handful of **well-known DOM attributes** and **CustomEvents**. The host never queries format-specific class names.

### `data-ldoc-scrollable`

Plugins with an internal scroll container set `data-ldoc-scrollable="1"` on that element. The host uses it to preserve scroll position across re-renders:

```javascript
// Plugin (doc-plugins.js, text_doc plugin)
doc.dataset.ldocScrollable = '1';

// Host (chat-documents.js, workspace panel)
const prev = body.querySelector('[data-ldoc-scrollable]');
const prevScrollTop = prev ? prev.scrollTop : body.scrollTop;
// ...re-render...
requestAnimationFrame(() => {
  const next = container.querySelector('[data-ldoc-scrollable]');
  (next || body).scrollTop = prevScrollTop;
});
```

### `data-ldoc-cache-key`

Plugins that persist per-doc state in `localStorage` mark their editable with `data-ldoc-cache-key="<prefix>"`. The host doesn't read the value; it's there so a future per-plugin dev-tools "clear all caches" feature works without host-side knowledge.

### CustomEvent `ldoc:invalidate-cache`

When the host re-renders a doc because server state changed (via `doc_updated`), it dispatches this event. Plugins owning any client-side cache for that doc self-clear:

```javascript
// Host side: fires before calling registry.render()
document.dispatchEvent(new CustomEvent('ldoc:invalidate-cache', {
  detail: { docId: doc.id },
}));

// Plugin side: listens, checks docId, drops its cache
document.addEventListener('ldoc:invalidate-cache', (ev) => {
  if (ev.detail?.docId !== _docId) return;
  try { localStorage.removeItem('text_doc:edits:' + _docId); } catch (_) {}
});
```

The host never names a cache key. Each plugin owns its own storage scheme.

---

## CSS class naming

Two prefixes, two ownership domains:

### `ldoc-*` — owned by llming-docs

Format plugins create DOM with these classes. All format-specific stylesheets target them.

Examples: `ldoc-text`, `ldoc-word`, `ldoc-table`, `ldoc-table-wrapper`, `ldoc-pptx`, `ldoc-pptx-slide`, `ldoc-pptx-lightbox-*`, `ldoc-html`, `ldoc-html-card`, `ldoc-email-draft`, `ldoc-latex`, `ldoc-rich-toolbar`, `ldoc-ai-*`, `ldoc-export-btn`, `ldoc-source-panel`.

Rule: a plugin author changes/adds `ldoc-*` classes freely. No host PR required.

### `cv2-*` — owned by the host

Classes the host sets on the chat app shell. llming-docs plugins reference them when they need to interact with host UI (e.g. the attachment preview popover) or pick up theme state.

Legitimate `cv2-*` references inside llming-docs:

| Class | Why llming-docs uses it |
|---|---|
| `cv2-dark` | Theme scope — dark-mode overrides are written as `#chat-app.cv2-dark .ldoc-foo {…}` |
| `cv2-active` | Generic active-state modifier |
| `cv2-spin` | Generic spinner animation name |
| `cv2-doc-plugin-block` | Outer container class the host wraps each plugin render in |
| `cv2-doc-plugin-streaming` | Streaming-spinner placeholder the host creates during LLM streaming |
| `cv2-preview-popover`, `cv2-preview-title` | Host's attachment-popover DOM (the email plugin updates the popover title when subject changes) |

Any other `cv2-*` reference inside llming-docs is a bug.

---

## CSS variables

llming-docs never defines colors directly — it reads the host's theme via `var(--chat-*)`:

| Variable | Role |
|---|---|
| `var(--chat-accent)` / `var(--chat-accent-rgb)` | Primary accent colour |
| `var(--chat-surface)` | Panel / card background |
| `var(--chat-text)` / `var(--chat-text-muted)` | Foreground text |
| `var(--chat-border)` / `var(--chat-border-strong)` | Borders |

The host redefines these per theme (inside `#chat-app.cv2-dark { … }` etc). Every `ldoc-*` rule that uses a colour does so via a variable, so dark/light switches flip the whole document surface automatically with no code in llming-docs.

---

## Plugin contract (for authors extending llming-docs)

Each plugin registered via `window.registerLlmingDocPlugins` is a plain object:

```javascript
const myPlugin = {
  inline: true,                // renders inline (vs. as a document-panel item)
  sidebar: true,               // track in the sidebar after render (default true)
  fencedBlockAllowed: false,   // TOOL-ONLY policy — fenced ```mytype blocks are NOT rendered
  loader: async () => { /* optional: load vendor libs before first render */ },
  render: async (container, rawData, blockId) => {
    const spec = _parseJSON(rawData);
    // ...build DOM...
    // Mark scrollable / cacheable elements with host-agnostic attributes
    // doc.dataset.ldocScrollable = '1';
  },
};
```

The plugin bundle (`doc-plugins.js`) is an IIFE — all helpers + plugin implementations are local. Only `window.registerLlmingDocPlugins` is exposed.

See [Extending](extending.md) for the full end-to-end recipe (Python + JS + CSS + manifest).

---

## Phase history (what moved, what stayed)

Documenting the refactor so future contributors don't recreate the split mistakes:

### What moved from the host into llming-docs

| From | To | Reason |
|---|---|---|
| `static/chat/plugins/doc-plugin-registry.js` | `frontend/static/plugins/doc-plugin-registry.js` | Registry is doc-system infrastructure |
| `static/chat/plugins/block-data-store.js` | `frontend/static/plugins/block-data-store.js` | Cross-block `$ref` resolution has per-type compatibility aliasing |
| `static/chat/plugins/ai-edit-shared.js` | `frontend/static/plugins/ai-edit-shared.js` | Shared by text_doc + email_draft plugins |
| All 7 doc plugin implementations (~4000 lines) from `builtin-plugins.js` | `frontend/static/plugins/doc-plugins.js` | Format-specific render code |
| ~2200 lines of `.cv2-doc-*` / `.cv2-rich-toolbar` / `.cv2-pptx-*` / `.cv2-email-*` CSS | `frontend/static/css/doc-plugins.css` | Format-specific styling |
| `FORBIDDEN_FENCED_DOC_LANGS` hard-coded list | `llming_docs.frontend.FORBIDDEN_FENCED_DOC_LANGS` | Derived from manifest |
| `DOC_ICONS` hard-coded map | `llming_docs.frontend.DOC_ICONS` | Derived from manifest |
| `_docGroupLabels` hard-coded map | `llming_docs.get_mcp_group_labels()` | Derived from `_MCP_SERVERS` + aliases |

### What stayed in the host

- Chat shell (sidebar, conversation list, message rendering).
- Attachment hover/preview popover system (`_pv*` functions, `.cv2-preview-*` classes).
- Non-document plugins: `mermaid`, `rich_mcp`, `kantini_result`, `followup`. These register themselves via the host's own `registerBuiltinPlugins` and are unrelated to `DocumentSessionStore`.
- Product-number rich_mcp renderer (customer-specific; rich_mcp payload, not a document type).
- `_cv2DocApi` debug helpers.
- Workspace panel UI (tabs, undock, floating state) — that's host chrome around the plugin's render area.

### Class renames applied

- `cv2-doc-text` → `ldoc-text`
- `cv2-doc-word` → `ldoc-word`
- `cv2-doc-table-*` → `ldoc-table-*`
- `cv2-doc-pptx-*` → `ldoc-pptx-*`
- `cv2-pptx-lightbox-*` → `ldoc-pptx-lightbox-*`
- `cv2-doc-html-*` → `ldoc-html-*`
- `cv2-doc-latex` → `ldoc-latex`
- `cv2-rich-toolbar*` → `ldoc-rich-toolbar*`
- `cv2-email-*` → `ldoc-email-*`
- `cv2-ai-*` → `ldoc-ai-*`
- `cv2-doc-export-btn` → `ldoc-export-btn`
- `cv2-doc-source-*` → `ldoc-source-*`
- `cv2-doc-card*` → `ldoc-card*`
- `cv2-doc-embed` → `ldoc-embed`
- `cv2-doc-flash` → `ldoc-flash`
- … and ~100 others following the same `cv2-[-]*doc-` → `ldoc-` pattern.

CSS variables: `var(--cv2-text*)` / `var(--cv2-surface*)` / etc. → `var(--chat-text*)` / `var(--chat-surface*)` — matching the host's actual theme tokens.
