"""Abstract base classes for provider adapters.

Each service area (mail, calendar, files, people, slides, sheets) is a
separate ABC. Adapters implement the ones they support. The composite
``Provider`` class combines auth + all service areas -- adapters raise
``NotImplementedError`` for unsupported areas.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from llming_docs.providers.models import (
    Attachment,
    Calendar,
    DraftMessage,
    Drive,
    DriveItem,
    DriveItemList,
    Event,
    EventList,
    Folder,
    Message,
    MessageList,
    Person,
    Sheet,
    SheetList,
    Slide,
    SlideList,
    UserProfile,
)


class AuthProvider(ABC):
    """Authentication and session management."""

    @property
    @abstractmethod
    def is_authenticated(self) -> bool: ...

    @property
    @abstractmethod
    def user_email(self) -> str | None: ...

    @property
    @abstractmethod
    def user_name(self) -> str | None: ...

    @abstractmethod
    def build_login_url(self, redirect_uri: str) -> str: ...

    @abstractmethod
    async def handle_oauth_callback(self, code: str, redirect_uri: str) -> bool: ...

    @abstractmethod
    async def get_profile(self) -> UserProfile: ...


class MailProvider(ABC):
    """Mail operations."""

    @abstractmethod
    async def list_folders(self) -> list[Folder]: ...

    @abstractmethod
    async def list_messages(
        self, folder_id: str, limit: int = 20, skip: int = 0
    ) -> MessageList: ...

    @abstractmethod
    async def get_message(self, message_id: str) -> Message | None: ...

    @abstractmethod
    async def send_message(self, draft: DraftMessage) -> bool: ...

    @abstractmethod
    async def create_draft(self, draft: DraftMessage) -> Message | None: ...

    @abstractmethod
    async def reply(
        self, message_id: str, body: str, reply_all: bool = False
    ) -> bool: ...

    @abstractmethod
    async def mark_read(self, message_id: str, is_read: bool = True) -> bool: ...

    @abstractmethod
    async def download_attachment(
        self, message_id: str, attachment_name: str
    ) -> tuple[bytes, str] | None: ...


class CalendarProvider(ABC):
    """Calendar operations."""

    @abstractmethod
    async def list_calendars(self) -> list[Calendar]: ...

    @abstractmethod
    async def list_events(
        self, start: str, end: str, limit: int = 50
    ) -> EventList: ...

    @abstractmethod
    async def create_event(self, event: Event) -> Event | None: ...


class PeopleProvider(ABC):
    """People / directory / contacts."""

    @abstractmethod
    async def search_people(self, query: str) -> list[Person]: ...

    @abstractmethod
    async def get_photo(self, person_id: str) -> bytes | None: ...

    @abstractmethod
    async def get_email_map(self) -> dict[str, Person]: ...


class FileProvider(ABC):
    """File storage operations (OneDrive, Google Drive, SharePoint)."""

    @abstractmethod
    async def list_drives(self) -> list[Drive]: ...

    @abstractmethod
    async def list_items(
        self,
        drive_id: str | None = None,
        folder_id: str | None = None,
        limit: int = 50,
    ) -> DriveItemList: ...

    @abstractmethod
    async def get_item(
        self, item_id: str, drive_id: str | None = None
    ) -> DriveItem | None: ...

    @abstractmethod
    async def download(
        self, item_id: str, drive_id: str | None = None
    ) -> bytes | None: ...

    @abstractmethod
    async def search(self, query: str, limit: int = 25) -> DriveItemList: ...


class SlidesProvider(ABC):
    """Presentation/slides operations."""

    @abstractmethod
    async def list_slides(self, presentation_id: str) -> SlideList: ...

    @abstractmethod
    async def get_slide(
        self, presentation_id: str, slide_id: str
    ) -> Slide | None: ...


class SheetsProvider(ABC):
    """Spreadsheet operations."""

    @abstractmethod
    async def list_sheets(self, workbook_id: str) -> SheetList: ...

    @abstractmethod
    async def read_range(
        self, workbook_id: str, sheet_id: str, range_ref: str
    ) -> list[list]: ...


class Provider(
    AuthProvider, MailProvider, CalendarProvider, PeopleProvider, FileProvider
):
    """Composite provider -- adapters subclass this and implement what they support.

    Unimplemented methods raise NotImplementedError by default.
    Adapters override only the methods they can handle.
    """

    @property
    def provider_name(self) -> str:
        return "unknown"

    # Default implementations that raise -- subclasses override what they support.

    # SlidesProvider and SheetsProvider are optional extensions,
    # not included in the base composite to keep the required surface small.
