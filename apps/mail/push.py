"""Mail push manager — per-session polling and server-initiated events.

Polls the inbox head every 10 s per active WebSocket session.  When
the top message changes, pushes ``mail.new_mail`` to all WS connections
bound to that session.  Tracks messages in virus-scan state and pushes
``mail.scan_done`` when the scan completes.

Usage (from the ``/ws/mail`` handler)::

    push_manager = MailPushManager()

    @app.websocket("/ws/mail")
    async def mail_ws(ws):
        ...
        push_manager.register(session_id, ws, graph, _mail_to_row)
        try:
            while True: ...
        finally:
            push_manager.unregister(session_id, ws)
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from fastapi import WebSocket

log = logging.getLogger(__name__)

POLL_INTERVAL = 10  # seconds


class MailPushManager:
    """Manages per-session polling and fan-out to WebSocket connections."""

    def __init__(self):
        # session_id → set of (ws, graph, row_fn) tuples
        self._connections: dict[str, set] = defaultdict(set)
        # session_id → asyncio.Task
        self._pollers: dict[str, asyncio.Task] = {}
        # session_id → {folder_id: last_top_message_id}
        self._inbox_state: dict[str, dict[str, str]] = defaultdict(dict)
        # session_id → {message_id: retries_left}
        self._scan_watchlist: dict[str, dict[str, int]] = defaultdict(dict)

    def register(self, session_id: str, ws: "WebSocket", graph, row_fn: Callable):
        """Add a WS connection and start polling if this is the first for the session."""
        entry = (ws, graph, row_fn)
        self._connections[session_id].add(entry)
        log.info("[PUSH] register session=%s, connections=%d, has_poller=%s",
                 session_id[:16], len(self._connections[session_id]),
                 session_id in self._pollers)
        if session_id not in self._pollers:
            self._pollers[session_id] = asyncio.create_task(
                self._poll_loop(session_id, graph, row_fn),
            )
            log.info("[PUSH] poller started for session=%s", session_id[:16])

    def unregister(self, session_id: str, ws: "WebSocket"):
        """Remove a WS connection.  Stops the poller when the last one leaves."""
        conns = self._connections.get(session_id)
        if not conns:
            return
        conns.discard(next((e for e in conns if e[0] is ws), None))
        if not conns:
            del self._connections[session_id]
            task = self._pollers.pop(session_id, None)
            if task:
                task.cancel()
            self._inbox_state.pop(session_id, None)
            self._scan_watchlist.pop(session_id, None)

    def watch_scanning(self, session_id: str, message_id: str, max_retries: int = 4):
        """Add a message to the scan watchlist (checked every poll tick)."""
        self._scan_watchlist[session_id][message_id] = max_retries

    # ── internal ─────────────────────────────────────────────────

    async def _push(self, session_id: str, msg: dict):
        """Fan out a push message to all WS connections for a session."""
        conns = self._connections.get(session_id)
        if not conns:
            return
        dead = []
        for entry in list(conns):
            ws = entry[0]
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(entry)
        for entry in dead:
            conns.discard(entry)

    async def _poll_loop(self, session_id: str, graph, row_fn: Callable):
        log.info("[PUSH] poll_loop entering for session=%s", session_id[:16])
        try:
            while True:
                await asyncio.sleep(POLL_INTERVAL)
                await self._poll_tick(session_id, graph, row_fn)
        except asyncio.CancelledError:
            log.info("[PUSH] poller cancelled for session=%s", session_id[:16])
        except Exception:
            log.exception("[PUSH] poller crashed for session %s", session_id[:8])

    async def _poll_tick(self, session_id: str, graph, row_fn: Callable):
        # ── Check for new inbox mail ───────────────────────
        try:
            result = await graph.get_mail().email_index_async(
                limit=1, folder_id="inbox",
            )
        except Exception as exc:
            log.warning("[PUSH] poll_tick fetch failed for session=%s: %s",
                        session_id[:16], exc)
            return  # transient — skip this tick

        if result.elements:
            top = result.elements[0]
            top_id = top.email_id
            last_top = self._inbox_state[session_id].get("inbox")
            log.debug("[PUSH] tick session=%s top=%s last=%s",
                      session_id[:16], top_id[:12], (last_top or "")[:12])

            if last_top is not None and top_id != last_top:
                await self._push(session_id, {
                    "action": "mail.new_mail",
                    "folder_id": "inbox",
                    "message": row_fn(top),
                })

            self._inbox_state[session_id]["inbox"] = top_id

        # ── Check scan watchlist ───────────────────────────
        watchlist = self._scan_watchlist.get(session_id)
        if not watchlist:
            return

        done = []
        expired = []
        for msg_id, retries in list(watchlist.items()):
            try:
                mail = await graph.get_mail().get_mail_async(email_id=msg_id)
                if mail and not mail.scanning:
                    done.append(msg_id)
                elif retries <= 1:
                    expired.append(msg_id)
                else:
                    watchlist[msg_id] = retries - 1
            except Exception:
                if retries <= 1:
                    expired.append(msg_id)
                else:
                    watchlist[msg_id] = retries - 1

        for msg_id in done:
            watchlist.pop(msg_id, None)
            await self._push(session_id, {
                "action": "mail.scan_done",
                "message_id": msg_id,
            })

        for msg_id in expired:
            watchlist.pop(msg_id, None)
            log.info("Scan watch expired for %s (session %s)", msg_id[:12], session_id[:8])
