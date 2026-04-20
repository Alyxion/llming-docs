"""Backwards-compat shim — word_exporter moved to ``llming_docs.text.exporter``."""
from llming_docs.text.exporter import *  # noqa: F401,F403
from llming_docs.text.exporter import export_docx, _strip_html, _add_rich_text  # noqa: F401
