# llming-docs

Structured documents for LLM chat: Plotly charts, tables, text documents, presentations, HTML sandboxes, LaTeX formulas, and email drafts — with validation, delta-based undo, cross-document embedding, and multi-format export (DOCX, PPTX, XLSX, CSV, HTML).

`llming-docs` is the canonical home for document creation and editing logic. Chat frontends dock into it; no chat-framework dependency.

## Documentation

Full docs live in [`docs/`](docs/index.md) and render via `mkdocs serve`:

- [Home](docs/index.md)
- [Principles](docs/principles.md)
- [Documents vs `__rich_mcp__` envelopes](docs/docs-vs-rich-mcp.md)
- [Document types](docs/types.md)
- Concepts — [validation](docs/concepts/validation.md), [history & undo](docs/concepts/history-undo.md), [embedding](docs/concepts/embedding.md), [MCP servers](docs/concepts/mcp-servers.md)
- Integration — [docking into a chat frontend](docs/integration/docking.md), [extending](docs/integration/extending.md)
- API — [stores & manager](docs/api/stores.md), [render & embed](docs/api/rendering.md)

## Quick look

```python
from llming_docs import DocPluginManager

mgr = DocPluginManager(enabled_types=["plotly", "table", "text_doc"])
doc = mgr.store.create(
    type="table", name="Q1 Revenue",
    data={"columns": [{"name": "Region"}, {"name": "USD"}],
          "rows": [["EU", 420_000], ["US", 310_000]]},
)
```
