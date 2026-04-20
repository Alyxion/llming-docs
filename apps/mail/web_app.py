"""Outlook-style mail client — FastAPI + Vue 3 / Quasar.

Requires the office-connect library (office_con) to be installed or on sys.path.

    cd /path/to/llming-docs
    cp apps/mail/.env.template apps/mail/.env   # fill in credentials
    python apps/mail/web_app.py

Accessible via https://localhost:8443/ (behind the HTTPS proxy on port 8080).
Set MOCK_MODE=1 in .env for synthetic data without real O365 credentials.
"""

from __future__ import annotations

import logging
import os
import secrets
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

import uvicorn
from fastapi import FastAPI, Request, Response, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

APP_DIR = Path(__file__).resolve().parent
DOCS_PROJECT_DIR = APP_DIR.parent.parent  # llming-docs root
STATIC_DIR = APP_DIR / "static"
ASSETS_DIR = APP_DIR / "assets"

# Token file — stored alongside the app for test reuse
TOKEN_FILE = APP_DIR / "msgraph_test_token.json"

# Load .env from app directory
load_dotenv(APP_DIR / ".env")

# office-connect must be installed (pip/poetry) or available on sys.path.
# For local dev alongside sibling repos:
# llming-docs root (for llming_docs.providers imports)
_docs_root = APP_DIR.parent.parent  # llming-docs/
sys.path.insert(0, str(_docs_root))

# office-connect must be installed (pip/poetry) or available on sys.path.
_office_connect_path = Path(os.environ.get(
    "OFFICE_CONNECT_PATH",
    str(_docs_root.parent / "office-connect"),  # ../office-connect
))
if _office_connect_path.is_dir():
    sys.path.insert(0, str(_office_connect_path))

from office_con.msgraph.ms_graph_handler import MsGraphInstance       # noqa: E402
from office_con.msgraph.mail_handler import compute_folder_signature # noqa: E402
from office_con.mcp_server import export_keyfile                     # noqa: E402
from office_con.auth.office_user_instance import OfficeUserInstance   # noqa: E402
from push import MailPushManager                                     # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MOCK_MODE = os.environ.get("MOCK_MODE", "").strip() in ("1", "true", "yes")
PORT = int(os.environ.get("SAMPLE_PORT", "8080"))
# Base URL as seen by the browser (behind the HTTPS proxy)
BASE_URL = os.environ.get("SAMPLE_BASE_URL", "https://localhost:8443")
REDIRECT_URI = f"{BASE_URL}/auth"

SCOPES = list(set(
    OfficeUserInstance.PROFILE_SCOPE
    + OfficeUserInstance.MAIL_SCOPE
    + OfficeUserInstance.CALENDAR_SCOPE
))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("sample")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(docs_url=None, redoc_url=None)

# CSRF token per process (single-user dev tool)
CSRF_TOKEN = secrets.token_hex(16)

SESSION_COOKIE = "mail_session"

# Session store — maps session ID → MsGraphInstance
_sessions: dict[str, MsGraphInstance] = {}

# Push manager — per-session polling + WS push
_push = MailPushManager()

# Mock data store for chat, teams, files (populated in _init_mock)
_mock_data: dict = {}


def _init_mock() -> MsGraphInstance:
    """Create a pre-authenticated MsGraphInstance backed by synthetic data."""
    from office_con.testing.mock_data import set_faces_dir
    faces_dir = ASSETS_DIR / "faces"
    if faces_dir.is_dir():
        set_faces_dir(faces_dir)
    from office_con.testing.fixtures import default_mock_profile
    profile = default_mock_profile()
    graph = MsGraphInstance(
        scopes=SCOPES,
        endpoint="https://graph.microsoft.com/v1.0/",
        client_id="mock-client-id",
        client_secret="mock-client-secret",
        tenant_id="mock-tenant",
    )
    graph.enable_mock(profile)
    graph.email = profile.email
    graph.user_id = profile.user_id
    graph.given_name = profile.given_name
    graph.full_name = profile.full_name
    graph.cache_dict["access_token"] = "mock-token"
    graph.cache_dict["refresh_token"] = "mock-refresh"

    # Load chat, teams, and files fixtures
    # Import fixtures directly to avoid llming_docs top-level heavy deps
    import importlib.util
    _fix_path = _docs_root / "llming_docs" / "providers" / "mock" / "fixtures.py"
    _spec = importlib.util.spec_from_file_location("mock_fixtures", _fix_path)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    default_chat_conversations = _mod.default_chat_conversations
    default_teams_channels = _mod.default_teams_channels
    default_drive_items = _mod.default_drive_items
    _mock_data["chats"] = default_chat_conversations()
    _mock_data["teams"] = default_teams_channels()
    _mock_data["drive"] = default_drive_items()

    log.info("Mock mode enabled — using synthetic data (no real O365 connection)")
    return graph


MOCK_SESSION_ID = "mock-session"

if MOCK_MODE:
    _sessions[MOCK_SESSION_ID] = _init_mock()


def _mail_to_search_row(m) -> dict:
    """Convert an OfficeMail to the row shape the Vue list/search views expect."""
    return {
        "id": m.email_id,
        "from_name": m.from_name or "",
        "from_email": m.from_email or "",
        "subject": m.subject or "(no subject)",
        "preview": m.body_preview or "",
        "received": m.local_timestamp or "",
        "is_read": m.is_read,
        "has_attachments": m.has_attachments,
        "importance": m.importance or "normal",
        "categories": m.categories,
        # Index queries don't fetch attachment details, so scanning is
        # indeterminate here.  The push system (mail.scan_done) handles
        # scan-state transitions for the client.
        "scanning": False,
    }


def _get_session_id(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE)


def _get_graph(request: Request) -> MsGraphInstance:
    sid = _get_session_id(request)
    if sid is None or sid not in _sessions:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return _sessions[sid]


# ---------------------------------------------------------------------------
# Security middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # CSP: allow Quasar inline styles, font loading, sandboxed mail body iframe
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-eval'; "
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-src 'self' blob:; "
        "frame-ancestors 'none'"
    )
    return response


@app.middleware("http")
async def csrf_check(request: Request, call_next):
    """Require X-CSRF-Token header on state-changing requests."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        token = request.headers.get("X-CSRF-Token", "")
        if token != CSRF_TOKEN:
            return JSONResponse({"error": "CSRF token mismatch"}, status_code=403)
    return await call_next(request)


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def index():
    return HTMLResponse((STATIC_DIR / "index.html").read_text())


@app.get("/auth")
async def oauth_callback(code: str = Query(...)):
    """OAuth callback — Microsoft redirects here with ?code=."""
    graph = MsGraphInstance(
        scopes=SCOPES,
        client_id=os.environ.get("O365_CLIENT_ID"),
        client_secret=os.environ.get("O365_CLIENT_SECRET"),
        tenant_id=os.environ.get("O365_TENANT_ID", "common"),
        endpoint=os.environ.get("O365_ENDPOINT", "https://graph.microsoft.com/v1.0/"),
    )
    result = await graph.acquire_token_async(code, REDIRECT_URI)
    if isinstance(result, HTMLResponse) and result.status_code >= 400:
        return result
    session_id = secrets.token_urlsafe(32)
    _sessions[session_id] = graph
    # Persist token for automated tests
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    export_keyfile(
        str(TOKEN_FILE),
        access_token=graph.cache_dict.get("access_token", ""),
        refresh_token=graph.cache_dict.get("refresh_token", ""),
        client_id=graph.client_id or "",
        client_secret=graph.client_secret or "",
        tenant_id=graph.tenant_id or "common",
        app="office-connect-sample",
        email=graph.email,
    )
    log.info("Token saved to %s", TOKEN_FILE)
    response = RedirectResponse(f"{BASE_URL}/")
    response.set_cookie(
        SESSION_COOKIE, session_id,
        httponly=True, secure=True, samesite="lax", max_age=7 * 86400,
    )
    return response


# Serve static assets (vendor/, app.js, app.css)
app.mount("/vendor", StaticFiles(directory=str(STATIC_DIR / "vendor")), name="vendor")


@app.get("/mail_client.js")
async def serve_mail_client_js():
    return Response(
        (STATIC_DIR / "mail_client.js").read_text(),
        media_type="application/javascript",
    )


@app.get("/mail_hooks.js")
async def serve_mail_hooks_js():
    return Response(
        (STATIC_DIR / "mail_hooks.js").read_text(),
        media_type="application/javascript",
    )


@app.get("/mail_cache.js")
async def serve_mail_cache_js():
    return Response(
        (STATIC_DIR / "mail_cache.js").read_text(),
        media_type="application/javascript",
    )


@app.get("/app.js")
async def serve_js():
    return Response(
        (STATIC_DIR / "app.js").read_text(),
        media_type="application/javascript",
    )


@app.get("/app.css")
async def serve_css():
    return Response(
        (STATIC_DIR / "app.css").read_text(),
        media_type="text/css",
    )


@app.get("/csrf-token")
async def get_csrf():
    return {"token": CSRF_TOKEN}


@app.get("/login")
async def login():
    """Start the OAuth flow — redirect to Microsoft."""
    graph = MsGraphInstance(
        scopes=SCOPES,
        client_id=os.environ.get("O365_CLIENT_ID"),
        client_secret=os.environ.get("O365_CLIENT_SECRET"),
        tenant_id=os.environ.get("O365_TENANT_ID", "common"),
        endpoint=os.environ.get("O365_ENDPOINT", "https://graph.microsoft.com/v1.0/"),
        select_account=True,
    )
    auth_url = graph.build_auth_url(REDIRECT_URI)
    return RedirectResponse(auth_url)


@app.get("/auth-status")
async def auth_status(request: Request):
    sid = _get_session_id(request)
    graph = _sessions.get(sid) if sid else None
    if graph is None:
        return {"authenticated": False}
    return {"authenticated": True, "email": graph.email}


# ---------------------------------------------------------------------------
# Mail HTTP API — attachment binary downloads ONLY.
#
# All other mail reads (folder list, message index, body + metadata,
# search, send, move, delete, drafts, mark_read) travel through the
# ``/ws/mail`` WebSocket.  Binary attachments stay on HTTP so the
# browser can drive "Save As" via ``Content-Disposition`` and use
# Cache-Control + Range requests without blocking the WS JSON channel.
# See docs/mail-architecture.md.
# ---------------------------------------------------------------------------


def _inline_cid_images(body: str, attachments) -> str:
    """Replace ``cid:`` image references in the body with data URIs."""
    if not body or not attachments:
        return body
    import base64
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(body, "html.parser")
    cid_map, name_map = {}, {}
    for att in attachments:
        if att.content_bytes and att.content_type and att.content_type.startswith("image/"):
            if att.content_id:
                cid_map[f"cid:{att.content_id}"] = att
                cid_map[f"cid:{att.content_id.split('@')[0]}"] = att
            name_map[att.name] = att
    changed = False
    for img in soup.find_all("img"):
        src = img.get("src", "")
        att = cid_map.get(src) or name_map.get(src.rsplit("/", 1)[-1])
        if att and att.content_bytes:
            b64 = base64.b64encode(att.content_bytes).decode()
            img["src"] = f"data:{att.content_type};base64,{b64}"
            changed = True
    return str(soup) if changed else body


@app.get("/api/mail/messages/{message_id}/attachments/{attachment_name}")
async def download_attachment(request: Request, message_id: str, attachment_name: str):
    """Download an attachment by message ID and filename."""
    graph = _get_graph(request)
    mail = graph.get_mail()
    result = await mail.get_mail_async(email_id=message_id)
    if result is None:
        raise HTTPException(404, "Message not found")
    for att in result.attachments:
        if att.name == attachment_name and att.content_bytes:
            return Response(
                content=att.content_bytes,
                media_type=att.content_type or "application/octet-stream",
                headers={"Content-Disposition": f'attachment; filename="{att.name}"'}
            )
    raise HTTPException(404, "Attachment not found")


# ---------------------------------------------------------------------------
# Mail — all via WebSocket (except content fetch + downloads)
# ---------------------------------------------------------------------------

async def _ws_folders(graph, data: dict) -> dict:
    """List mail folders with parent_id for tree rendering.

    ``recursive=True`` walks ``childFolders`` so nested folders (e.g.
    ``Inbox/News``) arrive alongside the top-level ones.  The client
    assembles the tree from ``parent_id`` links.
    """
    folders = await graph.get_mail_folders().get_folders_async(recursive=True)
    return {"folders": [f.model_dump() for f in folders]}


async def _ws_messages(graph, data: dict) -> dict:
    """List messages in a folder.

    Supports delta-sync: when ``since_sig`` matches the current folder
    state the server returns ``{unchanged: true, sig}`` and skips the
    payload entirely.
    """
    folder_id = data.get("folder_id", "inbox")
    limit = min(max(int(data.get("limit", 20)), 1), 100)
    skip = max(int(data.get("skip", 0)), 0)
    result = await graph.get_mail().email_index_async(
        limit=limit, skip=skip, folder_id=folder_id,
    )
    rows = [_mail_to_search_row(m) for m in result.elements]
    sig = compute_folder_signature(rows)
    if data.get("since_sig") == sig:
        return {"unchanged": True, "sig": sig}
    return {"messages": rows, "total": result.total_mails, "sig": sig}


async def _ws_get_mail(graph, data: dict) -> dict:
    """Return a full message (body + headers + attachment metadata) over WS.

    Embedded ``cid:`` images are resolved to base64 data URIs and
    inlined into the body before send — the client never needs a
    second round trip to render embedded images.  Attachment binaries
    are NOT included; the client downloads those over HTTP on demand.
    """
    message_id = data.get("message_id")
    if not message_id:
        return {"error": "message_id is required"}
    result = await graph.get_mail().get_mail_async(email_id=message_id)
    if result is None:
        return {"error": "Message not found"}
    out = result.model_dump(exclude={"zip_data"})
    if result.body and result.attachments:
        out["body"] = _inline_cid_images(result.body, result.attachments)
    out["attachments"] = [
        {
            "name": a.name,
            "content_type": a.content_type,
            "is_embedded": a.is_embedded,
            "size": len(a.content_bytes) if a.content_bytes else 0,
        }
        for a in (result.attachments or []) if not a.is_embedded
    ]
    return out


async def _ws_mark_read(graph, data: dict) -> dict:
    message_id = data.get("message_id")
    if not message_id:
        return {"error": "message_id is required"}
    is_read = bool(data.get("is_read", True))
    mail = graph.get_mail()
    await mail.flag_read_async(
        f"{graph.msg_endpoint}me/messages/{message_id}", is_read,
    )
    return {"ok": True, "is_read": is_read}


async def _ws_create_draft(graph, data: dict) -> dict:
    to = data.get("to", [])
    subject = data.get("subject", "")
    content = data.get("body", "")
    is_html = data.get("is_html", False)
    if not to or not subject:
        return {"error": "to and subject are required"}
    mail = graph.get_mail()
    result = await mail.create_draft_async(
        to_recipients=to, subject=subject, body=content, is_html=is_html,
    )
    if result is None:
        return {"error": "Failed to create draft"}
    return result


async def _ws_send(graph, data: dict) -> dict:
    to = data.get("to", [])
    subject = data.get("subject", "")
    content = data.get("body", "")
    is_html = data.get("is_html", False)
    if not to or not subject:
        return {"error": "to and subject are required"}
    mail = graph.get_mail()
    ok = await mail.send_message_async(
        to_recipients=to, subject=subject, body=content, is_html=is_html,
        cc_recipients=data.get("cc") or None,
        bcc_recipients=data.get("bcc") or None,
    )
    if not ok:
        return {"error": "Failed to send"}
    return {"ok": True}


async def _ws_send_draft(graph, data: dict) -> dict:
    message_id = data.get("message_id")
    if not message_id:
        return {"error": "message_id is required"}
    mail = graph.get_mail()
    ok = await mail.send_draft_async(message_id)
    if not ok:
        return {"error": "Failed to send draft"}
    return {"ok": True}


async def _ws_reply(graph, data: dict) -> dict:
    message_id = data.get("message_id")
    comment = data.get("body", "")
    reply_all = data.get("reply_all", False)
    if not message_id:
        return {"error": "message_id is required"}
    token = await graph.get_access_token_async()
    if not token:
        return {"error": "Token expired"}
    action = "replyAll" if reply_all else "reply"
    url = f"{graph.msg_endpoint}me/messages/{message_id}/{action}"
    resp = await graph.run_async(
        url=url, method="POST", json={"comment": comment}, token=token,
    )
    if resp is None or resp.status_code >= 300:
        return {"error": "Failed to send reply"}
    return {"ok": True}


async def _ws_search(graph, data: dict) -> dict:
    q = data.get("q", "").strip()
    if not q:
        return {"error": "q is required"}
    limit = min(max(int(data.get("limit", 25)), 1), 100)
    mail = graph.get_mail()
    result = await mail.email_index_async(limit=limit, query=q)
    return {
        "messages": [_mail_to_search_row(m) for m in result.elements],
        "query": q,
    }


async def _ws_delete(graph, data: dict) -> dict:
    message_id = data.get("message_id")
    if not message_id:
        return {"error": "message_id is required"}
    ok = await graph.get_mail().delete_message_async(message_id)
    if not ok:
        return {"error": "Failed to delete"}
    return {"ok": True}


async def _ws_move(graph, data: dict) -> dict:
    message_id = data.get("message_id")
    destination_id = data.get("destination_id") or data.get("destinationId")
    if not message_id or not destination_id:
        return {"error": "message_id and destination_id are required"}
    result = await graph.get_mail().move_message_async(message_id, destination_id)
    if result is None:
        return {"error": "Failed to move"}
    return result.model_dump()


# ── Reactions (Outlook emoji responses) ─────────────────────────
# Graph's ``message/reactions`` endpoint is still beta; we shell out
# via the raw HTTP client so a handler upgrade in office-connect isn't
# required.  In mock mode we keep per-session reaction state in memory.

_REACTION_BETA = "https://graph.microsoft.com/beta/me/messages/"
_mock_reactions: dict[str, list[dict]] = {}  # message_id → [{reactionType, user}]


async def _ws_get_reactions(graph, data: dict) -> dict:
    message_id = data.get("message_id")
    if not message_id:
        return {"error": "message_id is required"}
    if MOCK_MODE:
        return {"reactions": list(_mock_reactions.get(message_id, []))}
    token = await graph.get_access_token_async()
    if not token:
        return {"error": "Token expired"}
    try:
        resp = await graph.run_async(url=f"{_REACTION_BETA}{message_id}/reactions", token=token)
        if resp is None or resp.status_code >= 400:
            return {"reactions": []}
        return {"reactions": resp.json().get("value", [])}
    except Exception:
        return {"reactions": []}


async def _ws_set_reaction(graph, data: dict) -> dict:
    message_id = data.get("message_id")
    rtype = data.get("reaction_type") or data.get("reactionType")
    if not message_id or not rtype:
        return {"error": "message_id and reaction_type are required"}
    if MOCK_MODE:
        mine = {"reactionType": rtype, "user": {"displayName": getattr(graph, "full_name", "Mock")}}
        entries = [r for r in _mock_reactions.get(message_id, []) if r.get("user", {}).get("displayName") != mine["user"]["displayName"]]
        entries.append(mine)
        _mock_reactions[message_id] = entries
        return {"ok": True, "reaction_type": rtype}
    token = await graph.get_access_token_async()
    if not token:
        return {"error": "Token expired"}
    try:
        resp = await graph.run_async(
            url=f"{_REACTION_BETA}{message_id}/setReaction",
            method="POST", json={"reactionType": rtype}, token=token,
        )
        if resp is None or resp.status_code >= 300:
            return {"error": "Failed to set reaction"}
        return {"ok": True, "reaction_type": rtype}
    except Exception as exc:
        return {"error": str(exc)}


async def _ws_unset_reaction(graph, data: dict) -> dict:
    message_id = data.get("message_id")
    if not message_id:
        return {"error": "message_id is required"}
    if MOCK_MODE:
        who = getattr(graph, "full_name", "Mock")
        _mock_reactions[message_id] = [r for r in _mock_reactions.get(message_id, [])
                                       if r.get("user", {}).get("displayName") != who]
        return {"ok": True}
    token = await graph.get_access_token_async()
    if not token:
        return {"error": "Token expired"}
    try:
        resp = await graph.run_async(
            url=f"{_REACTION_BETA}{message_id}/unsetReaction",
            method="POST", json={}, token=token,
        )
        if resp is None or resp.status_code >= 300:
            return {"error": "Failed to clear reaction"}
        return {"ok": True}
    except Exception as exc:
        return {"error": str(exc)}


_WS_ACTIONS = {
    "folders": _ws_folders,
    "messages": _ws_messages,
    "get_mail": _ws_get_mail,
    "mark_read": _ws_mark_read,
    "create_draft": _ws_create_draft,
    "send": _ws_send,
    "send_draft": _ws_send_draft,
    "reply": _ws_reply,
    "search": _ws_search,
    "delete": _ws_delete,
    "move": _ws_move,
    "get_reactions": _ws_get_reactions,
    "set_reaction": _ws_set_reaction,
    "unset_reaction": _ws_unset_reaction,
}


@app.websocket("/ws/mail")
async def mail_ws(ws: WebSocket):
    """Single WebSocket for all mail actions.

    Session is identified by the ``mail_session`` cookie set during OAuth.
    Client sends JSON: ``{"action": "<name>", "id": "<correlation>", ...data}``
    Server responds: ``{"id": "<correlation>", ...result}``
    """
    sid = ws.cookies.get(SESSION_COOKIE)
    graph = _sessions.get(sid) if sid else None
    if graph is None:
        await ws.close(code=4401, reason="Not authenticated")
        return
    await ws.accept()
    _push.register(sid, ws, graph, _mail_to_search_row)
    try:
        while True:
            msg = await ws.receive_json()
            action = msg.get("action", "")
            correlation_id = msg.get("id")
            handler = _WS_ACTIONS.get(action)
            if handler is None:
                resp = {"error": f"Unknown action: {action}"}
            else:
                try:
                    resp = await handler(graph, msg)
                except Exception as exc:
                    log.exception("WS action %s failed", action)
                    resp = {"error": str(exc)}
            if correlation_id is not None:
                resp["id"] = correlation_id
            resp["action"] = action
            await ws.send_json(resp)
    except WebSocketDisconnect:
        pass
    finally:
        _push.unregister(sid, ws)


# ---------------------------------------------------------------------------
# People / Directory API
# ---------------------------------------------------------------------------

@app.get("/api/people/email-map")
async def people_email_map(request: Request):
    """Return email → user info mapping for sender photo matching."""
    graph = _get_graph(request)
    directory = graph.get_directory()
    result = await directory.get_users_async()
    mapping = {}
    for u in result.users:
        if u.email:
            first = (u.given_name or u.display_name or "?")[0].upper()
            last = (u.surname or "")[0].upper() if u.surname else ""
            mapping[u.email.lower()] = {
                "id": u.id,
                "display_name": u.display_name,
                "initials": first + last,
            }
    return mapping


@app.get("/api/people/search")
async def search_people(request: Request, q: str = Query("", min_length=0)):
    """Search the directory for people matching *q*."""
    graph = _get_graph(request)
    directory = graph.get_directory()
    result = await directory.get_users_async()
    query = q.strip().lower()
    people = []
    for u in result.users:
        if query and query not in (u.display_name or "").lower() \
                and query not in (u.email or "").lower() \
                and query not in (u.job_title or "").lower() \
                and query not in (u.department or "").lower():
            continue
        first = (u.given_name or u.display_name or "?")[0].upper()
        last = (u.surname or "")[0].upper() if u.surname else ""
        people.append({
            "id": u.id,
            "display_name": u.display_name,
            "email": u.email,
            "job_title": u.job_title,
            "department": u.department,
            "initials": first + last,
        })
    return people


@app.get("/api/people/{user_id}/photo")
async def get_person_photo(request: Request, user_id: str):
    """Return a user's profile photo as image/jpeg, or 404."""
    graph = _get_graph(request)
    directory = graph.get_directory()
    photo_bytes = await directory.get_user_photo_async(user_id)
    if photo_bytes is None:
        raise HTTPException(404, "Photo not found")
    mime = "image/svg+xml" if photo_bytes[:4] == b"<svg" else "image/jpeg"
    return Response(content=photo_bytes, media_type=mime)


# ---------------------------------------------------------------------------
# Calendar API
# ---------------------------------------------------------------------------

@app.get("/api/calendar/list")
async def list_calendars(request: Request):
    graph = _get_graph(request)
    cal = graph.get_calendar()
    calendars = await cal.get_calendars_async()
    return [
        {
            "id": c.get("id"),
            "name": c.get("name", ""),
            "color": c.get("hexColor", ""),
            "is_default": c.get("isDefaultCalendar", False),
        }
        for c in calendars
    ]


@app.get("/api/calendar/events")
async def list_events(
    request: Request,
    start: str = Query(None),
    end: str = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    graph = _get_graph(request)
    cal = graph.get_calendar()
    now = datetime.now()
    start_dt = datetime.fromisoformat(start) if start else now - timedelta(days=7)
    end_dt = datetime.fromisoformat(end) if end else now + timedelta(days=30)
    result = await cal.get_events_async(start_date=start_dt, end_date=end_dt, limit=limit)
    return result.model_dump()


# ---------------------------------------------------------------------------
# Chat API
# ---------------------------------------------------------------------------

@app.get("/api/chat/list")
async def list_chats(request: Request):
    """Return chat list for sidebar (id, topic, chatType, lastMessage, members)."""
    if MOCK_MODE:
        chats = _mock_data.get("chats", [])
        return [
            {
                "id": c["id"],
                "topic": c["topic"],
                "chatType": c["chatType"],
                "lastMessage": c.get("lastMessage"),
                "members": c["members"],
            }
            for c in chats
        ]
    # Real mode — use Graph API
    graph = _get_graph(request)
    token = await graph.get_access_token_async()
    if not token:
        raise HTTPException(401, "Token expired")
    try:
        resp = await graph.run_async(
            url=f"{graph.msg_endpoint}me/chats?$expand=members,lastMessagePreview&$top=50",
            token=token,
        )
        if resp is None or resp.status_code != 200:
            raise HTTPException(502, "Failed to fetch chats")
        data = resp.json()
        result = []
        for c in data.get("value", []):
            members = [
                {"displayName": m.get("displayName", ""), "email": m.get("email", "")}
                for m in c.get("members", [])
            ]
            last_msg = c.get("lastMessagePreview")
            result.append({
                "id": c["id"],
                "topic": c.get("topic"),
                "chatType": c.get("chatType", "oneOnOne"),
                "lastMessage": {
                    "content": last_msg.get("body", {}).get("content", "") if last_msg else "",
                    "senderName": (last_msg.get("from", {}).get("user", {}).get("displayName", "")
                                   if last_msg else ""),
                    "timestamp": last_msg.get("createdDateTime", "") if last_msg else "",
                } if last_msg else None,
                "members": members,
            })
        return result
    except Exception as exc:
        log.warning("Chat list failed: %s", exc)
        raise HTTPException(502, "Failed to fetch chats")


@app.get("/api/chat/{chat_id}")
async def get_chat(request: Request, chat_id: str):
    """Return full chat with messages."""
    if MOCK_MODE:
        chats = _mock_data.get("chats", [])
        for c in chats:
            if c["id"] == chat_id:
                return c
        raise HTTPException(404, "Chat not found")
    # Real mode
    graph = _get_graph(request)
    token = await graph.get_access_token_async()
    if not token:
        raise HTTPException(401, "Token expired")
    try:
        # Fetch chat metadata
        resp = await graph.run_async(
            url=f"{graph.msg_endpoint}me/chats/{chat_id}?$expand=members",
            token=token,
        )
        if resp is None or resp.status_code != 200:
            raise HTTPException(502, "Failed to fetch chat")
        chat_data = resp.json()
        # Fetch messages
        msg_resp = await graph.run_async(
            url=f"{graph.msg_endpoint}me/chats/{chat_id}/messages?$top=50",
            token=token,
        )
        messages = []
        if msg_resp and msg_resp.status_code == 200:
            for m in msg_resp.json().get("value", []):
                sender = m.get("from", {}) or {}
                user = sender.get("user", {}) or {}
                messages.append({
                    "id": m.get("id", ""),
                    "senderName": user.get("displayName", ""),
                    "senderEmail": user.get("email", ""),
                    "content": m.get("body", {}).get("content", ""),
                    "timestamp": m.get("createdDateTime", ""),
                    "isFromMe": False,
                    "reactions": [],
                })
        members = [
            {"displayName": mem.get("displayName", ""), "email": mem.get("email", "")}
            for mem in chat_data.get("members", [])
        ]
        return {
            "id": chat_data["id"],
            "topic": chat_data.get("topic"),
            "chatType": chat_data.get("chatType", "oneOnOne"),
            "createdDateTime": chat_data.get("createdDateTime", ""),
            "members": members,
            "messages": messages,
        }
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("Chat fetch failed: %s", exc)
        raise HTTPException(502, "Failed to fetch chat")


# ---------------------------------------------------------------------------
# Teams API
# ---------------------------------------------------------------------------

@app.get("/api/teams/list")
async def list_teams(request: Request):
    """Return teams with channels."""
    if MOCK_MODE:
        teams = _mock_data.get("teams", [])
        return [
            {
                "id": t["id"],
                "displayName": t["displayName"],
                "channels": t["channels"],
            }
            for t in teams
        ]
    # Real mode
    graph = _get_graph(request)
    token = await graph.get_access_token_async()
    if not token:
        raise HTTPException(401, "Token expired")
    try:
        resp = await graph.run_async(
            url=f"{graph.msg_endpoint}me/joinedTeams",
            token=token,
        )
        if resp is None or resp.status_code != 200:
            raise HTTPException(502, "Failed to fetch teams")
        result = []
        for team in resp.json().get("value", []):
            # Fetch channels for each team
            ch_resp = await graph.run_async(
                url=f"{graph.msg_endpoint}teams/{team['id']}/channels",
                token=token,
            )
            channels = []
            if ch_resp and ch_resp.status_code == 200:
                channels = [
                    {
                        "id": ch["id"],
                        "displayName": ch.get("displayName", ""),
                        "lastActivity": ch.get("createdDateTime", ""),
                    }
                    for ch in ch_resp.json().get("value", [])
                ]
            result.append({
                "id": team["id"],
                "displayName": team.get("displayName", ""),
                "channels": channels,
            })
        return result
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("Teams list failed: %s", exc)
        raise HTTPException(502, "Failed to fetch teams")


@app.get("/api/teams/{team_id}/channels/{channel_id}/messages")
async def get_channel_messages(request: Request, team_id: str, channel_id: str):
    """Return messages for a specific channel."""
    if MOCK_MODE:
        teams = _mock_data.get("teams", [])
        for t in teams:
            if t["id"] == team_id:
                messages = t.get("messages", {}).get(channel_id, [])
                return {"messages": messages}
        raise HTTPException(404, "Team not found")
    # Real mode
    graph = _get_graph(request)
    token = await graph.get_access_token_async()
    if not token:
        raise HTTPException(401, "Token expired")
    try:
        resp = await graph.run_async(
            url=f"{graph.msg_endpoint}teams/{team_id}/channels/{channel_id}/messages?$top=50",
            token=token,
        )
        if resp is None or resp.status_code != 200:
            raise HTTPException(502, "Failed to fetch channel messages")
        messages = []
        for m in resp.json().get("value", []):
            sender = m.get("from", {}) or {}
            user = sender.get("user", {}) or {}
            messages.append({
                "id": m.get("id", ""),
                "senderName": user.get("displayName", ""),
                "senderEmail": user.get("email", ""),
                "content": m.get("body", {}).get("content", ""),
                "timestamp": m.get("createdDateTime", ""),
                "reactions": [
                    {"emoji": r.get("reactionType", ""), "count": 1}
                    for r in m.get("reactions", [])
                ],
                "replies": m.get("replyCount", 0),
            })
        return {"messages": messages}
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("Channel messages failed: %s", exc)
        raise HTTPException(502, "Failed to fetch channel messages")


# ---------------------------------------------------------------------------
# Files API
# ---------------------------------------------------------------------------

@app.get("/api/files/recent")
async def list_recent_files(request: Request):
    """Return recently accessed files."""
    if MOCK_MODE:
        drive = _mock_data.get("drive", {})
        return drive.get("recent", [])
    # Real mode
    graph = _get_graph(request)
    token = await graph.get_access_token_async()
    if not token:
        raise HTTPException(401, "Token expired")
    try:
        resp = await graph.run_async(
            url=f"{graph.msg_endpoint}me/drive/recent?$top=20",
            token=token,
        )
        if resp is None or resp.status_code != 200:
            raise HTTPException(502, "Failed to fetch recent files")
        items = []
        for item in resp.json().get("value", []):
            items.append({
                "id": item.get("id", ""),
                "name": item.get("name", ""),
                "type": "folder" if "folder" in item else "file",
                "mimeType": item.get("file", {}).get("mimeType", ""),
                "size": item.get("size", 0),
                "modifiedAt": item.get("lastModifiedDateTime", ""),
                "modifiedBy": (item.get("lastModifiedBy", {})
                               .get("user", {}).get("displayName", "")),
                "path": item.get("parentReference", {}).get("path", "/"),
                "webUrl": item.get("webUrl", ""),
            })
        return items
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("Recent files failed: %s", exc)
        raise HTTPException(502, "Failed to fetch recent files")


@app.get("/api/files/my")
async def list_my_files(request: Request):
    """Return files in the root of the user's OneDrive."""
    if MOCK_MODE:
        drive = _mock_data.get("drive", {})
        return drive.get("my_files", [])
    # Real mode
    graph = _get_graph(request)
    token = await graph.get_access_token_async()
    if not token:
        raise HTTPException(401, "Token expired")
    try:
        resp = await graph.run_async(
            url=f"{graph.msg_endpoint}me/drive/root/children?$top=50",
            token=token,
        )
        if resp is None or resp.status_code != 200:
            raise HTTPException(502, "Failed to fetch files")
        items = []
        for item in resp.json().get("value", []):
            items.append({
                "id": item.get("id", ""),
                "name": item.get("name", ""),
                "type": "folder" if "folder" in item else "file",
                "mimeType": item.get("file", {}).get("mimeType", ""),
                "size": item.get("size", 0),
                "modifiedAt": item.get("lastModifiedDateTime", ""),
                "modifiedBy": (item.get("lastModifiedBy", {})
                               .get("user", {}).get("displayName", "")),
                "path": "/",
                "webUrl": item.get("webUrl", ""),
            })
        return items
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("My files failed: %s", exc)
        raise HTTPException(502, "Failed to fetch files")


@app.get("/api/files/shared")
async def list_shared_files(request: Request):
    """Return files shared with the current user."""
    if MOCK_MODE:
        drive = _mock_data.get("drive", {})
        return drive.get("shared", [])
    # Real mode
    graph = _get_graph(request)
    token = await graph.get_access_token_async()
    if not token:
        raise HTTPException(401, "Token expired")
    try:
        resp = await graph.run_async(
            url=f"{graph.msg_endpoint}me/drive/sharedWithMe?$top=50",
            token=token,
        )
        if resp is None or resp.status_code != 200:
            raise HTTPException(502, "Failed to fetch shared files")
        items = []
        for item in resp.json().get("value", []):
            items.append({
                "id": item.get("id", ""),
                "name": item.get("name", ""),
                "type": "folder" if "folder" in item else "file",
                "mimeType": item.get("file", {}).get("mimeType", ""),
                "size": item.get("size", 0),
                "modifiedAt": item.get("lastModifiedDateTime", ""),
                "modifiedBy": (item.get("lastModifiedBy", {})
                               .get("user", {}).get("displayName", "")),
                "path": item.get("parentReference", {}).get("path", "/"),
                "webUrl": item.get("webUrl", ""),
            })
        return items
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("Shared files failed: %s", exc)
        raise HTTPException(502, "Failed to fetch shared files")


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@app.get("/api/profile")
async def get_profile(request: Request):
    graph = _get_graph(request)
    handler = await graph.get_profile_async()
    if handler.me is None:
        raise HTTPException(502, "Could not load profile")
    return handler.me.model_dump()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        "web_app:app",
        host="0.0.0.0",
        port=PORT,
        log_level="info",
        app_dir=str(APP_DIR),
    )
