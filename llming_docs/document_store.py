"""Document model and session-scoped document store.

Supports validation, version history with delta-based undo, and
unified storage for both AI-created and uploaded documents.
"""

import threading
import time
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, Field


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
        """Undo the most recent change to a document. Returns restored Document or None."""
        with self._lock:
            doc = self._docs.get(doc_id)
            if not doc:
                return None

            history = self._histories.get(doc_id)
            if not history:
                return None

            result = history.undo()
            if result is None:
                return None

            restored_data, restored_version = result
            doc.data = restored_data
            doc.version += 1  # undo itself is a new version
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
        """
        with self._lock:
            self._docs.clear()
            self._histories.clear()
            for d in docs_data:
                doc = Document(**d)
                doc.type = self._TYPE_ALIASES.get(doc.type, doc.type)
                self._docs[doc.id] = doc

    def clear(self) -> None:
        """Drop all documents and history."""
        with self._lock:
            self._docs.clear()
            self._histories.clear()
