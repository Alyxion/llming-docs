"""Backwards-compat shim — html_exporter moved to ``llming_docs.web.exporter``."""
from llming_docs.web.exporter import *  # noqa: F401,F403
from llming_docs.web.exporter import export_html, _escape_html  # noqa: F401
