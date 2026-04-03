"""Unified provider interfaces for mail, calendar, files, people, and more.

Adapters (msgraph, gmail, mock) implement these interfaces so that
applications work identically regardless of the backend.
"""

from __future__ import annotations

from llming_docs.providers.base import (
    AuthProvider,
    MailProvider,
    CalendarProvider,
    PeopleProvider,
    FileProvider,
    SlidesProvider,
    SheetsProvider,
)
from llming_docs.providers.models import (
    Folder, Message, MessageList, Attachment, DraftMessage,
    Calendar, Event, EventList, Attendee,
    Person, PersonList,
    Drive, DriveItem, DriveItemList,
    Slide, SlideList,
    Sheet, SheetList,
    UserProfile,
)

__all__ = [
    # Providers
    "AuthProvider", "MailProvider", "CalendarProvider",
    "PeopleProvider", "FileProvider", "SlidesProvider", "SheetsProvider",
    # Models
    "Folder", "Message", "MessageList", "Attachment", "DraftMessage",
    "Calendar", "Event", "EventList", "Attendee",
    "Person", "PersonList",
    "Drive", "DriveItem", "DriveItemList",
    "Slide", "SlideList", "Sheet", "SheetList",
    "UserProfile",
]
