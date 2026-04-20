"""Per-type deep validation for the document system.

Called by DocumentSessionStore on every create/update to catch
structural problems early and return AI-actionable error messages.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Set


@dataclass
class ValidationError:
    """A single validation problem found in document data."""

    code: str
    message: str
    hint: str
    path: str = ""


# ---------------------------------------------------------------------------
# Type-validator registry
# ---------------------------------------------------------------------------

_VALIDATORS: Dict[str, Callable[[Any], List[ValidationError]]] = {}


def validate_document(doc_type: str, data: Any) -> List[ValidationError]:
    """Validate document *data* for the given *doc_type*.

    Returns an empty list when the data is structurally valid.
    Unknown types pass validation (empty list).
    """
    if data is None:
        return [ValidationError(
            code="null_data",
            message="Document data is None",
            hint="Provide a non-null data payload for the document",
        )]
    validator = _VALIDATORS.get(doc_type)
    if validator is None:
        return []
    return validator(data)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _err(code: str, message: str, hint: str, path: str = "") -> ValidationError:
    return ValidationError(code=code, message=message, hint=hint, path=path)


def _is_list(value: Any) -> bool:
    return isinstance(value, list)


def _is_dict(value: Any) -> bool:
    return isinstance(value, dict)


def _is_str(value: Any) -> bool:
    return isinstance(value, str)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)


_EMAIL_RE = re.compile(r"^[^@]+@[^@]+\.[^@]+$")


def _looks_like_email(addr: str) -> bool:
    """Very loose check: has @ and at least one dot after @."""
    return bool(_EMAIL_RE.match(addr))


def _has_html_tags(text: str) -> bool:
    return bool(re.search(r"<[a-zA-Z][^>]*>", text))


# ---------------------------------------------------------------------------
# Table validator
# ---------------------------------------------------------------------------

def _validate_column_defs(columns: List[Any], path: str) -> List[ValidationError]:
    """Validate column definitions (strings or dicts with key/label)."""
    errors: List[ValidationError] = []
    for i, col in enumerate(columns):
        if _is_dict(col):
            if "key" not in col and "label" not in col:
                errors.append(_err(
                    "col_missing_key",
                    f"Column {i} is a dict but has neither 'key' nor 'label'",
                    f"Add a 'key' or 'label' field to column {i}",
                    path=f"{path}/{i}",
                ))
        elif not _is_str(col):
            errors.append(_err(
                "col_invalid_type",
                f"Column {i} must be a string or a dict with 'key'/'label'",
                f"Change column {i} to a string name or a dict with 'key'",
                path=f"{path}/{i}",
            ))
    return errors


def _column_keys(columns: List[Any]) -> List[str]:
    """Extract string keys from column defs for row-width checks."""
    keys: List[str] = []
    for col in columns:
        if _is_dict(col):
            keys.append(col.get("key", col.get("label", "")))
        elif _is_str(col):
            keys.append(col)
        else:
            keys.append("")
    return keys


def _validate_rows(rows: List[Any], columns: List[Any], path: str) -> List[ValidationError]:
    """Validate rows against column definitions."""
    errors: List[ValidationError] = []
    n_cols = len(columns)
    col_keys = set(_column_keys(columns))

    for i, row in enumerate(rows):
        if _is_list(row):
            # Flat array row — length must match columns
            if len(row) != n_cols:
                errors.append(_err(
                    "row_length_mismatch",
                    f"Row {i} has {len(row)} values but table has {n_cols} columns",
                    f"{'Add' if len(row) < n_cols else 'Remove'} "
                    f"{abs(n_cols - len(row))} value(s) in row {i} to match the {n_cols} columns",
                    path=f"{path}/{i}",
                ))
        elif _is_dict(row):
            # Object row — keys must be subset of column keys
            extra = set(row.keys()) - col_keys
            if extra:
                extras_str = ", ".join(sorted(extra))
                errors.append(_err(
                    "row_extra_keys",
                    f"Row {i} has keys not in columns: {extras_str}",
                    f"Remove extra keys ({extras_str}) from row {i} or add them as columns",
                    path=f"{path}/{i}",
                ))
        else:
            errors.append(_err(
                "row_invalid_type",
                f"Row {i} must be an array or an object",
                f"Change row {i} to an array of values or an object with column keys",
                path=f"{path}/{i}",
            ))
    return errors


def _validate_table(data: Any) -> List[ValidationError]:
    """Validate table document data."""
    errors: List[ValidationError] = []

    if not _is_dict(data):
        return [_err("table_not_dict", "Table data must be a dict", "Wrap table data in a JSON object")]

    has_sheets = "sheets" in data
    has_legacy = "columns" in data or "rows" in data

    if not has_sheets and not has_legacy:
        return [_err(
            "table_missing_structure",
            "Table must have 'columns'+'rows' or 'sheets'",
            "Add 'columns' and 'rows' for a single sheet, or 'sheets' for multi-sheet",
        )]

    # --- Multi-sheet ---
    if has_sheets:
        sheets = data["sheets"]
        if not _is_list(sheets):
            return [_err("sheets_not_array", "'sheets' must be an array", "Change 'sheets' to an array of sheet objects")]
        seen_names: Set[str] = set()
        for si, sheet in enumerate(sheets):
            sp = f"sheets/{si}"
            if not _is_dict(sheet):
                errors.append(_err("sheet_not_dict", f"Sheet {si} must be a dict", f"Change sheet {si} to an object", path=sp))
                continue
            # name
            if "name" not in sheet:
                errors.append(_err("sheet_missing_name", f"Sheet {si} is missing 'name'", f"Add a 'name' field to sheet {si}", path=sp))
            else:
                name = sheet["name"]
                if not _is_str(name):
                    errors.append(_err("sheet_name_not_str", f"Sheet {si} name must be a string", f"Change sheet {si} name to a string", path=sp))
                elif name in seen_names:
                    errors.append(_err("sheet_duplicate_name", f"Duplicate sheet name '{name}'", f"Give sheet {si} a unique name", path=sp))
                else:
                    seen_names.add(name)
            # columns
            if "columns" not in sheet:
                errors.append(_err("sheet_missing_columns", f"Sheet {si} is missing 'columns'", f"Add 'columns' to sheet {si}", path=sp))
            else:
                cols = sheet["columns"]
                if not _is_list(cols) or len(cols) == 0:
                    errors.append(_err("sheet_columns_empty", f"Sheet {si} 'columns' must be a non-empty array", f"Add at least one column to sheet {si}", path=f"{sp}/columns"))
                else:
                    errors.extend(_validate_column_defs(cols, path=f"{sp}/columns"))
                    # rows
                    if "rows" in sheet:
                        rows = sheet["rows"]
                        if not _is_list(rows):
                            errors.append(_err("sheet_rows_not_array", f"Sheet {si} 'rows' must be an array", f"Change 'rows' in sheet {si} to an array", path=f"{sp}/rows"))
                        else:
                            errors.extend(_validate_rows(rows, cols, path=f"{sp}/rows"))
            # rows without columns already caught above
        return errors

    # --- Legacy flat format ---
    columns = data.get("columns", [])
    if not _is_list(columns) or len(columns) == 0:
        errors.append(_err("columns_empty", "'columns' must be a non-empty array", "Add at least one column name to 'columns'", path="columns"))
    else:
        errors.extend(_validate_column_defs(columns, path="columns"))

    if "rows" in data:
        rows = data["rows"]
        if not _is_list(rows):
            errors.append(_err("rows_not_array", "'rows' must be an array", "Change 'rows' to an array of row arrays/objects", path="rows"))
        elif len(columns) > 0:
            errors.extend(_validate_rows(rows, columns, path="rows"))

    # frozen_rows
    if "frozen_rows" in data:
        fr = data["frozen_rows"]
        if not _is_int(fr) or fr < 0:
            errors.append(_err(
                "frozen_rows_invalid",
                "'frozen_rows' must be a non-negative integer",
                "Set 'frozen_rows' to 0 or a positive integer",
                path="frozen_rows",
            ))

    # auto_filter
    if "auto_filter" in data:
        af = data["auto_filter"]
        if not _is_bool(af):
            errors.append(_err(
                "auto_filter_invalid",
                "'auto_filter' must be a boolean",
                "Set 'auto_filter' to true or false",
                path="auto_filter",
            ))

    return errors


_VALIDATORS["table"] = _validate_table


# ---------------------------------------------------------------------------
# Presentation validator
# ---------------------------------------------------------------------------

_SLIDE_ELEMENT_TYPES = {"text", "heading", "subtitle", "list", "table", "chart", "image", "bullets"}
_PRESENTATION_FORMATS = {"simple", "markdown", "html"}


def _validate_presentation(data: Any) -> List[ValidationError]:
    """Validate presentation document data."""
    errors: List[ValidationError] = []

    if not _is_dict(data):
        return [_err("pres_not_dict", "Presentation data must be a dict", "Wrap presentation data in a JSON object")]

    if "slides" not in data:
        return [_err("pres_missing_slides", "Presentation must have 'slides' array", "Add a 'slides' array to the presentation")]

    slides = data["slides"]
    if not _is_list(slides):
        return [_err("pres_slides_not_array", "'slides' must be an array", "Change 'slides' to an array of slide objects")]

    # theme
    if "theme" in data:
        theme = data["theme"]
        if not _is_dict(theme):
            errors.append(_err("pres_theme_not_dict", "'theme' must be a dict", "Change 'theme' to an object with string values", path="theme"))
        else:
            for k, v in theme.items():
                if not _is_str(v):
                    errors.append(_err(
                        "pres_theme_value_not_str",
                        f"Theme key '{k}' must have a string value",
                        f"Change theme['{k}'] to a string",
                        path=f"theme/{k}",
                    ))

    # format
    if "format" in data:
        fmt = data["format"]
        if fmt not in _PRESENTATION_FORMATS:
            errors.append(_err(
                "pres_invalid_format",
                f"'format' must be one of: {', '.join(sorted(_PRESENTATION_FORMATS))}",
                f"Change 'format' to one of: {', '.join(sorted(_PRESENTATION_FORMATS))}",
                path="format",
            ))

    seen_ids: Set[str] = set()
    for si, slide in enumerate(slides):
        sp = f"slides/{si}"
        if not _is_dict(slide):
            errors.append(_err("slide_not_dict", f"Slide {si} must be a dict", f"Change slide {si} to an object", path=sp))
            continue

        # id
        if "id" not in slide:
            errors.append(_err("slide_missing_id", f"Slide {si} is missing 'id'", f"Add a unique 'id' field to slide {si}", path=sp))
        else:
            sid = slide["id"]
            sid_str = str(sid)
            if sid_str in seen_ids:
                errors.append(_err("slide_duplicate_id", f"Duplicate slide id '{sid_str}'", f"Give slide {si} a unique id", path=sp))
            else:
                seen_ids.add(sid_str)

        # notes
        if "notes" in slide:
            if not _is_str(slide["notes"]):
                errors.append(_err("slide_notes_not_str", f"Slide {si} 'notes' must be a string", f"Change 'notes' in slide {si} to a string", path=f"{sp}/notes"))

        # elements
        elements = slide.get("elements", [])
        if not _is_list(elements):
            errors.append(_err("slide_elements_not_array", f"Slide {si} 'elements' must be an array", f"Change 'elements' in slide {si} to an array", path=f"{sp}/elements"))
            continue

        has_content = len(elements) > 0 or "title" in slide or "placeholder" in slide
        if not has_content:
            errors.append(_err(
                "slide_empty",
                f"Slide {si} has no elements, title, or placeholder",
                f"Add at least one element or a title/placeholder to slide {si}",
                path=sp,
            ))

        for ei, elem in enumerate(elements):
            ep = f"{sp}/elements/{ei}"
            if not _is_dict(elem):
                errors.append(_err("elem_not_dict", f"Element {ei} in slide {si} must be a dict", f"Change element {ei} to an object", path=ep))
                continue
            if "type" not in elem:
                errors.append(_err("elem_missing_type", f"Element {ei} in slide {si} is missing 'type'", f"Add a 'type' field to element {ei}", path=ep))
            else:
                etype = elem["type"]
                if etype not in _SLIDE_ELEMENT_TYPES:
                    errors.append(_err(
                        "elem_invalid_type",
                        f"Element {ei} in slide {si} has unknown type '{etype}'",
                        f"Change type to one of: {', '.join(sorted(_SLIDE_ELEMENT_TYPES))}",
                        path=ep,
                    ))
                # list elements must have items
                if etype == "list" and "items" not in elem:
                    errors.append(_err(
                        "list_elem_missing_items",
                        f"List element {ei} in slide {si} is missing 'items'",
                        f"Add an 'items' array to list element {ei}",
                        path=ep,
                    ))
                elif etype == "list" and "items" in elem and not _is_list(elem["items"]):
                    errors.append(_err(
                        "list_elem_items_not_array",
                        f"List element {ei} in slide {si} 'items' must be an array",
                        f"Change 'items' to an array in list element {ei}",
                        path=ep,
                    ))

    return errors


_VALIDATORS["presentation"] = _validate_presentation


# ---------------------------------------------------------------------------
# Text document validator
# ---------------------------------------------------------------------------

_SECTION_TYPES = {"heading", "paragraph", "list", "table", "embed", "image"}


def _validate_text_doc(data: Any) -> List[ValidationError]:
    """Validate text document data."""
    errors: List[ValidationError] = []

    if not _is_dict(data):
        return [_err("text_not_dict", "Text document data must be a dict", "Wrap text document data in a JSON object")]

    if "sections" not in data:
        return [_err("text_missing_sections", "Text document must have 'sections' array", "Add a 'sections' array to the document")]

    sections = data["sections"]
    if not _is_list(sections):
        return [_err("text_sections_not_array", "'sections' must be an array", "Change 'sections' to an array of section objects")]

    seen_ids: Set[str] = set()
    for si, section in enumerate(sections):
        sp = f"sections/{si}"
        if not _is_dict(section):
            errors.append(_err("section_not_dict", f"Section {si} must be a dict", f"Change section {si} to an object", path=sp))
            continue

        # id
        if "id" not in section:
            errors.append(_err("section_missing_id", f"Section {si} is missing 'id'", f"Add a unique 'id' field to section {si}", path=sp))
        else:
            sid = str(section["id"])
            if sid in seen_ids:
                errors.append(_err("section_duplicate_id", f"Duplicate section id '{sid}'", f"Give section {si} a unique id", path=sp))
            else:
                seen_ids.add(sid)

        # type
        if "type" not in section:
            errors.append(_err("section_missing_type", f"Section {si} is missing 'type'", f"Add a 'type' field to section {si}", path=sp))
        else:
            stype = section["type"]
            if stype not in _SECTION_TYPES:
                errors.append(_err(
                    "section_invalid_type",
                    f"Section {si} has unknown type '{stype}'",
                    f"Change type to one of: {', '.join(sorted(_SECTION_TYPES))}",
                    path=sp,
                ))

            # embed sections need a ref
            if stype == "embed":
                if "$ref" not in section and "ref" not in section:
                    errors.append(_err(
                        "embed_missing_ref",
                        f"Embed section {si} is missing '$ref' or 'ref'",
                        f"Add a '$ref' or 'ref' field pointing to the embedded document id",
                        path=sp,
                    ))

            # heading level
            if stype == "heading" and "level" in section:
                level = section["level"]
                if not _is_int(level) or level < 1 or level > 6:
                    errors.append(_err(
                        "heading_invalid_level",
                        f"Heading section {si} level must be an integer 1-6, got {level!r}",
                        f"Set 'level' to an integer between 1 and 6",
                        path=f"{sp}/level",
                    ))

            # list sections need items
            if stype == "list":
                if "items" not in section:
                    errors.append(_err(
                        "list_section_missing_items",
                        f"List section {si} is missing 'items'",
                        f"Add an 'items' array to list section {si}",
                        path=sp,
                    ))
                elif not _is_list(section["items"]):
                    errors.append(_err(
                        "list_section_items_not_array",
                        f"List section {si} 'items' must be an array",
                        f"Change 'items' to an array in list section {si}",
                        path=sp,
                    ))

    return errors


_VALIDATORS["text_doc"] = _validate_text_doc


# ---------------------------------------------------------------------------
# Email validator
# ---------------------------------------------------------------------------

def _validate_email(data: Any) -> List[ValidationError]:
    """Validate email draft data."""
    errors: List[ValidationError] = []

    if not _is_dict(data):
        return [_err("email_not_dict", "Email data must be a dict", "Wrap email data in a JSON object")]

    # to
    if "to" not in data:
        errors.append(_err("email_missing_to", "Email must have 'to' field", "Add a 'to' array with at least one recipient", path="to"))
    else:
        to = data["to"]
        if not _is_list(to) or len(to) == 0:
            errors.append(_err("email_to_empty", "'to' must be a non-empty array", "Add at least one recipient to 'to'", path="to"))

    # subject
    if "subject" not in data:
        errors.append(_err("email_missing_subject", "Email must have 'subject' field", "Add a 'subject' string", path="subject"))
    else:
        subj = data["subject"]
        if not _is_str(subj) or len(subj.strip()) == 0:
            errors.append(_err("email_subject_empty", "'subject' must be a non-empty string", "Set 'subject' to a non-empty string", path="subject"))

    # body_html
    if "body_html" not in data:
        errors.append(_err("email_missing_body", "Email must have 'body_html' field", "Add a 'body_html' string with the email body", path="body_html"))
    else:
        body = data["body_html"]
        if not _is_str(body):
            errors.append(_err("email_body_not_str", "'body_html' must be a string", "Change 'body_html' to a string", path="body_html"))
        elif body and not _has_html_tags(body):
            errors.append(_err(
                "email_body_plain_text",
                "'body_html' appears to be plain text without HTML tags",
                "Wrap the body in HTML tags, e.g. <p>Your text here</p>",
                path="body_html",
            ))

    # Validate addresses across to/cc/bcc
    all_addresses: List[str] = []
    for field_name in ("to", "cc", "bcc"):
        if field_name not in data:
            continue
        recipients = data[field_name]
        if not _is_list(recipients):
            if field_name != "to":  # 'to' already checked above
                errors.append(_err(
                    f"email_{field_name}_not_array",
                    f"'{field_name}' must be an array",
                    f"Change '{field_name}' to an array of email addresses",
                    path=field_name,
                ))
            continue
        for ri, addr in enumerate(recipients):
            if not _is_str(addr):
                errors.append(_err(
                    "email_addr_not_str",
                    f"Address {ri} in '{field_name}' must be a string",
                    f"Change address {ri} in '{field_name}' to a string email address",
                    path=f"{field_name}/{ri}",
                ))
            elif not _looks_like_email(addr):
                errors.append(_err(
                    "email_addr_invalid",
                    f"Address '{addr}' in '{field_name}' does not look like a valid email",
                    f"Fix the email address format (expected user@domain.tld)",
                    path=f"{field_name}/{ri}",
                ))
            else:
                all_addresses.append(addr.lower())

    # Duplicate recipients
    seen_addrs: Set[str] = set()
    for addr in all_addresses:
        if addr in seen_addrs:
            errors.append(_err(
                "email_duplicate_recipient",
                f"Duplicate recipient '{addr}' across to/cc/bcc",
                f"Remove the duplicate occurrence of '{addr}'",
            ))
            break  # Report once
        seen_addrs.add(addr)

    # Attachments
    if "attachments" in data:
        attachments = data["attachments"]
        if not _is_list(attachments):
            errors.append(_err("email_attachments_not_array", "'attachments' must be an array", "Change 'attachments' to an array", path="attachments"))
        else:
            for ai, att in enumerate(attachments):
                ap = f"attachments/{ai}"
                if not _is_dict(att):
                    errors.append(_err("email_attachment_not_dict", f"Attachment {ai} must be a dict", f"Change attachment {ai} to an object with 'ref' and 'name'", path=ap))
                    continue
                if "ref" not in att:
                    errors.append(_err("email_attachment_missing_ref", f"Attachment {ai} is missing 'ref'", f"Add a 'ref' field to attachment {ai}", path=ap))
                if "name" not in att:
                    errors.append(_err("email_attachment_missing_name", f"Attachment {ai} is missing 'name'", f"Add a 'name' field to attachment {ai}", path=ap))

    return errors


_VALIDATORS["email_draft"] = _validate_email


# ---------------------------------------------------------------------------
# Plotly validator
# ---------------------------------------------------------------------------

def _validate_plotly(data: Any) -> List[ValidationError]:
    """Validate Plotly chart data."""
    errors: List[ValidationError] = []

    if not _is_dict(data):
        return [_err("plotly_not_dict", "Plotly data must be a dict", "Wrap Plotly data in a JSON object")]

    if "data" not in data:
        return [_err("plotly_missing_data", "Plotly document must have 'data' array", "Add a 'data' array with at least one trace")]

    traces = data["data"]
    if not _is_list(traces):
        return [_err("plotly_data_not_array", "'data' must be an array", "Change 'data' to an array of trace objects")]

    if len(traces) == 0:
        errors.append(_err("plotly_no_traces", "'data' array must have at least one trace", "Add at least one trace to the 'data' array", path="data"))
        return errors

    for ti, trace in enumerate(traces):
        tp = f"data/{ti}"
        if not _is_dict(trace):
            errors.append(_err("trace_not_dict", f"Trace {ti} must be a dict", f"Change trace {ti} to an object", path=tp))
            continue

        if "type" not in trace:
            errors.append(_err("trace_missing_type", f"Trace {ti} is missing 'type'", f"Add a 'type' field (e.g. 'scatter', 'bar') to trace {ti}", path=tp))
        elif not _is_str(trace["type"]):
            errors.append(_err("trace_type_not_str", f"Trace {ti} 'type' must be a string", f"Change trace {ti} 'type' to a string", path=tp))

        # x/y length check
        if "x" in trace and "y" in trace:
            x = trace["x"]
            y = trace["y"]
            if _is_list(x) and _is_list(y) and len(x) != len(y):
                errors.append(_err(
                    "trace_xy_length_mismatch",
                    f"Trace {ti} has {len(x)} x-values but {len(y)} y-values",
                    f"Make x and y arrays the same length in trace {ti}",
                    path=tp,
                ))

        # Empty trace check: only "type" and no data fields
        data_fields = {k for k in trace.keys() if k != "type" and k != "name" and k != "mode"
                       and k != "marker" and k != "line" and k != "opacity"
                       and k != "hoverinfo" and k != "showlegend" and k != "legendgroup"
                       and k != "visible" and k != "uid" and k != "customdata"
                       and k != "meta" and k != "transforms" and k != "textposition"
                       and k != "textfont" and k != "hoverlabel"}
        if len(data_fields) == 0:
            errors.append(_err(
                "trace_empty",
                f"Trace {ti} has no data fields (only styling/metadata)",
                f"Add data fields (x, y, z, values, labels, etc.) to trace {ti}",
                path=tp,
            ))

    # layout
    if "layout" in data:
        if not _is_dict(data["layout"]):
            errors.append(_err("plotly_layout_not_dict", "'layout' must be a dict", "Change 'layout' to an object", path="layout"))

    return errors


_VALIDATORS["plotly"] = _validate_plotly


# ---------------------------------------------------------------------------
# HTML validator
# ---------------------------------------------------------------------------

def _validate_html(data: Any) -> List[ValidationError]:
    """Validate HTML document data."""
    errors: List[ValidationError] = []

    if not _is_dict(data):
        return [_err("html_not_dict", "HTML data must be a dict", "Wrap HTML data in a JSON object")]

    has_html = "html" in data
    has_content = "content" in data

    if not has_html and not has_content:
        errors.append(_err(
            "html_missing_content",
            "HTML document must have 'html' or 'content' field",
            "Add an 'html' field with the HTML markup",
        ))

    if "css" in data and not _is_str(data["css"]):
        errors.append(_err("html_css_not_str", "'css' must be a string", "Change 'css' to a CSS string", path="css"))

    if "js" in data and not _is_str(data["js"]):
        errors.append(_err("html_js_not_str", "'js' must be a string", "Change 'js' to a JavaScript string", path="js"))

    if "title" in data and not _is_str(data["title"]):
        errors.append(_err("html_title_not_str", "'title' must be a string", "Change 'title' to a string", path="title"))

    return errors


_VALIDATORS["html"] = _validate_html


# ---------------------------------------------------------------------------
# LaTeX validator
# ---------------------------------------------------------------------------

def _validate_latex(data: Any) -> List[ValidationError]:
    """Validate LaTeX document data."""
    if not _is_dict(data):
        return [_err("latex_not_dict", "LaTeX data must be a dict", "Wrap LaTeX data in a JSON object")]

    if "formula" not in data:
        return [_err("latex_missing_formula", "LaTeX document must have 'formula' field", "Add a 'formula' string with the LaTeX expression")]

    formula = data["formula"]
    if not _is_str(formula) or len(formula.strip()) == 0:
        return [_err(
            "latex_formula_empty",
            "'formula' must be a non-empty string",
            "Set 'formula' to a non-empty LaTeX expression",
            path="formula",
        )]

    return []


_VALIDATORS["latex"] = _validate_latex
