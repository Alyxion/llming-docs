"""Standalone mock provider -- zero external dependencies.

Generates synthetic mail, calendar, people, and file data
for development, testing, and demos.  No office-connect or
network access required.
"""
from __future__ import annotations

from datetime import datetime, timezone

from llming_docs.providers.models import (
    Attachment, Calendar, DraftMessage, Drive, DriveItem, DriveItemList,
    Event, EventList, Folder, Message, MessageList, Person, PersonList,
    UserProfile,
)
from llming_docs.providers.mock.fixtures import (
    default_mail_folders,
    default_mail_messages,
    default_calendar_events,
    default_company_directory,
)
from llming_docs.providers.mock.faces import generate_svg_avatar, load_face


def _parse_msg(raw: dict) -> Message:
    """Convert a raw fixture dict to a unified Message model."""
    from_addr = raw.get("from", {}).get("emailAddress", {})
    body = raw.get("body", {})
    atts = []
    for a in raw.get("attachments", []):
        atts.append(Attachment(
            name=a.get("name", ""),
            content_type=a.get("contentType", "application/octet-stream"),
            size=a.get("size", 0),
            is_inline=a.get("isInline", False),
        ))
    received = raw.get("receivedDateTime")
    return Message(
        id=raw.get("id", ""),
        folder_id=raw.get("_folder_id"),
        subject=raw.get("subject", ""),
        from_name=from_addr.get("name"),
        from_email=from_addr.get("address"),
        body=body.get("content", ""),
        body_type=body.get("contentType", "text"),
        body_preview=raw.get("bodyPreview", ""),
        received_at=datetime.fromisoformat(received) if received else None,
        is_read=raw.get("isRead", False),
        is_draft=raw.get("isDraft", False),
        importance=raw.get("importance", "normal"),
        has_attachments=raw.get("hasAttachments", False),
        attachments=atts,
        categories=raw.get("categories", []),
        web_link=raw.get("webLink"),
    )


def _parse_event(raw: dict) -> Event:
    """Convert a raw fixture dict to a unified Event model."""
    start_str = raw.get("start", {}).get("dateTime", "")
    end_str = raw.get("end", {}).get("dateTime", "")
    organizer = raw.get("organizer", {}).get("emailAddress", {})
    meeting = raw.get("onlineMeeting") or {}
    return Event(
        id=raw.get("id", ""),
        subject=raw.get("subject", ""),
        start_time=datetime.fromisoformat(start_str) if start_str else None,
        end_time=datetime.fromisoformat(end_str) if end_str else None,
        is_all_day=raw.get("isAllDay", False),
        location=(raw.get("location") or {}).get("displayName"),
        organizer_name=organizer.get("name"),
        organizer_email=organizer.get("address"),
        is_online_meeting=raw.get("isOnlineMeeting", False),
        meeting_url=meeting.get("joinUrl"),
        show_as=raw.get("showAs", "busy"),
        importance=raw.get("importance"),
        body_preview=raw.get("bodyPreview"),
    )


def _parse_person(raw: dict) -> Person:
    """Convert a raw fixture dict to a unified Person model."""
    given = raw.get("givenName", "")
    surname = raw.get("surname", "")
    first = (given or raw.get("displayName", "?"))[0].upper()
    last = surname[0].upper() if surname else ""
    return Person(
        id=raw.get("id", ""),
        display_name=raw.get("displayName", ""),
        email=raw.get("mail"),
        given_name=given or None,
        surname=surname or None,
        initials=first + last,
        job_title=raw.get("jobTitle"),
        department=raw.get("department"),
        office_location=raw.get("officeLocation"),
        phone=raw.get("mobilePhone"),
        manager_id=(raw.get("manager") or {}).get("id"),
        is_active=raw.get("accountEnabled", True),
    )


def _parse_folder(raw: dict) -> Folder:
    """Convert a raw fixture dict to a unified Folder model."""
    return Folder(
        id=raw.get("id", ""),
        name=raw.get("displayName", ""),
        parent_id=raw.get("parentFolderId"),
        unread_count=raw.get("unreadItemCount", 0),
        total_count=raw.get("totalItemCount", 0),
        child_count=raw.get("childFolderCount", 0),
    )


class MockProvider:
    """Self-contained mock provider with synthetic data.

    Pre-authenticated and ready to use immediately -- ideal for local
    development, automated tests, and live demos.

    Usage::

        provider = MockProvider(faces_dir="path/to/faces")
        assert provider.is_authenticated
        folders = await provider.list_folders()
    """

    def __init__(self, *, faces_dir: str | None = None):
        self._faces_dir = faces_dir
        self._raw_folders = default_mail_folders()
        self._raw_messages = default_mail_messages()
        self._raw_events = default_calendar_events()
        self._raw_directory = default_company_directory()
        self._user_photos: dict[str, bytes] = self._build_photos()

        # Pre-parse into unified models
        self._folders = [_parse_folder(f) for f in self._raw_folders]
        self._messages = [_parse_msg(m) for m in self._raw_messages]
        self._events = [_parse_event(e) for e in self._raw_events]
        self._people = [_parse_person(u) for u in self._raw_directory]

    def _build_photos(self) -> dict[str, bytes]:
        photos: dict[str, bytes] = {}
        male_idx = female_idx = 0
        colors = [
            "#4A90D9", "#D94A4A", "#4AD97A", "#D9A04A", "#7A4AD9",
            "#D94A9A", "#4AD9D9", "#8B6914", "#2E8B57", "#B22222",
        ]
        for user in self._raw_directory:
            gender = user.get("_gender", "male")
            idx = male_idx if gender == "male" else female_idx
            if gender == "male":
                male_idx += 1
            else:
                female_idx += 1
            photo = load_face(gender, idx, self._faces_dir)
            if photo:
                photos[user["id"]] = photo
            else:
                given = user.get("givenName", "?")
                surname = user.get("surname", "?")
                initials = f"{given[0]}{surname[0]}".upper()
                photos[user["id"]] = generate_svg_avatar(
                    initials, colors[(male_idx + female_idx) % len(colors)])
        return photos

    # ── Properties ────────────────────────────────────────────────

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def user_email(self) -> str | None:
        return "mock@example.com"

    @property
    def user_name(self) -> str | None:
        return "Mock User"

    # ── Auth ──────────────────────────────────────────────────────

    def build_login_url(self, redirect_uri: str) -> str:
        return "https://mock.example.com/auth?already=true"

    async def handle_oauth_callback(self, code: str, redirect_uri: str) -> bool:
        return True

    async def get_profile(self) -> UserProfile:
        return UserProfile(
            id="mock-user-id",
            email="mock@example.com",
            display_name="Mock User",
            given_name="Mock",
            surname="User",
            job_title="Software Engineer",
            department="Engineering",
            provider="mock",
        )

    # ── Mail ──────────────────────────────────────────────────────

    async def list_folders(self) -> list[Folder]:
        return self._folders

    async def list_messages(self, folder_id: str, limit: int = 20, skip: int = 0) -> MessageList:
        msgs = [m for m in self._messages if m.folder_id == folder_id]
        page = msgs[skip:skip + limit]
        return MessageList(messages=page, total=len(msgs))

    async def get_message(self, message_id: str) -> Message | None:
        for m in self._messages:
            if m.id == message_id:
                return m
        return None

    async def send_message(self, draft: DraftMessage) -> bool:
        return True

    async def create_draft(self, draft: DraftMessage) -> Message | None:
        import uuid
        return Message(
            id=str(uuid.uuid4()),
            subject=draft.subject,
            body=draft.body,
            is_draft=True,
        )

    async def reply(self, message_id: str, body: str, reply_all: bool = False) -> bool:
        return True

    async def mark_read(self, message_id: str, is_read: bool = True) -> bool:
        for m in self._messages:
            if m.id == message_id:
                m.is_read = is_read
                return True
        return False

    async def download_attachment(self, message_id: str, attachment_name: str) -> tuple[bytes, str] | None:
        msg = await self.get_message(message_id)
        if not msg:
            return None
        # Look up raw message for binary content
        for raw in self._raw_messages:
            if raw["id"] == message_id:
                import base64
                for att in raw.get("attachments", []):
                    if att.get("name") == attachment_name:
                        content = base64.b64decode(att.get("contentBytes", ""))
                        return content, att.get("contentType", "application/octet-stream")
        return None

    # ── Calendar ──────────────────────────────────────────────────

    async def list_calendars(self) -> list[Calendar]:
        return [Calendar(id="mock-calendar", name="Calendar", is_default=True, is_primary=True)]

    async def list_events(self, start: str, end: str, limit: int = 50) -> EventList:
        filtered = []
        for ev in self._events:
            if ev.start_time is None:
                continue
            ev_date = ev.start_time.strftime("%Y-%m-%d")
            if start and ev_date < start:
                continue
            if end and ev_date > end:
                continue
            filtered.append(ev)
        return EventList(events=filtered[:limit], total=len(filtered))

    async def create_event(self, event: Event) -> Event | None:
        return event

    # ── People ────────────────────────────────────────────────────

    async def search_people(self, query: str) -> list[Person]:
        if not query:
            return self._people
        q = query.lower()
        return [
            p for p in self._people
            if q in (p.display_name or "").lower()
            or q in (p.email or "").lower()
            or q in (p.department or "").lower()
            or q in (p.job_title or "").lower()
        ]

    async def get_photo(self, person_id: str) -> bytes | None:
        return self._user_photos.get(person_id)

    async def get_email_map(self) -> dict[str, Person]:
        return {p.email.lower(): p for p in self._people if p.email}

    # ── Files (minimal stubs) ─────────────────────────────────────

    async def list_drives(self) -> list[Drive]:
        return [Drive(id="mock-drive", name="OneDrive", drive_type="personal")]

    async def list_items(self, drive_id: str | None = None, folder_id: str | None = None, limit: int = 50) -> DriveItemList:
        return DriveItemList()

    async def get_item(self, item_id: str, drive_id: str | None = None) -> DriveItem | None:
        return None

    async def download(self, item_id: str, drive_id: str | None = None) -> bytes | None:
        return None

    async def search(self, query: str, limit: int = 25) -> DriveItemList:
        return DriveItemList()
