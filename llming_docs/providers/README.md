# Providers

Providers are backend adapters that supply mail, calendar, people, and file
data to llming-docs applications.  Every provider exposes the same interface
so that UI code works identically regardless of the data source.

## Available Providers

| Provider | Module | Status | Dependencies |
|----------|--------|--------|--------------|
| **MS Graph** | `providers.msgraph` | Auth + structure | `office-connect` |
| **Mock** | `providers.mock` | Fully functional | None |
| **Gmail** | `providers.gmail` | Stub | `google-auth`, `google-api-python-client` |

## Architecture

```
Application (UI / API)
        |
   Provider interface  (properties + methods)
        |
   +-----------+-----------+-----------+
   | MsGraph   | Mock      | Gmail     |
   | Provider  | Provider  | Provider  |
   +-----------+-----------+-----------+
        |            |           |
   office-connect  fixtures   google-api
```

### Core Concepts

- **Provider** -- a class that implements a common set of properties
  (`provider_name`, `is_authenticated`, `user_email`, `user_name`) and
  methods (`build_login_url`, `handle_oauth_callback`, mail/calendar/people
  operations).
- **Unified models** -- Pydantic v2 `BaseModel` subclasses defined in
  `providers.models` (`Folder`, `Message`, `Event`, `Person`, etc.) that
  every provider maps its raw data into.
- **Fixtures** -- the mock provider generates its own synthetic data in
  `mock/fixtures.py` using the same JSON shapes as the MS Graph API, making
  it a drop-in replacement for development and testing.

## Model Hierarchy

```
Mail
├── Folder
├── Message / MessageList
├── Attachment
└── DraftMessage

Calendar
├── Calendar
├── Event / EventList
└── Attendee

People
├── Person / PersonList
└── UserProfile

Files
├── Drive
└── DriveItem / DriveItemList

Presentations
├── Slide / SlideList

Spreadsheets
├── Sheet / SheetList
```

## How to Write an Adapter

1. Create a new package under `providers/` (e.g., `providers/mybackend/`).

2. Implement a provider class with these properties and methods:

```python
from __future__ import annotations

class MyProvider:
    """Custom backend adapter."""

    @property
    def provider_name(self) -> str:
        return "mybackend"

    @property
    def is_authenticated(self) -> bool:
        ...

    @property
    def user_email(self) -> str | None:
        ...

    @property
    def user_name(self) -> str | None:
        ...

    def build_login_url(self, redirect_uri: str) -> str:
        ...

    async def handle_oauth_callback(self, code: str, redirect_uri: str) -> bool:
        ...

    # Mail operations
    def list_folders(self) -> list[dict]: ...
    def list_messages(self, folder_id: str, top: int, skip: int) -> list[dict]: ...
    def get_message(self, message_id: str) -> dict | None: ...

    # Calendar operations
    def list_events(self, start: str | None, end: str | None) -> list[dict]: ...

    # People operations
    def list_people(self, query: str | None, top: int) -> list[dict]: ...
    def get_person(self, person_id: str) -> dict | None: ...
    def get_person_photo(self, person_id: str) -> bytes | None: ...
```

3. Map your backend's raw responses into the unified model dicts (same
   JSON shape as MS Graph).  This ensures all consumers work without changes.

4. Register the provider in your application code -- there is no global
   registry; the app decides which provider(s) to instantiate.

## How Applications Consume Providers

Applications accept a provider instance at startup and call its methods
without caring which backend is active:

```python
from llming_docs.providers.mock import MockProvider
from llming_docs.providers.msgraph import MsGraphProvider

# Pick one based on configuration
if config.use_mock:
    provider = MockProvider()
else:
    provider = MsGraphProvider(
        client_id=config.client_id,
        client_secret=config.client_secret,
        tenant_id=config.tenant_id,
    )

# Use identically regardless of backend
folders = provider.list_folders()
events = provider.list_events()
people = provider.list_people(query="engineering")
```

## Multiple Provider Instances

An application can run several providers in parallel -- for example, an
MS Graph provider for production data alongside a mock provider for demo
accounts, or two MS Graph instances pointing at different tenants:

```python
providers = {
    "production": MsGraphProvider(client_id=..., tenant_id="tenant-a"),
    "partner":    MsGraphProvider(client_id=..., tenant_id="tenant-b"),
    "demo":       MockProvider(),
}

# Route by account
for name, provider in providers.items():
    if provider.is_authenticated:
        inbox = provider.list_messages("inbox")
```

## Future Roadmap

- **Gmail provider** -- full implementation covering Gmail, Google Calendar,
  and Google Drive using the official Google API client.
- **Google Slides adapter** -- read/write presentation decks via the
  Slides API, mapped to `Slide` / `SlideList` models.
- **Google Sheets adapter** -- spreadsheet access via the Sheets API,
  mapped to `Sheet` / `SheetList` models.
- **Formal Protocol/ABC** -- extract the provider interface into a
  `typing.Protocol` or `abc.ABC` base class for static type checking.
- **Async-first** -- migrate all I/O methods to async with sync wrappers.
