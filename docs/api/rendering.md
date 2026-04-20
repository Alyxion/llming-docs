# Render & Embed API

Reference for the export pipeline and cross-document embedding. All symbols are importable from the top-level package:

```python
from llming_docs import (
    render_to, can_render, can_embed,
    RenderResult, RenderContext, RENDER_CAPABILITIES,
    EmbedBehavior, EMBED_BEHAVIOR, EMBED_RULES,
    get_embed_behavior, get_embed_format, register_embed_behavior,
)
```

---

## `render_to`

Single entry point for exports.

```python
def render_to(
    doc_type: str,
    spec: Any,
    target_format: str,
    context: RenderContext | None = None,
) -> RenderResult
```

- `doc_type` — the source document type (`"plotly"`, `"table"`, `"text_doc"`, …).
- `spec` — the document's `data` payload.
- `target_format` — `"docx" | "pptx" | "xlsx" | "csv" | "html" | "png" | "json"`.
- `context` — optional `RenderContext` carrying embed resolution and templates.

Returns a `RenderResult`:

```python
@dataclass
class RenderResult:
    data: bytes
    mime_type: str
    filename: str
```

Raises `ValueError` if the type cannot render to the requested format. Use `can_render(doc_type, target_format)` to check without raising.

## `RenderContext`

```python
@dataclass
class RenderContext:
    resolve_embed: Callable[[str], Document | None] | None = None
    templates: list | None = None   # PPTX templates
```

`resolve_embed` is a callable the embed pipeline uses to look up referenced documents — usually `store.get`. If `None`, embeds fall back to placeholders.

## `RENDER_CAPABILITIES`

A `dict[str, set[str]]` declaring which target formats each doc type supports:

```python
RENDER_CAPABILITIES = {
    "plotly":       {"png", "json"},
    "table":        {"xlsx", "csv", "html"},
    "text_doc":     {"docx", "html"},
    "presentation": {"pptx"},
    "html":         {"html"},
    "latex":        {"png"},
    "email_draft":  set(),          # exports via email provider, not render_to
}
```

Extend this when adding a new type (see [Extending](../integration/extending.md)).

## `can_render`

```python
can_render(doc_type: str, target_format: str) -> bool
```

True iff `target_format` is in `RENDER_CAPABILITIES[doc_type]`.

---

## Embedding

### `EmbedBehavior`

Frozen dataclass describing how a document type behaves when embedded in another document.

```python
@dataclass(frozen=True)
class EmbedBehavior:
    mode: str                   # "graphic" | "table" | "text"
    aspect: float | None = None # width/height for graphic mode
```

- `"graphic"` — host document gets a PNG. Requires client-side rasterisation.
- `"table"` — host document gets a native table (headers + rows) in its format.
- `"text"` — host document inlines the source's text content / sections.

`aspect`:

- Float (e.g. `1.6`, `16/9`) — preferred width/height ratio for the rasterised output.
- `None` — intrinsic size (used by LaTeX; the formula renders at its natural dimensions).

### `EMBED_BEHAVIOR`

The registry — `dict[str, EmbedBehavior]`. Inspect it to see which types can be embedded:

```python
from llming_docs import EMBED_BEHAVIOR
for doc_type, behavior in EMBED_BEHAVIOR.items():
    print(f"{doc_type:15s} → {behavior.mode:8s}  aspect={behavior.aspect}")
```

### `register_embed_behavior`

```python
register_embed_behavior(doc_type: str, behavior: EmbedBehavior) -> None
```

Add or override an entry. Call this at module-import time when introducing a new document type:

```python
register_embed_behavior("kanban", EmbedBehavior(mode="graphic", aspect=1.6))
```

### `get_embed_behavior`

```python
get_embed_behavior(doc_type: str) -> EmbedBehavior | None
```

Returns the registered behavior or `None`. Use this from exporters/renderers — don't access `EMBED_BEHAVIOR` directly.

### `get_embed_format`

```python
get_embed_format(doc_type: str, host_format: str) -> str
```

Returns the concrete target format the pipeline will use when embedding `doc_type` into a document being exported to `host_format`. Example:

```python
get_embed_format("plotly", "docx")  # "png"  (graphic mode, DOCX wants raster)
get_embed_format("table",  "docx")  # "native_table" (native Word table)
get_embed_format("table",  "pptx")  # "native_table" (native PowerPoint table)
get_embed_format("text_doc", "docx") # "inline_sections"
```

### `EMBED_RULES`

A `dict[tuple[str, str], str]` of overrides used by the embed pipeline to map a `(source_type, host_format)` pair to a concrete embed format. Most entries are derived from `EMBED_BEHAVIOR`; `EMBED_RULES` lets you add special cases (e.g. a `(source, host)` pair that deviates from the default). Rarely modified — prefer adjusting `EMBED_BEHAVIOR`.

### `can_embed`

```python
can_embed(source_type: str, host_format: str) -> bool
```

True if the pipeline has a rule for this combination.

---

## Practical examples

### Export a document

```python
result = render_to(
    doc_type=doc.type,
    spec=doc.data,
    target_format="docx",
    context=RenderContext(resolve_embed=store.get),
)
with open("report.docx", "wb") as f:
    f.write(result.data)
```

### Check before exposing an export button

```python
from llming_docs import can_render, RENDER_CAPABILITIES

formats_for_this_doc = RENDER_CAPABILITIES.get(doc.type, set())
if "pptx" in formats_for_this_doc:
    show_export_button("PPTX")
```

### Register a new embedable type

```python
# In your package's __init__.py or module load path:
from llming_docs import EmbedBehavior, register_embed_behavior

register_embed_behavior("mindmap", EmbedBehavior(mode="graphic", aspect=1.6))
```

From this point, `mindmap` documents can be embedded inside any `text_doc` or `presentation` without any further changes in those types' exporters.
