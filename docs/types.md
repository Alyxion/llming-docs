# Document Types

Seven document types are supported out of the box. Each has a canonical data shape, a set of exporters, and an `EmbedBehavior` declaring how it behaves when embedded in another document.

!!! warning "All types are tool-only"
    Every document type below is created via `create_document(type, name, data)`
    and edited via `update_document` or per-type tools — **never** via fenced
    code blocks in assistant responses. The data shapes shown are what you
    pass as the `data` argument to `create_document`. See
    [Principles #0](principles.md#0-tool-only-creation).

## Summary

| Type | Data shape | Export | Embeds as |
|---|---|---|---|
| `plotly` | `{data: [...], layout: {...}}` | PNG | graphic (1.6 ratio) |
| `latex` | `{formula: "..."}` | PNG | graphic (intrinsic ratio) |
| `table` | `{columns: [...], rows: [...]}` or `{sheets: [...]}` | XLSX, CSV, HTML | table |
| `text_doc` | `{sections: [{id, type, content, ...}]}` | DOCX, HTML | text |
| `presentation` | `{title, author, slides: [{id, title, layout, elements: [...]}]}` | PPTX | graphic (16:9) |
| `html` / `html_sandbox` | `{html, css, js, title}` | HTML | graphic (1.6 ratio) |
| `email_draft` | `{subject, to, cc, bcc, body_html, attachments: [{ref, name}]}` | — | text |

Backward-compat aliases accepted: `word` → `text_doc`, `powerpoint` → `presentation`.

---

## plotly

Full Plotly.js specification — the `data` field is the array of traces, `layout` is the Plotly layout object.

```json
{
  "data": [
    {"type": "bar", "x": ["EU", "US"], "y": [420000, 310000]}
  ],
  "layout": {"title": "Q1 Revenue"}
}
```

Tools: `plotly_add_trace`, `plotly_update_trace`, `plotly_update_layout`, `plotly_get_data`, and generic `update_document`.

Exports via the client (Plotly.toImage → PNG) when embedded.

## latex

Minimal — a single LaTeX formula string. Rendered with KaTeX on the client, rasterised to PNG on embed.

```json
{"formula": "E = mc^2"}
```

## table

Either a single sheet (`columns` + `rows`) or a multi-sheet spreadsheet (`sheets: [...]`).

```json
{
  "columns": [
    {"name": "Region", "type": "text"},
    {"name": "Revenue", "type": "number"}
  ],
  "rows": [
    ["EU", 420000],
    ["US", 310000]
  ]
}
```

Multi-sheet:

```json
{
  "sheets": [
    {"name": "Q1", "columns": [...], "rows": [...]},
    {"name": "Q2", "columns": [...], "rows": [...]}
  ]
}
```

Column types: `text`, `number`, `date`, `currency`, `percent`, `boolean`. The exporter uses these to format cells and apply column widths.

Tools: `table_add_row`, `table_update_cell`, `table_add_sheet`, `table_freeze_panes`, `table_export_xlsx`, `table_export_csv`.

XLSX export supports: multi-sheet, frozen panes, speaker notes, typed cells, auto-sized columns.

## text_doc

A sequence of typed sections. Supports inline references to other documents via `{"type": "embed", "ref": "<id>"}`.

```json
{
  "title": "Quarterly Report",
  "sections": [
    {"id": "s1", "type": "heading", "content": "Q1 2026", "level": 1},
    {"id": "s2", "type": "paragraph", "content": "Revenue grew 15% YoY."},
    {"id": "s3", "type": "embed",     "ref": "chart-uuid"},
    {"id": "s4", "type": "paragraph", "content": "See the chart above."}
  ]
}
```

Section types: `heading` (with `level`), `paragraph`, `bullet_list` / `numbered_list` (with `items`), `embed`, `image`, `page_break`, `table_of_contents`.

Tools: `text_doc_add_section`, `text_doc_update_section`, `text_doc_move_section`, `text_doc_remove_section`, `text_doc_export_docx`.

On DOCX export, embeds resolve automatically:

- Plotly / LaTeX / HTML sandboxes → PNG image.
- Tables → native Word table with column widths.
- Text documents → inlined sections.

## presentation

Slide deck with optional branded template.

```json
{
  "title": "Kickoff",
  "author": "Sales Team",
  "slideNumbers": true,
  "slides": [
    {
      "id": "cover", "layout": "title",
      "elements": [
        {"type": "text", "content": "Project Kickoff", "role": "title"},
        {"type": "text", "content": "2026 Roadmap",   "role": "subtitle"}
      ]
    },
    {
      "id": "s2", "layout": "content",
      "notes": "Remember to mention the hiring plan.",
      "elements": [
        {"type": "text", "content": "Goals"},
        {"type": "chart", "ref": "chart-uuid"}
      ]
    }
  ]
}
```

Element types: `text`, `bullet_list`, `chart` (via `$ref`), `table` (via `$ref` or inline), `image`, `embed` (generic `$ref` — behavior from `EMBED_BEHAVIOR`).

Tools: `pptx_add_slide`, `pptx_update_element`, `pptx_set_notes`, `pptx_reorder_slides`, `pptx_export`.

Templates: pass `presentation_templates` to `DocPluginManager` to offer branded styling. The exporter applies slide masters, theme colors, fonts.

## html / html_sandbox

A self-contained HTML / CSS / JS artefact. Rendered in a sandboxed iframe on the client.

```json
{
  "title": "Color picker",
  "html": "<input type='color' id='c'>",
  "css":  "body { font-family: sans-serif; }",
  "js":   "document.getElementById('c').oninput = e => document.body.style.background = e.target.value;"
}
```

The frontend renders this inside `<iframe sandbox="allow-scripts">` with inlined vendor libs (Plotly, KaTeX) if the html requests them. Exports as a standalone `.html` file.

## email_draft

A composable email with typed recipients and inline-referenced attachments.

```json
{
  "subject": "Q1 Report",
  "to":     ["ceo@example.com"],
  "cc":     ["board@example.com"],
  "bcc":    [],
  "body_html": "<p>Hi, attached is the Q1 report.</p>",
  "attachments": [
    {"ref": "chart-uuid",    "name": "Q1 Revenue.png"},
    {"ref": "report-uuid",   "name": "Q1 Report.docx"}
  ]
}
```

Attachments reference other documents by id. On send (handled by the host's email provider), each `ref` is resolved — charts rasterise to PNG, tables export as XLSX, text docs as DOCX, etc. — and attached to the outgoing MIME message.

Tools: `email_update_subject`, `email_update_recipients`, `email_update_body`, `email_add_attachment`, `email_send` (host-provided).
