"""Document model and session-scoped document store.

Supports validation, version history with delta-based undo, and
unified storage for both AI-created and uploaded documents.
"""

import threading
import time
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Legacy-table migration (JSON {sheets: ...} → XLSX {xlsx_b64: ...})
# ---------------------------------------------------------------------------


def _migrate_table_data_if_legacy(data: Any) -> Any:
    """Convert a legacy JSON-shape table payload to ``{xlsx_b64: "..."}``.

    No-op when ``data`` already carries ``xlsx_b64`` or doesn't look like
    a legacy table shape. Imported lazily so the document store doesn't
    take a hard dependency on openpyxl when the host happens to use only
    non-table doc types.
    """
    from llming_docs.sheet.xlsx_migrate import (
        is_legacy_json_table,
        migrate_legacy_json_to_workbook,
    )
    from llming_docs.sheet.xlsx_storage import workbook_to_b64

    if not is_legacy_json_table(data):
        return data
    wb = migrate_legacy_json_to_workbook(data)
    return {"xlsx_b64": workbook_to_b64(wb)}


class Document(BaseModel):
    """A document within a chat conversation."""
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    conversation_id: str = ""
    type: str = ""  # plotly, latex, table, text_doc, presentation, html, email_draft, pdf, docx, xlsx
    name: str = ""
    data: Any = None  # JSON-serializable document data
    version: int = 1
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    # Unified document fields
    source: str = "created"       # "created" | "uploaded" | "nudge"
    editable: bool = True         # False for uploaded docs
    inject_mode: str = "none"     # "none" | "full" | "summary" | "on_demand"


class DocumentSessionStore:
    """Thread-safe in-memory document store scoped to a session.

    Documents live for the duration of the chat session and are
    synced to the frontend via WebSocket for IDB persistence.

    Features:
    - Validation on create/update (returns errors instead of persisting)
    - Version history with delta-based undo
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._docs: Dict[str, Document] = {}
        self._histories: Dict[str, Any] = {}  # doc_id -> DocumentHistory
        self._notify_callback: Optional[Any] = None

    def set_notify_callback(self, callback) -> None:
        """Set a callback(event_type, document) for WebSocket notifications."""
        self._notify_callback = callback

    def _notify(self, event_type: str, doc: Document) -> None:
        if self._notify_callback:
            try:
                self._notify_callback(event_type, doc)
            except Exception:
                pass

    def _get_history(self, doc_id: str):
        """Get or create a DocumentHistory for the given doc."""
        if doc_id not in self._histories:
            from llming_docs.history import DocumentHistory
            self._histories[doc_id] = DocumentHistory()
        return self._histories[doc_id]

    def create(self, type: str, name: str, data: Any,
               id: Optional[str] = None,
               conversation_id: str = "",
               source: str = "created",
               editable: bool = True,
               inject_mode: str = "none",
               skip_validation: bool = False) -> Union["Document", list]:
        """Create a document. Returns Document on success, list[ValidationError] on failure.

        If ``id`` is provided it is used as the document id (e.g. to adopt the
        id from a fenced code block the LLM already emitted). Otherwise a fresh
        id is auto-generated. If the id already exists in the store the call
        is a no-op — the existing document is returned unchanged.
        """
        if id:
            with self._lock:
                existing = self._docs.get(id)
            if existing is not None:
                return existing

        # Normalize table data to the canonical XLSX storage shape. Catches
        # legacy ``{sheets: [...]}`` payloads coming from older clients
        # (e.g. the workspace "+ new doc" button's template) so every
        # ``table`` doc in the store is XLSX-backed regardless of how it
        # was created. New ``{xlsx_b64: ...}`` data is left untouched.
        if type == "table":
            data = _migrate_table_data_if_legacy(data)
            # XLSX bytes are the validation — skip the JSON-shape validator.
            skip_validation = True

        if not skip_validation and data is not None:
            from llming_docs.validators import validate_document
            errors = validate_document(type, data)
            if errors:
                return errors

        doc_kwargs = dict(
            type=type,
            name=name,
            data=data,
            conversation_id=conversation_id,
            source=source,
            editable=editable,
            inject_mode=inject_mode,
        )
        if id:
            doc_kwargs["id"] = id
        doc = Document(**doc_kwargs)
        with self._lock:
            self._docs[doc.id] = doc
        self._notify("doc_created", doc)
        return doc

    def get(self, doc_id: str) -> Optional[Document]:
        with self._lock:
            return self._docs.get(doc_id)

    def list_all(self) -> List[Document]:
        with self._lock:
            return list(self._docs.values())

    def list_by_type(self, doc_type: str) -> List[Document]:
        with self._lock:
            return [d for d in self._docs.values() if d.type == doc_type]

    def list_by_source(self, source: str) -> List[Document]:
        """List documents by source (created, uploaded, nudge)."""
        with self._lock:
            return [d for d in self._docs.values() if d.source == source]

    def update(self, doc_id: str, data: Any = None,
               name: Optional[str] = None,
               skip_validation: bool = False) -> Union[Optional["Document"], list]:
        """Update a document. Returns Document on success, list[ValidationError] on failure, None if not found."""
        with self._lock:
            doc = self._docs.get(doc_id)
            if not doc:
                return None

            new_data = data if data is not None else doc.data
            new_type = doc.type

            # Validate new data
            if not skip_validation and data is not None:
                from llming_docs.validators import validate_document
                errors = validate_document(new_type, new_data)
                if errors:
                    return errors

            # Record history before overwriting
            if data is not None:
                import copy
                old_data = copy.deepcopy(doc.data)
                history = self._get_history(doc_id)
                history.record(old_data, new_data, version=doc.version + 1)

            if data is not None:
                doc.data = data
            if name is not None:
                doc.name = name
            doc.version += 1
            doc.updated_at = time.time()

        self._notify("doc_updated", doc)
        return doc

    def undo(self, doc_id: str) -> Optional[Document]:
        """Undo the most recent change to a document. Returns restored Document or None.

        Pushes the current state onto the history's redo stack so a
        subsequent :meth:`redo` can step forward again.
        """
        with self._lock:
            doc = self._docs.get(doc_id)
            if not doc:
                return None

            history = self._histories.get(doc_id)
            if not history:
                return None

            # Pass the *current* state so redo can return us to it.
            result = history.undo(
                current_data=doc.data, current_version=doc.version,
            )
            if result is None:
                return None

            restored_data, restored_version = result
            doc.data = restored_data
            doc.version += 1  # undo itself is a new version
            doc.updated_at = time.time()

        self._notify("doc_updated", doc)
        return doc

    def redo(self, doc_id: str) -> Optional[Document]:
        """Step forward through the history's redo stack. Returns the
        restored Document or None when there's nothing to redo (no
        previous undo, or a fresh edit cleared the forward branch).

        We treat redo as the symmetric inverse of undo: push the current
        (undone) state back onto the undo stack via
        :meth:`DocumentHistory.record`, then apply the forward state
        retrieved from the redo stack. This means a subsequent undo will
        revert the redo cleanly — without us having to special-case
        anything in :meth:`undo`.
        """
        with self._lock:
            doc = self._docs.get(doc_id)
            if not doc:
                return None
            history = self._histories.get(doc_id)
            if not history:
                return None
            forward = history.redo()
            if forward is None:
                return None
            forward_data, _forward_version = forward

            # Re-push the current state so undo can come back to it.
            # ``record`` would normally clear the redo stack; we save and
            # restore it around the call to preserve any deeper redo
            # entries the user might still want to walk.
            saved_redo = list(history._redo)
            history.record(
                old_data=doc.data,
                new_data=forward_data,
                version=doc.version + 1,
            )
            history._redo = saved_redo

            doc.data = forward_data
            doc.version += 1
            doc.updated_at = time.time()

        self._notify("doc_updated", doc)
        return doc

    def delete(self, doc_id: str) -> bool:
        with self._lock:
            doc = self._docs.pop(doc_id, None)
            self._histories.pop(doc_id, None)
        if doc:
            self._notify("doc_deleted", doc)
            return True
        return False

    # Backward compat: old type names → new
    _TYPE_ALIASES = {"word": "text_doc", "powerpoint": "presentation"}

    def restore_from_list(self, docs_data: List[dict]) -> None:
        """Restore documents from frontend IDB on reconnect.

        Replaces the current set: clears existing docs before loading. This makes
        conversation switches clean — stale docs from the previous conversation
        don't leak into the new one.

        ``table`` docs whose ``data`` is the legacy ``{sheets: [...]}``
        JSON shape are migrated **on the fly** to the canonical XLSX
        (``{xlsx_b64: "..."}``). The migration runs once per legacy doc;
        the next time the doc is saved, the JSON shape is gone forever.
        """
        with self._lock:
            self._docs.clear()
            self._histories.clear()
            for d in docs_data:
                doc = Document(**d)
                doc.type = self._TYPE_ALIASES.get(doc.type, doc.type)
                if doc.type == "table":
                    doc.data = _migrate_table_data_if_legacy(doc.data)
                self._docs[doc.id] = doc

    def clear(self) -> None:
        """Drop all documents and history."""
        with self._lock:
            self._docs.clear()
            self._histories.clear()
