"""DocPluginManager — orchestrates document store and per-type MCP servers.

Each doc plugin type self-registers its preamble and MCP server definition
so that the LLM prompt and tooling are automatically derived from whichever
plugins are currently enabled.
"""

import importlib
import logging
from typing import List, Optional

from llming_models.tools.mcp.config import MCPServerConfig
from llming_docs.document_store import DocumentSessionStore
from llming_docs.creator_mcp import DocumentCreatorMCP
from llming_docs.unified_mcp import UnifiedDocumentMCP

logger = logging.getLogger(__name__)

# ── Plugin registry ──────────────────────────────────────────────
# All known doc plugin types.  Order here determines preamble order.
ALL_DOC_PLUGIN_TYPES: list[str] = [
    "plotly", "latex", "table", "text_doc", "presentation", "html", "email_draft",
]

# Backward compat: old type names → new type names
_TYPE_ALIASES: dict[str, str] = {
    "word": "text_doc",
    "powerpoint": "presentation",
}

# Schema one-liner per type — shown in the preamble as guidance for the
# `data` argument to create_document. Tool-only — no fenced blocks anywhere.
_PREAMBLE_LINES: dict[str, str] = {
    "plotly":       "- `plotly` — Plotly.js chart. data = {data: [...], layout: {...}}",
    "latex":        "- `latex` — LaTeX formula. data = {formula: \"...\"}",
    "table":        "- `table` — Data table / spreadsheet. data = {columns: [...], rows: [...]}",
    "text_doc":     "- `text_doc` — Text document (DOCX-like). data = {sections: [{id, type, content, ...}]}",
    "presentation": "- `presentation` — Slide deck (PPTX). data = {title, author, slideNumbers, slides: [{id, title, layout, elements: [...]}]}",
    "html":         "- `html` — Website / web app. data = {html, css, js, title}",
    "email_draft":  "- `email_draft` — Email draft. data = {subject, to: [...], cc: [...], bcc: [...], body_html, attachments: [{ref, name}]}",
}

# Per-type MCP server definitions (types without an entry only have frontend rendering)
_MCP_SERVERS: dict[str, dict] = {
    "plotly": {
        "module": "llming_docs.plotly_mcp",
        "class_name": "PlotlyDocumentMCP",
        "label": "Plotly Charts",
        "description": "Edit and refine Plotly chart documents",
    },
    "table": {
        "module": "llming_docs.table_mcp",
        "class_name": "TableDocumentMCP",
        "label": "Tables",
        "description": "Edit table and spreadsheet documents",
    },
    "text_doc": {
        "module": "llming_docs.text_doc_mcp",
        "class_name": "TextDocMCP",
        "label": "Text Documents",
        "description": "Edit structured text documents",
    },
    "presentation": {
        "module": "llming_docs.presentation_mcp",
        "class_name": "PresentationMCP",
        "label": "Presentations",
        "description": "Edit presentation slide decks",
    },
    "html": {
        "module": "llming_docs.html_mcp",
        "class_name": "HtmlDocumentMCP",
        "label": "Website",
        "description": "Create and edit websites, web apps, and interactive HTML/CSS/JS projects",
    },
    "email_draft": {
        "module": "llming_docs.email_mcp",
        "class_name": "EmailDraftMCP",
        "label": "Email Drafts",
        "description": "Compose and edit email drafts",
    },
}

# Tool-name prefix per doc type (for bulk-toggling when presets change)
TYPE_TOOL_PREFIXES: dict[str, str] = {
    "plotly": "plotly_",
    "table": "table_",
    "text_doc": "text_doc_",
    "presentation": "pptx_",
    "html": "html_",
    "email_draft": "email_",
}


class DocPluginManager:
    """Creates and manages document-related MCP servers for a session.

    Args:
        enabled_types: Which doc plugin types to enable.
            ``None`` → all types (default for random chat).
            ``[]``   → no doc plugins at all.
            ``["plotly", "table"]`` → only those types.
    """

    def __init__(
        self,
        enabled_types: Optional[List[str]] = None,
        presentation_templates: Optional[List] = None,
        requires_providers: Optional[List[str]] = None,
    ) -> None:
        self.store = DocumentSessionStore()
        self._mcp_instances: list = []
        self._enabled_types: list[str] = (
            [_TYPE_ALIASES.get(t, t) for t in enabled_types]
            if enabled_types is not None
            else list(ALL_DOC_PLUGIN_TYPES)
        )
        self._presentation_templates: list = list(presentation_templates or [])
        self._requires_providers: Optional[List[str]] = requires_providers

    # ── Public API ───────────────────────────────────────────────

    @property
    def enabled_types(self) -> list[str]:
        """Currently enabled doc plugin types."""
        return list(self._enabled_types)

    @property
    def presentation_templates(self) -> list:
        """Available presentation templates."""
        return list(self._presentation_templates)

    def set_enabled_types(self, types: Optional[List[str]]) -> None:
        """Update enabled types (e.g. when a preset is applied)."""
        if types is not None:
            self._enabled_types = [_TYPE_ALIASES.get(t, t) for t in types]
        else:
            self._enabled_types = list(ALL_DOC_PLUGIN_TYPES)

    def get_preamble(self) -> str:
        """Build LLM preamble text for currently enabled doc plugin types.

        Tool-only policy: documents are created and edited EXCLUSIVELY via the
        MCP tools (``create_document``, ``update_document``, per-type edit tools).
        Fenced code blocks (``` ``text_doc`` / ``plotly`` / ``table`` / … `` ```) are
        NOT rendered as documents and will appear as plain, ugly JSON code blocks
        to the user. Always use the tools.

        When the session already has documents (created earlier in the same
        conversation), a **Current Documents** inventory is appended so the
        LLM can see their ids and names without having to re-parse every
        earlier tool-call result — this is what prevents the common failure
        mode of calling ``create_document`` again instead of ``update_document``.
        """
        if not self._enabled_types:
            return ""

        lines = [
            "\n\n## Documents — Tool-Only Policy",
            "Documents (charts, tables, text documents, presentations, HTML, email drafts) "
            "are created and edited **EXCLUSIVELY** via MCP tools. "
            "Fenced code blocks with doc-type languages are **forbidden** — they are not "
            "rendered as documents.",
            "",
            "**NEVER** write `" + "```" + "text_doc`, `" + "```" + "plotly`, `" + "```" + "table`, "
            "`" + "```" + "presentation`, `" + "```" + "html`, `" + "```" + "latex`, or "
            "`" + "```" + "email_draft` blocks in your response. "
            "They will appear to the user as raw JSON and look broken.",
            "",
            "**ALWAYS** use:",
            "- `create_document(type, name, data)` to create a new document.",
            "- `update_document(document_id, operations)` to edit an existing document.",
            "- `read_document(document_id, path?)` to inspect an existing document before editing.",
            "- `undo_document(document_id)` to revert the last change.",
            "- Per-type tools (`text_doc_add_section`, `plotly_add_trace`, `table_add_row`, …) "
            "for type-specific operations.",
            "",
            "## Supported Document Types",
            "Pass one of these as the `type` argument to `create_document` "
            "(the shape shown is the `data` JSON payload):",
        ]
        for t in self._enabled_types:
            if t in _PREAMBLE_LINES:
                lines.append(_PREAMBLE_LINES[t])
        lines.append(
            "\n### Type Selection — Strict Mapping\n"
            "Pick the document type from the user's request, not from your own preference:\n"
            "- **Text, poem, letter, essay, article, notes, memo, minutes, story** → "
            "`text_doc`. Always. A poem is a text document, not an email draft or HTML.\n"
            "- **Table, list of rows, comparison, inventory** → `table`.\n"
            "- **Sheet, spreadsheet, Excel, XLSX, workbook** → `table` (use the multi-sheet "
            "`{sheets: [...]}` shape when the user explicitly wants multiple tabs, otherwise "
            "flat `{columns, rows}`).\n"
            "- **Slide deck, presentation, PowerPoint** → `presentation`.\n"
            "- **Chart, plot, graph** → `plotly`.\n"
            "- **Website, web page, interactive demo** → `html`.\n"
            "- **Email, draft reply** → `email_draft`.\n"
            "Never substitute a type because it seems faster or easier — the user's wording "
            "determines the type."
        )
        lines.append(
            "\n### Operating On an Existing Document\n"
            "When the user asks you to **act on** an attached or uploaded document — "
            "translate it, answer its questions, summarize it, rewrite it, fill it in, "
            "reformat it, extract parts of it — always produce the result as a **new "
            "document of the matching type**. Do not dump the result as chat text.\n"
            "- PDF, DOCX, DOC, TXT, RTF, Markdown source → create a `text_doc`.\n"
            "- XLSX, XLS, CSV, TSV → create a `table` (use `{sheets: [...]}` if the "
            "source had multiple sheets and the user wants to preserve them).\n"
            "- PPTX → create a `presentation`.\n"
            "- HTML page / web form → create an `html` document.\n"
            "- Email (`.eml`, forwarded message) → create an `email_draft` for the reply, "
            "or a `text_doc` for a non-reply output like a summary.\n"
            "The new document's `name` should reflect the operation (e.g. "
            "*\"Contract — English translation\"*, *\"Survey — filled in\"*, "
            "*\"Report Q1 — summary\"*) so the user can tell source and result apart."
        )
        lines.append(
            "\n### Data Reuse\n"
            "When the user asks to transform data you already have ('put this in a table', "
            "'show as chart'), reuse the data from previous tool results — do NOT re-query "
            "databases for data already present in the conversation."
        )
        lines.append(
            "\n### Document Identity & Updates\n"
            "Every document has an `id` generated by `create_document` and returned in the "
            "tool result. To modify a document, pass that id to `update_document` / per-type "
            "edit tools — never re-issue `create_document` for a document that already exists.\n"
            "Always pass a short, descriptive `name` when creating (e.g. `\"Q1 Revenue Chart\"`, "
            "`\"Sales by Region Table\"`, `\"Project Kickoff Deck\"`). The name appears in the "
            "sidebar and as the default export filename."
        )
        lines.append(
            "\n### Cross-Document References\n"
            "Reference any earlier document via `{\"$ref\": \"<id>\"}` in the JSON `data` "
            "payload of a later document. The referenced data merges as a base; explicit "
            "properties in the referencing object override.\n"
            "Example: a Plotly chart (id `chart-abc`) can be embedded in a presentation slide "
            "element as `{\"type\": \"chart\", \"$ref\": \"chart-abc\"}`.\n"
            "Only forward references work — reference documents that already exist in the "
            "conversation. No circular references."
        )
        lines.append(
            "\n### Embedding Documents in Text Documents\n"
            "When the user asks to include/embed a chart, table, or other document in a text "
            "document (Word/DOCX), use an `embed` section that references the target by id. "
            "**Do not fetch** the data via `read_document` or `plotly_get_data` "
            "and paste it in — **never copy** data when an embed reference works.\n"
            "\nUse `text_doc_add_section(document_id=<word-doc-id>, type=\"embed\", "
            "ref=\"<source-doc-id>\")`.\n"
            "\nOn export, embeds resolve automatically:\n"
            "- Charts/plots → PNG image.\n"
            "- Tables → native Word table.\n"
            "- Text documents → inlined sections."
        )
        lines.append(
            "\n### Editing Documents (update_document)\n"
            "`update_document(document_id, operations)` applies surgical edits without "
            "re-creating the document. Pass MULTIPLE operations in one call — they are "
            "applied atomically (all-or-nothing). Prefer one call with many operations "
            "over multiple calls: it is faster, creates a single undo step, and uses "
            "less context.\n"
            "\nPath language — slash-separated, resolves against the document's data:\n"
            "- `slides/s1/title` — slide with id 's1', field 'title'.\n"
            "- `slides/0/elements/2/content` — first slide, third element, content.\n"
            "- `sheets/Q1/rows/3/revenue` — sheet named 'Q1', row 3, column 'revenue'.\n"
            "- `sections/abc123/content` — section with id 'abc123'.\n"
            "- `to`, `subject`, `body_html` — top-level email fields.\n"
            "- `data/0/x` — first Plotly trace, x values.\n"
            "\nOperations:\n"
            "- `set` — replace value: `{op: 'set', path: 'slides/s1/title', value: 'New Title'}`.\n"
            "- `add` — insert: `{op: 'add', path: 'slides', value: {id: 's3', ...}, position: 2}`.\n"
            "- `remove` — delete: `{op: 'remove', path: 'slides/s2'}`.\n"
            "- `move` — reorder: `{op: 'move', path: 'slides/s1', position: 0}`.\n"
            "\nUse `read_document` to inspect before editing. Use `undo_document` to revert. "
            "**Always prefer `update_document` over re-creating** — it's faster, preserves "
            "history, and keeps the existing document id stable."
            "\n\n**Title vs filename — do not confuse them.** The `name` argument to "
            "`create_document` / `update_document` is the **filename** shown in the sidebar "
            "and used on export (e.g. `Report.docx`). The in-document title (a heading "
            "section, a slide title, a table caption, the email subject) lives inside "
            "`data`. When the user says *'change the title'*, edit the title inside the "
            "content — not the filename. Only change `name` when the user explicitly says "
            "*'rename the document'*, *'change the filename'*, or similar."
        )
        if "plotly" in self._enabled_types:
            lines.append(
                "For charts: use Plotly.js spec with 'type' in each trace "
                "(e.g. 'pie', 'bar', 'scatter')."
            )
        if "presentation" in self._enabled_types:
            # Check if any template has layouts (template-native mode)
            _templates_with_layouts = [
                t for t in self._presentation_templates
                if hasattr(t, 'layouts') and t.layouts
            ]
            if _templates_with_layouts:
                # Template-native preamble — the LLM should use layout names and placeholders
                lines.append(
                    "\n### Presentations\n"
                    "When creating presentations:\n"
                    "1. **Create data documents first** — call `create_document(type=\"table\", ...)` "
                    "and `create_document(type=\"plotly\", ...)` BEFORE the presentation. Note the "
                    "ids returned in the tool results; you will reference them from slides.\n"
                    "2. **Reference data via `$ref`** — in placeholder values use "
                    "`{\"type\": \"chart\", \"$ref\": \"<chart-doc-id>\"}` or "
                    "`{\"type\": \"table\", \"$ref\": \"<table-doc-id>\"}` to embed data.\n"
                    "3. **Keep text concise** — use bullet points, not paragraphs, to avoid overflow.\n"
                    "4. The presentation supports PPTX export and fullscreen viewing."
                )
                for tpl in _templates_with_layouts:
                    tpl_name = tpl.name if hasattr(tpl, 'name') else str(tpl)
                    tpl_label = tpl.label if hasattr(tpl, 'label') else tpl_name
                    lines.append(f"\n### Template: \"{tpl_name}\" ({tpl_label})")
                    lines.append(
                        f'Set `"template": "{tpl_name}"` at the top level when the user '
                        "explicitly requests this brand/template style. "
                        "Without an explicit request, use the default styling (no template field).\n"
                        "When using this template, slides use `layout` + `placeholders` instead of `elements`.\n"
                        "Available layouts:"
                    )
                    for layout in tpl.layouts:
                        ph_list = ", ".join(
                            f'`{ph.name}` ({"/".join(ph.accepts)})'
                            for ph in layout.placeholders
                        )
                        flags = ""
                        if layout.is_title:
                            flags = " *(use for first slide)*"
                        elif layout.is_end:
                            flags = " *(use for last slide)*"
                        lines.append(f'- **"{layout.name}"** ({layout.label}){flags}: {ph_list}')
                    lines.append(
                        '\nUse **"text"** as the default layout for text/list slides and '
                        '**"chart"** as the default for chart/data slides. '
                        'Only use specialized layouts (two_columns, text_half, picture) when '
                        'the content specifically calls for them.'
                    )
                    lines.append(
                        "\nPlaceholder values: a string for text, or an object for rich content:\n"
                        '- List: `{"type": "list", "items": ["Item 1", "Item 2"]}`\n'
                        '- Table: `{"type": "table", "headers": [...], "rows": [[...]]}`\n'
                        '- Chart: `{"type": "chart", "data": [...], "layout": {...}}` (Plotly spec, or `{"$ref": "id"}`)\n'
                        '- Image: `{"type": "image", "src": "url_or_data_uri"}`\n'
                        "\nExample slide:\n"
                        "```json\n"
                        '{"layout": "text", "placeholders": {"title": "Revenue", '
                        '"body": "Q1 2026 Results", '
                        '"content": {"type": "list", "items": ["Up 15%", "42 new customers"]}}}\n'
                        "```"
                    )

                # Also mention non-template format for completeness
                tpl_names_list = ", ".join(
                    f'"{t.name}"' for t in _templates_with_layouts
                )
                lines.append(
                    "\n### Default Presentations (no template)\n"
                    f"When NOT using a template ({tpl_names_list}), use the abstract `elements` format:\n"
                    "- Spec-level fields: `\"title\"`, `\"author\"`, `\"slideNumbers\": true`\n"
                    "- Slide fields: `\"title\"`, `\"layout\"` (\"title\"/\"end\"), `\"elements\"` array\n"
                    "- Element types: text, heading, list (items:[]), table (headers:[], rows:[[]]), "
                    "chart (Plotly spec), image (src, alt), subtitle (for title slides)."
                )
            else:
                # No template layouts — use the existing generic preamble
                lines.append(
                    "\n### Presentation Best Practices\n"
                    "When creating presentations:\n"
                    "1. **Create data documents first** — call `create_document(type=\"table\", ...)` "
                    "and `create_document(type=\"plotly\", ...)` BEFORE the presentation. Use the "
                    "returned ids in slide elements.\n"
                    "2. **Reference data via `$ref`** — in slide elements use "
                    "`{\"type\": \"chart\", \"$ref\": \"<chart-doc-id>\"}` or "
                    "`{\"type\": \"table\", \"$ref\": \"<table-doc-id>\"}` to embed data.\n"
                    "3. **Title slide** — set `\"layout\": \"title\"` on the first slide. "
                    "It renders with centered title, accent bar, and author line.\n"
                    "4. **Spec-level fields** — set `\"title\"`, `\"author\"`, "
                    "`\"slideNumbers\": true` at the top level of the spec.\n"
                    "5. **Keep text concise** — use bullet points, not paragraphs, to avoid overflow.\n"
                    "6. Element types: text, heading, list (items:[]), table (headers:[], rows:[[]]), "
                    "chart (Plotly spec), image (src, alt), subtitle (for title slides).\n"
                    "7. The presentation supports PPTX export and fullscreen viewing."
                )
                if self._presentation_templates:
                    tpl_names = ", ".join(
                        f'"{t.name}" ({t.label})' if hasattr(t, 'name') else str(t)
                        for t in self._presentation_templates
                    )
                    lines.append(
                        "\n### Presentation Templates\n"
                        f"Available templates: {tpl_names}.\n"
                        'Add `"template": "template_name"` to the top-level presentation spec ONLY '
                        "when the user explicitly requests a specific brand or template style.\n"
                        "Without an explicit request, use the default styling."
                    )
        if "email_draft" in self._enabled_types:
            lines.append(
                "\n### Email Drafts\n"
                "When composing emails:\n"
                "1. Call `create_document(type=\"email_draft\", name=\"<subject or summary>\", "
                "data={subject, to: [...], cc: [...], body_html, attachments: [{ref, name}]})`.\n"
                "2. Write `body_html` as clean, professional HTML suitable for email clients. "
                "Use inline styles only (no `<style>` blocks). No JavaScript.\n"
                "3. To attach files from the chat, add `{\"ref\": \"filename.pdf\", \"name\": \"Report\"}` "
                "to the `attachments` array. You can reference chat attachments by filename "
                "or documents created in the chat by their document id.\n"
                "4. The user will see a visual email preview with Draft and Send buttons — "
                "you do NOT need to send the email yourself."
            )

        # Current-documents inventory — listed last so it's closest to the
        # user's next message in context. Without this the LLM loses track
        # of existing doc ids across turns and defaults to create_document.
        docs = self.store.list_all()
        if docs:
            lines.append("\n### Current Documents (update, don't re-create)")
            lines.append(
                "The following documents already exist in this conversation. "
                "When the user asks to edit/extend/modify any of them, call "
                "`update_document(document_id=<id>, operations=[...])` (or a "
                "per-type tool like `text_doc_add_section`). **Do NOT** call "
                "`create_document` again — that would duplicate the document."
            )
            for d in docs:
                lines.append(
                    f"- `id={d.id}`  type=`{d.type}`  v{d.version}  name={d.name!r}"
                )
        return "\n".join(lines) + "\n"

    def get_mcp_configs(self) -> List[MCPServerConfig]:
        """Create MCP server instances and return their configs.

        Only creates MCPs for enabled types.  Call once per session, then
        merge the returned configs with the user's existing mcp_servers list.
        """
        if not self._enabled_types:
            return []

        configs: list[MCPServerConfig] = []

        # Creator MCP — present when any type is enabled
        creator = DocumentCreatorMCP(self.store)
        self._mcp_instances.append(creator)
        configs.append(MCPServerConfig(
            server_instance=creator,
            label="Documents",
            description="Create and manage rich documents (charts, tables, spreadsheets, etc.)",
            category="Documents",
            enabled_by_default=True,
            requires_providers=self._requires_providers,
        ))

        # Unified document editor — update, read, undo across all types
        unified = UnifiedDocumentMCP(self.store)
        self._mcp_instances.append(unified)
        configs.append(MCPServerConfig(
            server_instance=unified,
            label="Document Editor",
            description="Edit, read sections, search, and undo changes in any document",
            category="Documents",
            enabled_by_default=False,
            requires_providers=self._requires_providers,
        ))

        # Per-type MCP servers (legacy — to be phased out)
        for doc_type in self._enabled_types:
            spec = _MCP_SERVERS.get(doc_type)
            if not spec:
                continue  # e.g. "latex" has no MCP, only frontend rendering
            try:
                mod = importlib.import_module(spec["module"])
                cls = getattr(mod, spec["class_name"])
                instance = cls(self.store)
                self._mcp_instances.append(instance)
                configs.append(MCPServerConfig(
                    server_instance=instance,
                    label=spec["label"],
                    description=spec["description"],
                    category="Documents",
                    enabled_by_default=False,
                    requires_providers=self._requires_providers,
                ))
            except (ImportError, AttributeError) as e:
                logger.warning("[DOC_PLUGINS] Could not load %s MCP: %s", doc_type, e)

        return configs

    async def cleanup(self) -> None:
        """Clean up MCP instances."""
        for mcp in self._mcp_instances:
            if hasattr(mcp, "close"):
                try:
                    await mcp.close()
                except Exception:
                    pass
        self._mcp_instances.clear()
