# Embedding

Documents can embed other documents by reference — a chart inside a Word doc, a table inside a slide, an attachment on an email draft. The referenced data is resolved at render/export time, not duplicated at authoring time.

## The contract

A host document (`text_doc`, `presentation`, `email_draft`) emits an embed marker:

```json
{"type": "embed", "$ref": "<document-id>"}
```

or, in contexts where `$ref` isn't idiomatic (e.g. text_doc sections):

```json
{"type": "embed", "ref": "<document-id>"}
```

The render/export pipeline (`render.render_to`) looks up the target document, consults the `EmbedBehavior` registry for its type, and converts it to whatever the host format needs.

The host document **never branches on what it's embedding**. Add a new document type and every existing host can embed it automatically — no changes in `text_doc_exporter.py`, `pptx_exporter.py`, or the email resolver.

## The `EmbedBehavior` registry

```python
from llming_docs import EmbedBehavior, EMBED_BEHAVIOR

EMBED_BEHAVIOR: dict[str, EmbedBehavior] = {
    "plotly":       EmbedBehavior(mode="graphic", aspect=1.6),
    "latex":        EmbedBehavior(mode="graphic", aspect=None),
    "table":        EmbedBehavior(mode="table"),
    "text_doc":     EmbedBehavior(mode="text"),
    "html":         EmbedBehavior(mode="graphic", aspect=1.6),
    "html_sandbox": EmbedBehavior(mode="graphic", aspect=1.6),
    "presentation": EmbedBehavior(mode="graphic", aspect=16/9),
    "email_draft":  EmbedBehavior(mode="text"),
    "rich_mcp":     EmbedBehavior(mode="graphic", aspect=1.6),
}
```

### `mode`

- **`graphic`** — rasterise to PNG. Used for visual documents (charts, slides, HTML, formulas). Requires client-side rendering (Plotly.toImage, html2canvas, katex). The host document gets an image at the declared aspect ratio.
- **`table`** — native table in the host format. Used for `table` documents. Word gets a native Word table, PPTX gets a native PowerPoint table — never a screenshot.
- **`text`** — inline as text paragraphs/sections. Used for `text_doc` and `email_draft`. Sections and paragraphs merge into the host's flow.

### `aspect`

Width / height ratio. Only used by `graphic` mode:

- `1.6` — classic wide chart / screenshot ratio.
- `16/9` — a slide or full presentation preview.
- `None` — intrinsic ratio. For LaTeX (formula renders at its natural size) — the host decides how to handle it (usually inline at line height).

## What embedding looks like in practice

**Word doc embedding a chart:**

```json
{
  "sections": [
    {"id": "intro", "type": "paragraph", "content": "Q1 revenue grew 15%."},
    {"id": "chart", "type": "embed",     "ref": "plot-a1b2c3"},
    {"id": "after", "type": "paragraph", "content": "See chart above."}
  ]
}
```

On DOCX export: `plot-a1b2c3` is rasterised to PNG (via client render), inserted at the declared aspect ratio, flowed between the paragraphs.

**Slide embedding a table:**

```json
{
  "slides": [{
    "id": "results", "layout": "content",
    "elements": [
      {"type": "text", "content": "Results"},
      {"type": "embed", "ref": "table-x9y8z7"}
    ]
  }]
}
```

On PPTX export: `table-x9y8z7` inserts as a native PowerPoint table with its column types styling the cells.

**Email attachment:**

```json
{
  "attachments": [
    {"ref": "plot-a1b2c3", "name": "Q1 chart.png"},
    {"ref": "doc-444555",  "name": "Q1 report.docx"}
  ]
}
```

On send: each ref resolves according to its type — chart → PNG, text_doc → DOCX, table → XLSX — and attaches to the outgoing MIME message.

## Registering a new embed behavior

When adding a new document type, declaring its embed behavior is mandatory:

```python
from llming_docs import EmbedBehavior, register_embed_behavior

register_embed_behavior("kanban", EmbedBehavior(mode="graphic", aspect=1.6))
```

Forgetting this means the new type silently exports as a placeholder — the pipeline has nothing to do with it. There's no runtime warning; document it in the PR description and check the type appears in `EMBED_BEHAVIOR` before merging.

For graphic modes, you also need:

- A client-side rasteriser registered for the type (the frontend plugin system).
- An entry in the exporter's embed-graphic path (usually already generic — adding a type doesn't require exporter changes when `mode=graphic` and the frontend rasteriser handles it).

For table and text modes:

- The exporter needs to understand the source document's data shape. Since both `table` and `text_doc` already have exporters, reusing their data shapes is the cheap path.

## Reference resolution

- Only forward references work — a document can reference others that exist at render time. Future "late-bound" embeds are not supported.
- Circular references are rejected: `A` embeds `B` embeds `A` raises `ValueError("circular reference detected")`.
- Missing references (the `$ref` points to a deleted or non-existent doc) render a placeholder with the missing id, but do not fail the export. The host shows a warning indicator on the affected section.

## `$ref` vs `ref`

Two forms exist for historical reasons:

- `$ref` — used in JSON Schema-like contexts (Plotly traces embedded in a plot, presentation elements).
- `ref` — used in `text_doc` embed sections and email attachments.

Both are accepted by the resolver. New code should prefer `$ref` unless it's adding a section to an existing type that uses `ref`.
