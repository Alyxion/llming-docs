"""Delta-based version history with periodic snapshots for documents.

Provides efficient undo/redo and version reconstruction by storing a mix
of full snapshots and compact JSON-Pointer-style deltas.  Snapshots are
taken at fixed intervals or when the delta would be larger than 60 % of
the full document, keeping storage small while guaranteeing fast
reconstruction.
"""

import copy
import json
import time
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class HistoryEntry:
    """A single version in the history timeline.

    *data* holds either the full document snapshot (when *is_snapshot* is
    ``True``) or a list of JSON-Pointer patch operations (when ``False``).
    """

    version: int
    timestamp: float
    is_snapshot: bool
    data: Any  # Full doc data if snapshot, list of patches if delta


# ---------------------------------------------------------------------------
# Delta computation helpers
# ---------------------------------------------------------------------------

def compute_delta(old: Any, new: Any, path: str = "") -> list[dict]:
    """Compute a reversible delta between *old* and *new* values.

    Returns a list of patch operations using JSON-Pointer-style paths:

    - ``{"op": "replace", "path": "/x/y", "old": …, "new": …}``
    - ``{"op": "add",     "path": "/x/y", "value": …}``
    - ``{"op": "remove",  "path": "/x/y", "old": …}``
    """

    # None vs something ---------------------------------------------------
    if old is None and new is None:
        return []
    if old is None:
        return [{"op": "add", "path": path or "/", "value": new}]
    if new is None:
        return [{"op": "remove", "path": path or "/", "old": old}]

    # Type mismatch -------------------------------------------------------
    if type(old) is not type(new):
        return [{"op": "replace", "path": path or "/", "old": old, "new": new}]

    # Dicts ---------------------------------------------------------------
    if isinstance(old, dict) and isinstance(new, dict):
        patches: list[dict] = []
        all_keys = set(old) | set(new)
        for key in sorted(all_keys):
            child_path = f"{path}/{key}"
            if key not in old:
                patches.append({"op": "add", "path": child_path, "value": new[key]})
            elif key not in new:
                patches.append({"op": "remove", "path": child_path, "old": old[key]})
            else:
                patches.extend(compute_delta(old[key], new[key], child_path))
        return patches

    # Lists ---------------------------------------------------------------
    if isinstance(old, list) and isinstance(new, list):
        return _compute_list_delta(old, new, path)

    # Scalars (str, int, float, bool) -------------------------------------
    if old != new:
        return [{"op": "replace", "path": path or "/", "old": old, "new": new}]

    return []


def _compute_list_delta(old: list, new: list, path: str) -> list[dict]:
    """Compute delta for two lists, matching by ``id`` field when present."""

    # Check whether items carry an "id" field for identity matching.
    old_has_ids = all(isinstance(item, dict) and "id" in item for item in old) if old else False
    new_has_ids = all(isinstance(item, dict) and "id" in item for item in new) if new else False

    if old_has_ids and new_has_ids:
        return _compute_list_delta_by_id(old, new, path)

    return _compute_list_delta_by_index(old, new, path)


def _compute_list_delta_by_id(old: list, new: list, path: str) -> list[dict]:
    """Match list items by their ``id`` field."""

    patches: list[dict] = []
    old_map: dict[str, tuple[int, Any]] = {item["id"]: (i, item) for i, item in enumerate(old)}
    new_map: dict[str, tuple[int, Any]] = {item["id"]: (i, item) for i, item in enumerate(new)}

    # Removed items (in old but not in new)
    for item_id in old_map:
        if item_id not in new_map:
            idx, item = old_map[item_id]
            patches.append({"op": "remove", "path": f"{path}/{idx}", "old": item})

    # Added items (in new but not in old)
    for item_id in new_map:
        if item_id not in old_map:
            idx, item = new_map[item_id]
            patches.append({"op": "add", "path": f"{path}/{idx}", "value": item})

    # Changed items (in both)
    for item_id in old_map:
        if item_id in new_map:
            old_idx, old_item = old_map[item_id]
            _new_idx, new_item = new_map[item_id]
            patches.extend(compute_delta(old_item, new_item, f"{path}/{old_idx}"))

    return patches


def _compute_list_delta_by_index(old: list, new: list, path: str) -> list[dict]:
    """Match list items positionally by index."""

    patches: list[dict] = []
    max_len = max(len(old), len(new))

    for i in range(max_len):
        child_path = f"{path}/{i}"
        if i >= len(old):
            patches.append({"op": "add", "path": child_path, "value": new[i]})
        elif i >= len(new):
            patches.append({"op": "remove", "path": child_path, "old": old[i]})
        else:
            patches.extend(compute_delta(old[i], new[i], child_path))

    return patches


# ---------------------------------------------------------------------------
# Delta application
# ---------------------------------------------------------------------------

def apply_delta(data: Any, delta: list[dict], reverse: bool = False) -> Any:
    """Apply *delta* patches to *data* and return the result.

    If *reverse* is ``True`` the patches are applied backwards (undo
    semantics): ``replace`` uses *old* instead of *new*, ``add`` becomes
    a remove, and ``remove`` becomes an add.

    The input *data* is never mutated — a deep copy is made first.
    """

    result = copy.deepcopy(data)

    for patch in delta:
        op = patch["op"]
        path = patch["path"]
        parts = _parse_path(path)

        if op == "replace":
            value = patch["old"] if reverse else patch["new"]
            _set_at_path(result, parts, value)

        elif op == "add":
            if reverse:
                result = _remove_at_path(result, parts)
            else:
                value = patch["value"]
                result = _insert_at_path(result, parts, value)

        elif op == "remove":
            if reverse:
                value = patch["old"]
                result = _insert_at_path(result, parts, value)
            else:
                result = _remove_at_path(result, parts)

    return result


def _parse_path(path: str) -> list[str]:
    """Split a JSON-Pointer path into segments.

    ``"/slides/0/title"`` → ``["slides", "0", "title"]``
    ``"/"`` → ``[]``
    """
    if path == "/":
        return []
    parts = path.split("/")
    # First element is always empty (leading slash).
    return parts[1:]


def _navigate(data: Any, parts: list[str]) -> tuple[Any, str]:
    """Walk *data* along *parts* and return ``(parent, final_key)``."""

    current = data
    for segment in parts[:-1]:
        if isinstance(current, list):
            current = current[int(segment)]
        else:
            current = current[segment]
    return current, parts[-1]


def _set_at_path(data: Any, parts: list[str], value: Any) -> None:
    """Set the value at the given path in-place."""

    if not parts:
        # Cannot replace root in-place via mutation — caller handles this.
        return
    parent, key = _navigate(data, parts)
    if isinstance(parent, list):
        parent[int(key)] = value
    else:
        parent[key] = value


def _insert_at_path(data: Any, parts: list[str], value: Any) -> Any:
    """Insert *value* at path, returning the (possibly new) root."""

    if not parts:
        return value
    parent, key = _navigate(data, parts)
    if isinstance(parent, list):
        parent.insert(int(key), value)
    else:
        parent[key] = value
    return data


def _remove_at_path(data: Any, parts: list[str]) -> Any:
    """Remove the element at path, returning the (possibly new) root."""

    if not parts:
        return None
    parent, key = _navigate(data, parts)
    if isinstance(parent, list):
        del parent[int(key)]
    else:
        del parent[key]
    return data


# ---------------------------------------------------------------------------
# Size estimation
# ---------------------------------------------------------------------------

def _estimate_size(data: Any) -> int:
    """Estimate the JSON-serialized byte length of *data*."""

    return len(json.dumps(data, separators=(",", ":")))


# ---------------------------------------------------------------------------
# DocumentHistory
# ---------------------------------------------------------------------------

class DocumentHistory:
    """Delta-based version history with periodic snapshots.

    Stores up to :pyattr:`MAX_ENTRIES` history entries.  Every
    :pyattr:`SNAPSHOT_INTERVAL` versions a full snapshot is stored;
    in between, compact JSON-Pointer deltas keep memory usage low.
    If a delta exceeds :pyattr:`DELTA_SIZE_THRESHOLD` of the full
    document size a snapshot is stored instead.
    """

    MAX_ENTRIES: int = 30
    SNAPSHOT_INTERVAL: int = 5
    DELTA_SIZE_THRESHOLD: float = 0.6  # 60 %

    def __init__(self) -> None:
        self._entries: list[HistoryEntry] = []
        # Forward stack — populated by ``undo`` (storing the "current" state
        # we just stepped away from), drained by ``redo``. Cleared whenever
        # a fresh edit lands via ``record`` because the user's new edit
        # invalidates the previous forward branch — same semantics as any
        # text editor's undo/redo.
        self._redo: list[tuple[Any, int]] = []

    # -- Public API --------------------------------------------------------

    def record(self, old_data: Any, new_data: Any, version: int) -> None:
        """Record a version change, storing the *old* state.

        A full snapshot is stored when *version* is ``1``, when
        ``version % SNAPSHOT_INTERVAL == 0``, or when the computed
        delta is larger than :pyattr:`DELTA_SIZE_THRESHOLD` of the
        full document.  Otherwise a compact delta is stored.

        Delta entries store the difference from the *previous* entry's
        stored state to *old_data*, so that versions can be
        reconstructed by chaining forward from the nearest snapshot.
        """

        use_snapshot = version == 1 or version % self.SNAPSHOT_INTERVAL == 0

        if not use_snapshot:
            # Compute delta from the previous entry's state to old_data.
            # This makes deltas chainable from the nearest snapshot.
            prev_state = self._reconstruct_last()
            if prev_state is not None:
                delta = compute_delta(prev_state, old_data)
            else:
                # No previous state to diff against — must snapshot.
                use_snapshot = True

        if not use_snapshot:
            if delta:
                delta_size = _estimate_size(delta)
                full_size = _estimate_size(old_data)
                if full_size > 0 and delta_size > self.DELTA_SIZE_THRESHOLD * full_size:
                    use_snapshot = True
            else:
                # Empty delta means old_data == previous state — still
                # record it so the version number is tracked.
                pass

        if use_snapshot:
            entry = HistoryEntry(
                version=version,
                timestamp=time.time(),
                is_snapshot=True,
                data=copy.deepcopy(old_data),
            )
        else:
            entry = HistoryEntry(
                version=version,
                timestamp=time.time(),
                is_snapshot=False,
                data=delta,
            )

        self._entries.append(entry)
        # A fresh edit always invalidates the forward (redo) branch —
        # there's no longer a coherent "next" state once the user diverges.
        self._redo.clear()
        self._prune()

    def undo(self, current_data: Any = None, current_version: int = 0) -> tuple[Any, int] | None:
        """Pop the most recent entry and return the old state.

        Returns ``(restored_data, version)`` or ``None`` when the
        history is empty.  Because :meth:`record` stores the *old*
        state (the data before the change), undoing returns that state.

        If ``current_data`` is provided, it is pushed onto the redo
        stack so a subsequent :meth:`redo` can step forward to it.
        Callers that don't pass it lose redo capability for that step
        (back-compat for any in-tree caller that doesn't know about redo
        yet).
        """

        if not self._entries:
            return None

        last = self._entries.pop()

        # Stash the current state so redo can return us to it. We store a
        # SNAPSHOT regardless of how the original entry was stored — the
        # redo stack is bounded to ``MAX_ENTRIES`` and snapshots are far
        # simpler to reason about for the forward direction.
        if current_data is not None:
            self._redo.append((copy.deepcopy(current_data), int(current_version)))
            # Bound the redo stack to the same cap as the undo stack.
            while len(self._redo) > self.MAX_ENTRIES:
                self._redo.pop(0)

        # Snapshot entries hold old_data directly
        if last.is_snapshot:
            return copy.deepcopy(last.data), last.version

        # Delta entries: we need to reverse-apply the delta to get old_data.
        # The delta was computed as: diff(previous_reconstructed, old_data)
        # So old_data = apply_delta(previous_reconstructed, delta)
        prev_state = self._reconstruct_last()
        if prev_state is not None:
            restored = apply_delta(prev_state, last.data)
            return restored, last.version

        # No previous state available — cannot undo
        return None

    def redo(self) -> tuple[Any, int] | None:
        """Pop the most recent ``undo`` and return the state we stepped
        away from. Returns ``(restored_data, version)`` or ``None`` when
        the redo stack is empty (e.g. fresh history, or a new edit
        cleared the forward branch).

        Callers must ``record(old_data=..., new_data=restored_data, version=...)``
        themselves to log this redo as a normal edit; ``redo`` does not
        touch ``_entries`` because the entry it would push is an exact
        duplicate of the one ``undo`` just popped.
        """
        if not self._redo:
            return None
        data, version = self._redo.pop()
        return data, version

    def get_version(self, target_version: int) -> Any | None:
        """Reconstruct the document state at *target_version*.

        Returns ``None`` if the version is not present in the history.
        """

        # Check that the target version exists.
        target_entry: HistoryEntry | None = None
        for e in self._entries:
            if e.version == target_version:
                target_entry = e
                break

        if target_entry is None:
            return None

        # Snapshot — return directly.
        if target_entry.is_snapshot:
            return copy.deepcopy(target_entry.data)

        # Delta — find nearest preceding snapshot, apply deltas forward.
        snapshot_data, snapshot_version = self._find_nearest_snapshot(target_version)
        if snapshot_data is None:
            return None

        result = copy.deepcopy(snapshot_data)
        for e in self._entries:
            if e.version > snapshot_version and e.version <= target_version:
                if e.is_snapshot:
                    result = copy.deepcopy(e.data)
                else:
                    result = apply_delta(result, e.data)

        return result

    # -- Properties --------------------------------------------------------

    @property
    def version_count(self) -> int:
        """Number of recorded history entries."""
        return len(self._entries)

    @property
    def versions(self) -> list[int]:
        """List of recorded version numbers in chronological order."""
        return [e.version for e in self._entries]

    # -- Internal ----------------------------------------------------------

    def _reconstruct_last(self) -> Any | None:
        """Reconstruct the state stored by the most recent entry.

        Returns ``None`` when the history is empty.
        """

        if not self._entries:
            return None
        last = self._entries[-1]
        if last.is_snapshot:
            return copy.deepcopy(last.data)
        return self.get_version(last.version)

    def _find_nearest_snapshot(self, before_version: int) -> tuple[Any | None, int]:
        """Find the latest snapshot entry with ``version <= before_version``.

        Returns ``(snapshot_data, snapshot_version)`` or ``(None, -1)``.
        """

        best_data: Any | None = None
        best_version: int = -1

        for e in self._entries:
            if e.is_snapshot and e.version <= before_version and e.version > best_version:
                best_data = e.data
                best_version = e.version

        return best_data, best_version

    def _prune(self) -> None:
        """Drop oldest entries when the history exceeds :pyattr:`MAX_ENTRIES`.

        At least one snapshot is always retained so that delta entries
        remain reconstructable.
        """

        while len(self._entries) > self.MAX_ENTRIES:
            # Find the first snapshot that is NOT the only one.
            snapshot_count = sum(1 for e in self._entries if e.is_snapshot)
            if snapshot_count <= 1:
                # Only one snapshot left — drop the oldest entry regardless
                # (it must be a delta since we keep the snapshot).
                # But if the oldest IS the sole snapshot, we must keep it.
                if self._entries[0].is_snapshot:
                    # Drop the second-oldest instead.
                    del self._entries[1]
                else:
                    del self._entries[0]
            else:
                del self._entries[0]
