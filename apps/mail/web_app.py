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
from fastapi import FastAPI, Request, Response, HTTPException, Query
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
from office_con.mcp_server import export_keyfile                     # noqa: E402
from office_con.auth.office_user_instance import OfficeUserInstance   # noqa: E402

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

# In-memory session — single-user sample app
_graph: Optional[MsGraphInstance] = None

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


if MOCK_MODE:
    _graph = _init_mock()


def _get_graph() -> MsGraphInstance:
    if _graph is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return _graph


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
    global _graph
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
    _graph = graph
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
    return RedirectResponse(f"{BASE_URL}/")


# Serve static assets (vendor/, app.js, app.css)
app.mount("/vendor", StaticFiles(directory=str(STATIC_DIR / "vendor")), name="vendor")


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
async def auth_status():
    if _graph is None:
        return {"authenticated": False}
    return {"authenticated": True, "email": _graph.email}


# ---------------------------------------------------------------------------
# Mail API
# ---------------------------------------------------------------------------

@app.get("/api/mail/folders")
async def list_mail_folders():
    """List mail folders via Graph API."""
    graph = _get_graph()
    token = await graph.get_access_token_async()
    if not token:
        raise HTTPException(401, "Token expired")
    resp = await graph.run_async(
        url=f"{graph.msg_endpoint}me/mailFolders?$top=50",
        token=token,
    )
    if resp is None or resp.status_code != 200:
        raise HTTPException(502, "Failed to fetch folders")
    folders = resp.json().get("value", [])
    return [
        {
            "id": f["id"],
            "name": f.get("displayName", ""),
            "unread": f.get("unreadItemCount", 0),
            "total": f.get("totalItemCount", 0),
        }
        for f in folders
    ]


@app.get("/api/mail/messages")
async def list_messages(
    folder_id: str = Query("inbox"),
    limit: int = Query(20, ge=1, le=100),
    skip: int = Query(0, ge=0),
):
    """List messages in a folder."""
    graph = _get_graph()
    token = await graph.get_access_token_async()
    if not token:
        raise HTTPException(401, "Token expired")
    fields = "id,from,subject,bodyPreview,receivedDateTime,isRead,hasAttachments,importance"
    url = (
        f"{graph.msg_endpoint}me/mailFolders/{folder_id}/messages"
        f"?$select={fields}&$top={limit}&$skip={skip}"
        f"&$orderby=receivedDateTime desc&$count=true"
    )
    resp = await graph.run_async(url=url, token=token)
    if resp is None or resp.status_code != 200:
        raise HTTPException(502, "Failed to fetch messages")
    data = resp.json()
    messages = []
    for m in data.get("value", []):
        from_addr = m.get("from", {}).get("emailAddress", {})
        messages.append({
            "id": m["id"],
            "from_name": from_addr.get("name", ""),
            "from_email": from_addr.get("address", ""),
            "subject": m.get("subject", "(no subject)"),
            "preview": m.get("bodyPreview", ""),
            "received": m.get("receivedDateTime", ""),
            "is_read": m.get("isRead", False),
            "has_attachments": m.get("hasAttachments", False),
            "importance": m.get("importance", "normal"),
        })
    return {"messages": messages, "total": data.get("@odata.count", len(messages))}


@app.get("/api/mail/messages/{message_id}")
async def get_message(message_id: str):
    """Get a single message with body, CID images resolved to data URIs."""
    graph = _get_graph()
    mail = graph.get_mail()
    result = await mail.get_mail_async(email_id=message_id)
    if result is None:
        raise HTTPException(404, "Message not found")
    data = result.model_dump(exclude={"zip_data"})
    # Resolve cid: references to base64 data URIs
    if result.body and result.attachments:
        import base64
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(result.body, "html.parser")
        cid_map = {}
        name_map = {}
        for att in result.attachments:
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
        if changed:
            data["body"] = str(soup)
    # Include attachment metadata without binary content
    if result.attachments:
        data["attachments"] = [
            {"name": a.name, "content_type": a.content_type,
             "is_embedded": a.is_embedded,
             "size": len(a.content_bytes) if a.content_bytes else 0}
            for a in result.attachments if not a.is_embedded
        ]
    else:
        data["attachments"] = []
    return data


@app.get("/api/mail/messages/{message_id}/attachments/{attachment_name}")
async def download_attachment(message_id: str, attachment_name: str):
    """Download an attachment by message ID and filename."""
    graph = _get_graph()
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


@app.patch("/api/mail/read/{message_id}")
async def mark_as_read(message_id: str):
    """Mark a message as read."""
    graph = _get_graph()
    mail = graph.get_mail()
    await mail.flag_read_async(
        f"{graph.msg_endpoint}me/messages/{message_id}", True
    )
    return {"ok": True}


@app.post("/api/mail/draft")
async def create_draft(request: Request):
    """Create a draft message."""
    graph = _get_graph()
    body = await request.json()
    to = body.get("to", [])
    subject = body.get("subject", "")
    content = body.get("body", "")
    is_html = body.get("is_html", False)
    if not to or not subject:
        raise HTTPException(400, "to and subject are required")
    mail = graph.get_mail()
    result = await mail.create_draft_async(
        to_recipients=to, subject=subject, body=content, is_html=is_html,
    )
    if result is None:
        raise HTTPException(502, "Failed to create draft")
    return result


@app.post("/api/mail/send")
async def send_mail(request: Request):
    """Send a new message directly."""
    graph = _get_graph()
    body = await request.json()
    to = body.get("to", [])
    subject = body.get("subject", "")
    content = body.get("body", "")
    is_html = body.get("is_html", False)
    if not to or not subject:
        raise HTTPException(400, "to and subject are required")
    mail = graph.get_mail()
    ok = await mail.send_message_async(
        to_recipients=to, subject=subject, body=content, is_html=is_html,
    )
    if not ok:
        raise HTTPException(502, "Failed to send")
    return {"ok": True}


@app.post("/api/mail/draft/{message_id}/send")
async def send_draft(message_id: str):
    """Send an existing draft."""
    graph = _get_graph()
    mail = graph.get_mail()
    ok = await mail.send_draft_async(message_id)
    if not ok:
        raise HTTPException(502, "Failed to send draft")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Mail reply
# ---------------------------------------------------------------------------

@app.post("/api/mail/reply")
async def reply_to_message(request: Request):
    """Reply (or reply-all) to a message."""
    graph = _get_graph()
    body = await request.json()
    message_id = body.get("message_id")
    comment = body.get("body", "")
    reply_all = body.get("reply_all", False)
    if not message_id:
        raise HTTPException(400, "message_id is required")
    token = await graph.get_access_token_async()
    if not token:
        raise HTTPException(401, "Token expired")
    action = "replyAll" if reply_all else "reply"
    url = f"{graph.msg_endpoint}me/messages/{message_id}/{action}"
    resp = await graph.run_async(
        url=url, method="POST", json={"comment": comment}, token=token,
    )
    if resp is None or resp.status_code >= 300:
        raise HTTPException(502, "Failed to send reply")
    return {"ok": True}


# ---------------------------------------------------------------------------
# People / Directory API
# ---------------------------------------------------------------------------

@app.get("/api/people/email-map")
async def people_email_map():
    """Return email → user info mapping for sender photo matching."""
    graph = _get_graph()
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
async def search_people(q: str = Query("", min_length=0)):
    """Search the directory for people matching *q*."""
    graph = _get_graph()
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
async def get_person_photo(user_id: str):
    """Return a user's profile photo as image/jpeg, or 404."""
    graph = _get_graph()
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
async def list_calendars():
    graph = _get_graph()
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
    start: str = Query(None),
    end: str = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    graph = _get_graph()
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
async def list_chats():
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
    graph = _get_graph()
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
async def get_chat(chat_id: str):
    """Return full chat with messages."""
    if MOCK_MODE:
        chats = _mock_data.get("chats", [])
        for c in chats:
            if c["id"] == chat_id:
                return c
        raise HTTPException(404, "Chat not found")
    # Real mode
    graph = _get_graph()
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
async def list_teams():
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
    graph = _get_graph()
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
async def get_channel_messages(team_id: str, channel_id: str):
    """Return messages for a specific channel."""
    if MOCK_MODE:
        teams = _mock_data.get("teams", [])
        for t in teams:
            if t["id"] == team_id:
                messages = t.get("messages", {}).get(channel_id, [])
                return {"messages": messages}
        raise HTTPException(404, "Team not found")
    # Real mode
    graph = _get_graph()
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
async def list_recent_files():
    """Return recently accessed files."""
    if MOCK_MODE:
        drive = _mock_data.get("drive", {})
        return drive.get("recent", [])
    # Real mode
    graph = _get_graph()
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
async def list_my_files():
    """Return files in the root of the user's OneDrive."""
    if MOCK_MODE:
        drive = _mock_data.get("drive", {})
        return drive.get("my_files", [])
    # Real mode
    graph = _get_graph()
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
async def list_shared_files():
    """Return files shared with the current user."""
    if MOCK_MODE:
        drive = _mock_data.get("drive", {})
        return drive.get("shared", [])
    # Real mode
    graph = _get_graph()
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
async def get_profile():
    graph = _get_graph()
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
