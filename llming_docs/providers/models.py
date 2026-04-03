"""Unified data models for all providers.

These models represent the superset of fields across Office 365 (MS Graph)
and Google Workspace (Gmail, Google Calendar, Drive, Slides, Sheets).
Provider adapters map their native response data into these models.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Folder(BaseModel):
    """Mail folder (Office) or label (Gmail)."""

    id: str
    name: str
    parent_id: str | None = None
    unread_count: int = 0
    total_count: int = 0
    child_count: int = 0
    type: str = "folder"  # "folder", "label", "category"


class Attachment(BaseModel):
    """File attached to a message."""

    name: str
    content_type: str = "application/octet-stream"
    size: int = 0
    is_inline: bool = False
    content_id: str | None = None  # for CID references
    download_url: str | None = None  # pre-signed or API URL


class Message(BaseModel):
    """Email message -- unified across Office and Gmail."""

    id: str
    folder_id: str | None = None
    subject: str = ""
    from_name: str | None = None
    from_email: str | None = None
    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)
    body: str = ""
    body_type: str = "text"  # "text" or "html"
    body_preview: str = ""
    received_at: datetime | None = None
    sent_at: datetime | None = None
    is_read: bool = False
    is_draft: bool = False
    is_flagged: bool = False
    importance: str = "normal"  # "low", "normal", "high"
    has_attachments: bool = False
    attachments: list[Attachment] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    conversation_id: str | None = None
    web_link: str | None = None  # deep link to open in web client
    # Gmail-specific
    label_ids: list[str] = Field(default_factory=list)
    thread_id: str | None = None
    # Office-specific
    sensitivity: str | None = None  # normal, personal, private, confidential


class MessageList(BaseModel):
    """Paginated list of messages."""

    messages: list[Message] = Field(default_factory=list)
    total: int = 0


class DraftMessage(BaseModel):
    """Message to be sent or saved as draft."""

    to: list[str]
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)
    subject: str = ""
    body: str = ""
    is_html: bool = False
    attachments: list[Attachment] = Field(default_factory=list)
    # For reply/forward
    reply_to_id: str | None = None
    is_reply_all: bool = False
    is_forward: bool = False


class Attendee(BaseModel):
    """Event attendee."""

    name: str | None = None
    email: str | None = None
    status: str | None = None  # accepted, declined, tentative, none
    type: str = "required"  # required, optional, resource
    is_organizer: bool = False


class Calendar(BaseModel):
    """A calendar."""

    id: str
    name: str = ""
    color: str | None = None
    is_default: bool = False
    is_primary: bool = False  # Gmail terminology
    can_edit: bool = True


class Event(BaseModel):
    """Calendar event -- unified across Office and Google Calendar."""

    id: str
    calendar_id: str | None = None
    subject: str = ""
    body: str | None = None
    body_preview: str | None = None
    body_type: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    is_all_day: bool = False
    location: str | None = None
    organizer_name: str | None = None
    organizer_email: str | None = None
    attendees: list[Attendee] = Field(default_factory=list)
    is_online_meeting: bool = False
    meeting_url: str | None = None  # Teams/Meet join URL
    show_as: str = "busy"  # free, tentative, busy, oof, workingElsewhere
    sensitivity: str | None = None
    importance: str | None = None
    recurrence: str | None = None  # human-readable recurrence description
    # Google-specific
    hangout_link: str | None = None
    # Office-specific
    response_status: str | None = None


class EventList(BaseModel):
    """List of calendar events."""

    events: list[Event] = Field(default_factory=list)
    total: int = 0


class Person(BaseModel):
    """A person in the directory / contacts."""

    id: str
    display_name: str = ""
    email: str | None = None
    given_name: str | None = None
    surname: str | None = None
    initials: str = ""
    job_title: str | None = None
    department: str | None = None
    office_location: str | None = None
    phone: str | None = None
    mobile_phone: str | None = None
    photo_url: str | None = None  # URL to fetch photo
    manager_id: str | None = None
    is_active: bool = True


class PersonList(BaseModel):
    """List of people."""

    people: list[Person] = Field(default_factory=list)
    total: int = 0


class Drive(BaseModel):
    """A file storage drive (OneDrive, Google Drive, SharePoint doc lib)."""

    id: str
    name: str = ""
    drive_type: str = ""  # personal, business, documentLibrary, shared
    owner_name: str | None = None
    total_bytes: int | None = None
    used_bytes: int | None = None
    web_url: str | None = None


class DriveItem(BaseModel):
    """A file or folder in a drive."""

    id: str
    name: str = ""
    path: str | None = None
    is_folder: bool = False
    size: int = 0
    mime_type: str | None = None
    created_at: datetime | None = None
    modified_at: datetime | None = None
    web_url: str | None = None
    download_url: str | None = None
    parent_id: str | None = None
    # Google-specific
    starred: bool = False
    trashed: bool = False


class DriveItemList(BaseModel):
    """List of drive items."""

    items: list[DriveItem] = Field(default_factory=list)
    total: int = 0


class Slide(BaseModel):
    """A presentation slide."""

    id: str
    title: str = ""
    index: int = 0
    notes: str | None = None
    thumbnail_url: str | None = None


class SlideList(BaseModel):
    """List of slides in a presentation."""

    slides: list[Slide] = Field(default_factory=list)
    presentation_id: str | None = None
    presentation_name: str = ""


class Sheet(BaseModel):
    """A spreadsheet sheet/tab."""

    id: str
    title: str = ""
    index: int = 0
    row_count: int = 0
    column_count: int = 0


class SheetList(BaseModel):
    """List of sheets in a workbook."""

    sheets: list[Sheet] = Field(default_factory=list)
    workbook_id: str | None = None
    workbook_name: str = ""


class UserProfile(BaseModel):
    """The authenticated user's profile."""

    id: str
    email: str = ""
    display_name: str = ""
    given_name: str | None = None
    surname: str | None = None
    job_title: str | None = None
    department: str | None = None
    office_location: str | None = None
    phone: str | None = None
    photo_url: str | None = None
    provider: str = ""  # "msgraph", "gmail", "mock"
