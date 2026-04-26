"""Socket-aware transport layer for the document editor.

The host (lodge, Quasar, …) owns the WebSocket and the user-session
identity. This module owns everything to do with documents — it
processes ``client_doc_*`` messages and produces document events to
send back over the wire.

Isolation contract (CRITICAL — read before changing this file)
==============================================================
Doc data MUST NEVER leak between user sessions. This module is
**stateless** with respect to sessions: it never looks up "current
session", never holds a registry of stores, never reaches into a
caller-owned context. Every operation runs on the ``store`` the
caller passed in, and every outgoing message goes through the
``send`` callback the caller passed in.

The caller is responsible for:

  1. Maintaining one :class:`DocumentSessionStore` per user session.
  2. Passing the correct store + send for each incoming WS message,
     based on the WS connection it arrived on.
  3. Never sharing stores across sessions.

If the caller does that correctly, this module cannot leak data.
There is no shared state, no globals, no caches keyed by anything
other than the store that was passed in.

Adding global state, module-level caches, or a "lookup store by id"
function would break this guarantee. Don't.
"""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from llming_docs.client_payload import client_doc_payload
from llming_docs.document_store import DocumentSessionStore
from llming_docs.ops_dispatcher import (
    apply_operations_to_data,
    empty_data_for,
)


SendFn = Callable[[dict], Awaitable[None]]


# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------


async def handle_client_doc_message(
    store: DocumentSessionStore,
    msg: dict,
    send: SendFn,
) -> bool:
    """Process a ``client_doc_*`` WS message against ``store``.

    Returns True when ``msg`` was a doc-editor message (regardless of
    whether the operation succeeded or returned an error to the
    client), False when the message type is unknown to this dispatcher
    so the caller can route it elsewhere.

    The caller MUST pass the per-session store and the per-WS send
    callback. See the module docstring's isolation contract.
    """
    msg_type = msg.get("type") or ""
    if not msg_type.startswith("client_doc_"):
        return False

    handler = _HANDLERS.get(msg_type)
    if handler is None:
        # Recognized prefix but unknown action — claim it (so lodge
        # doesn't log "Unknown message type") and return a structured
        # error so a stale frontend gets a useful message.
        await send({
            "type": "client_doc_error",
            "request_id": msg.get("request_id"),
            "errors": [{
                "code": "unknown_action",
                "message": f"unknown doc action '{msg_type}'",
                "hint": None,
                "path": None,
            }],
        })
        return True

    await handler(store, msg, send)
    return True


# ---------------------------------------------------------------------------
# Per-action handlers
# ---------------------------------------------------------------------------


async def _handle_create(store: DocumentSessionStore, msg: dict, send: SendFn) -> None:
    doc_type = msg.get("doc_type") or msg.get("type")
    name = msg.get("name") or "Untitled"
    operations = msg.get("operations") or []
    legacy_data = msg.get("data")

    if not doc_type:
        await _send_error(send, msg, "missing_type",
                          "client_doc_create requires 'doc_type'")
        return

    # Three intake paths converge to the same canonical storage:
    #   * ``operations`` (preferred) — empty doc + ops via the
    #     type-aware dispatcher (table → openpyxl, others → JSON ops).
    #   * ``data`` (legacy templates from the workspace "+ new doc"
    #     button) — passed straight to ``store.create`` which already
    #     migrates legacy table JSON to XLSX inline.
    #   * Neither — make a valid blank doc using the type's empty
    #     template so validators don't reject the create.
    if operations:
        initial = empty_data_for(doc_type)
        final_data, op_error = apply_operations_to_data(
            doc_type, initial, operations,
        )
        if op_error is not None:
            await _send_op_error(send, msg, op_error)
            return
        result = store.create(
            type=doc_type, name=name, data=final_data,
            skip_validation=(doc_type == "table"),
        )
    elif legacy_data is not None:
        result = store.create(
            type=doc_type, name=name, data=legacy_data,
        )
    else:
        result = store.create(
            type=doc_type, name=name, data=empty_data_for(doc_type),
            skip_validation=(doc_type == "table"),
        )
    if isinstance(result, list):
        await _send_validation_errors(send, msg, result)


async def _handle_update(store: DocumentSessionStore, msg: dict, send: SendFn) -> None:
    doc_id = msg.get("document_id")
    operations = msg.get("operations") or []
    new_name = msg.get("name")
    if not doc_id:
        await _send_error(send, msg, "missing_document_id",
                          "client_doc_update requires 'document_id'")
        return
    doc = store.get(doc_id)
    if doc is None:
        await _send_error(send, msg, "document_not_found",
                          f"No document with id '{doc_id}'")
        return

    working, op_error = apply_operations_to_data(doc.type, doc.data, operations)
    if op_error is not None:
        await _send_op_error(send, msg, op_error)
        return

    update_kwargs: dict[str, Any] = {"skip_validation": (doc.type == "table")}
    if operations:
        update_kwargs["data"] = working
    if new_name is not None:
        update_kwargs["name"] = new_name
    result = store.update(doc_id, **update_kwargs)
    if isinstance(result, list):
        await _send_validation_errors(send, msg, result)


async def _handle_undo(store: DocumentSessionStore, msg: dict, send: SendFn) -> None:
    doc_id = msg.get("document_id")
    if not doc_id:
        return
    if store.undo(doc_id) is None:
        await _send_error(send, msg, "no_history",
                          "Nothing to undo on this document.")


async def _handle_redo(store: DocumentSessionStore, msg: dict, send: SendFn) -> None:
    doc_id = msg.get("document_id")
    if not doc_id:
        return
    if store.redo(doc_id) is None:
        await _send_error(send, msg, "no_redo",
                          "Nothing to redo on this document.")


async def _handle_delete(store: DocumentSessionStore, msg: dict, send: SendFn) -> None:
    doc_id = msg.get("document_id")
    if doc_id:
        store.delete(doc_id)


_HANDLERS: dict[str, Callable[[DocumentSessionStore, dict, SendFn], Awaitable[None]]] = {
    "client_doc_create": _handle_create,
    "client_doc_update": _handle_update,
    "client_doc_undo":   _handle_undo,
    "client_doc_redo":   _handle_redo,
    "client_doc_delete": _handle_delete,
}


# ---------------------------------------------------------------------------
# Server-side notify wiring (caller binds it during session setup)
# ---------------------------------------------------------------------------


def make_doc_notify(send: SendFn) -> Callable[[str, Any], None]:
    """Build a ``_notify`` callback for ``DocumentSessionStore.set_notify_callback``.

    The returned callable closes over ``send``, which the caller MUST
    have already bound to the specific WS connection for this session.
    The store fires the callback synchronously from inside its lock;
    we marshal each event onto the asyncio loop so the caller's send
    coroutine actually executes.

    Important: every such callback is bound to ONE WS / ONE session.
    Don't reuse a notifier across sessions.
    """
    import asyncio
    def _notify(event_type: str, doc) -> None:
        asyncio.ensure_future(send({
            "type": event_type,
            "document": client_doc_payload(doc),
        }))
    return _notify


# ---------------------------------------------------------------------------
# Error-shape helpers — keep the wire format consistent across all paths
# ---------------------------------------------------------------------------


async def _send_error(send: SendFn, msg: dict, code: str, message: str) -> None:
    await send({
        "type": "client_doc_error",
        "request_id": msg.get("request_id"),
        "errors": [{"code": code, "message": message, "hint": None, "path": None}],
    })


async def _send_op_error(send: SendFn, msg: dict, op_error: dict) -> None:
    await send({
        "type": "client_doc_error",
        "request_id": msg.get("request_id"),
        "errors": [{
            "code": op_error.get("error", "operation_failed"),
            "message": op_error.get("message", "operation failed"),
            "hint": op_error.get("hint"),
            "path": op_error.get("failed_operation"),
        }],
    })


async def _send_validation_errors(send: SendFn, msg: dict, errors: list) -> None:
    await send({
        "type": "client_doc_error",
        "request_id": msg.get("request_id"),
        "errors": [
            {"code": e.code, "message": e.message,
             "hint": e.hint, "path": e.path}
            for e in errors
        ],
    })
