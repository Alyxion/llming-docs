"""Client-side frontend assets for the document plugin system.

This package owns **all** format-specific client code for the llming-docs
document types: plugin renderers (JS), stylesheets (CSS), icon mappings, and
the list of reserved fenced-block languages. Host chat frameworks (e.g.
``llming-lodge``) dock into this package by:

1. Mounting :func:`get_static_dir` at a URL (typically ``/doc-static/``).
2. Reading :func:`get_manifest` to discover which plugin scripts + stylesheets
   to inject into the chat HTML page.
3. Importing :data:`FORBIDDEN_FENCED_DOC_LANGS` for server-side policy
   enforcement (stripping fenced doc blocks from LLM responses).
4. Importing :data:`DOC_ICONS` for sidebar / tab icons.

Hosts must not hard-code any of the above themselves — all format knowledge
lives here, and new document types are added by extending :data:`MANIFEST`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


# ── Format metadata (authoritative source) ────────────────────────────────

@dataclass(frozen=True)
class DocTypeFrontend:
    """Client-side rendering metadata for a single document type."""

    doc_type: str
    """Canonical type id — e.g. ``"plotly"``. Matches ``Document.type``."""

    label: str
    """Human-readable label shown in MCP tool groups, sidebar, etc."""

    icon: str
    """Material Icons glyph name (used by sidebar / tabs)."""

    plugin_js: Optional[str] = None
    """Filename of the plugin JS, relative to ``frontend/static/plugins/``.

    ``None`` means the plugin is still part of the host's built-in bundle
    and has not yet been extracted into llming-docs. This is a migration
    waypoint — every type should eventually own its own JS file here."""

    plugin_css: Optional[str] = None
    """Filename of plugin-specific CSS, relative to ``frontend/static/css/``.

    Same migration-waypoint semantics as :attr:`plugin_js`."""

    vendor_libs: List[str] = field(default_factory=list)
    """Rich-MCP vendor lib names this type needs (``"plotly"``, ``"katex_js"``, …).
    Passed to the sandbox iframe for rich_mcp renders, ignored otherwise."""

    aliases: List[str] = field(default_factory=list)
    """Legacy type names that should resolve to this type — e.g. ``"word"``
    for ``"text_doc"``. Also forbidden as fenced-block languages."""


# ── Canonical manifest ────────────────────────────────────────────────────
#
# Adding a new document type is purely additive: append a new entry here,
# drop the matching JS/CSS into ``frontend/static/``, and implement the
# Python side (validator, exporter, MCPs) elsewhere in llming_docs. Host
# chat frameworks re-read the manifest at startup — no host code changes.

MANIFEST: List[DocTypeFrontend] = [
    DocTypeFrontend(
        doc_type="plotly",
        label="Plotly Chart",
        icon="bar_chart",
        # plugin_js="plotly.js",  # pending migration — see frontend/static/README.md
        # plugin_css="plotly.css",
        vendor_libs=["plotly"],
    ),
    DocTypeFrontend(
        doc_type="latex",
        label="LaTeX Formula",
        icon="functions",
        vendor_libs=["katex_js", "katex_css"],
    ),
    DocTypeFrontend(
        doc_type="table",
        label="Table",
        icon="table_chart",
    ),
    DocTypeFrontend(
        doc_type="text_doc",
        label="Text Document",
        icon="description",
        aliases=["word"],
    ),
    DocTypeFrontend(
        doc_type="presentation",
        label="Presentation",
        icon="slideshow",
        aliases=["powerpoint", "pptx"],
    ),
    DocTypeFrontend(
        doc_type="html",
        label="HTML Sandbox",
        icon="code",
        aliases=["html_sandbox"],
    ),
    DocTypeFrontend(
        doc_type="email_draft",
        label="Email Draft",
        icon="mail",
    ),
]


# ── Derived public API ────────────────────────────────────────────────────

def get_manifest() -> List[DocTypeFrontend]:
    """Return the full frontend manifest (read-only — mutate at your peril)."""
    return list(MANIFEST)


def get_static_dir() -> Path:
    """Return the filesystem directory the host should mount as static assets.

    Files under this directory are expected to be served unchanged at whatever
    URL prefix the host chooses (``/doc-static/`` by convention). Subdirs:

    - ``plugins/`` — one JS file per document type.
    - ``css/`` — per-type CSS (optional).
    - ``vendor/`` — third-party libs that live with llming-docs (not host).
    """
    return Path(__file__).parent / "static"


#: Fenced-block language identifiers that the server strips from assistant
#: text under the tool-only policy. Derived from the manifest so adding a new
#: type automatically extends the policy — host code should import this and
#: never hard-code the list.
FORBIDDEN_FENCED_DOC_LANGS: tuple[str, ...] = tuple(
    name
    for entry in MANIFEST
    for name in (entry.doc_type, *entry.aliases)
)


#: Material-icon map keyed by document type (including aliases). Used by the
#: host's sidebar / tab strip. Host code should import this rather than
#: maintain its own copy.
DOC_ICONS: dict[str, str] = {
    name: entry.icon
    for entry in MANIFEST
    for name in (entry.doc_type, *entry.aliases)
}


def get_mcp_group_labels() -> dict[str, str]:
    """Return ``{doc_type → MCP group label}`` for every type that has a
    per-type MCP server, including aliases. The host uses this to drive
    auto-enable of per-type edit tools without hard-coding type → label
    pairs itself."""
    from llming_docs.manager import _MCP_SERVERS
    out: dict[str, str] = {}
    for entry in MANIFEST:
        spec = _MCP_SERVERS.get(entry.doc_type)
        if not spec:
            continue
        label = spec["label"]
        out[entry.doc_type] = label
        for alias in entry.aliases:
            out[alias] = label
    return out


__all__ = [
    "DocTypeFrontend",
    "MANIFEST",
    "get_manifest",
    "get_static_dir",
    "get_mcp_group_labels",
    "FORBIDDEN_FENCED_DOC_LANGS",
    "DOC_ICONS",
]
