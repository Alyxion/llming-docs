# History & Undo

Every document has an associated `DocumentHistory` that records each edit. Undo rewinds one step in constant amortised time, regardless of how many edits came before.

## Storage format

History is a mixed stream of **snapshots** and **deltas**:

- **Snapshot** — a full copy of `doc.data` at a given version.
- **Delta** — a list of JSON-Pointer-style patch ops between consecutive versions.

```python
@dataclass
class HistoryEntry:
    version: int
    timestamp: float
    is_snapshot: bool
    data: Any  # Full data if snapshot; list of patches if delta
```

Snapshots are taken:

- At the first version (always).
- Every N versions (configurable, default 10).
- Whenever the delta against the previous version would exceed ~60% of the full document size (i.e. when delta compression stops paying off).

This keeps storage small for documents under frequent small edits (a slide deck under iteration) while guaranteeing fast reconstruction — you never replay more than N deltas to rebuild any version.

## Delta operations

```python
{"op": "replace", "path": "/slides/0/title", "old": "Old", "new": "New"}
{"op": "add",     "path": "/slides",         "value": {...}}           # position implied
{"op": "remove",  "path": "/slides/2",       "old": {...}}
```

- Replace and remove carry the `old` value so the patch is reversible — undo flips `new`/`old` and flips `add`/`remove`.
- Paths use leading `/`, slash-separated — the same language `UnifiedDocumentMCP` uses for edits (with the minor difference that `UnifiedDocumentMCP` omits the leading slash for LLM ergonomics).

## Public API

```python
from llming_docs import DocumentHistory, HistoryEntry, compute_delta, apply_delta

# Diff two arbitrary JSON values
patches = compute_delta(old_data, new_data)

# Apply patches forward to reconstruct the new value
reconstructed = apply_delta(old_data, patches)

# Direct access (normally not needed — the store manages history)
history = DocumentHistory(snapshot_interval=10)
history.record(old_data, new_data, version=2)
restored_data, restored_version = history.undo()
```

## Undo via the store

```python
doc = store.undo(doc_id)  # Returns the restored Document (emits doc_updated)
```

- One step at a time — there is currently no multi-step undo.
- Undo itself creates a *new* version (the restored state) — so subsequent edits continue to record deltas normally.
- Redo is not implemented. Users who undo too far must re-prompt the LLM for the change.

## LLM-facing `undo_document` tool

`UnifiedDocumentMCP` exposes `undo_document(document_id)`:

- Returns the restored data as a JSON string.
- Emits `doc_updated` to the client so the sidebar and any inline render refresh.
- Returns a structured error if the document has no history (freshly created docs cannot be undone).

## What is *not* history

- **Create/delete** — only `update()` records history. If the LLM asks to "undo creation", the tool should call `delete_document` instead.
- **Name changes** — changing only `doc.name` without a data change does not record history.
- **`source`/`editable`/`inject_mode`** — metadata fields are not versioned. They're expected to be set at creation and remain stable.

## Storage budget

History lives in memory on the server and is **not** currently synced back to the client IDB. On reconnect the client sends its documents; the server reconstructs a fresh `DocumentHistory` starting from the restored version. Undo works within the current session but does not survive a session disconnect.

This is a deliberate trade-off — full history persistence would require per-delta round trips, which would either bloat IDB storage or gate edits on network RTTs. If future requirements demand persistent history, the format above is designed to be serialisable.
