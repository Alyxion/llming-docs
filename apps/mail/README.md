# Mail App

Outlook-style web mail client built with FastAPI, Vue 3, Quasar, and Phosphor Icons. Uses the [office-connect](https://github.com/Alyxion/office-connect) library for Microsoft 365 integration.

## Features

- **3-panel mail layout** — folder sidebar, message list with date grouping, reading pane
- **Rich HTML emails** — signatures, newsletters, tables, inline images (CID resolved to data URIs)
- **Compose** — new mail, reply, reply all, forward, CC/BCC, people autocomplete from directory
- **Calendar** — month/week/day views, color-coded by status (busy/tentative/OOF/free), right-click to create
- **People directory** — search, profile photos, click-to-email
- **Attachments** — displayed in reading pane, clickable to download
- **Context menus** — right-click on emails (reply, forward, delete) and calendar events
- **Mark as read** — 3.5s delay like Outlook, cancelled on navigation
- **Mock mode** — full synthetic data, no real O365 account needed

## Setup

### Prerequisites

- Python 3.14+
- The [office-connect](https://github.com/Alyxion/office-connect) library (installed or on sys.path)
- HTTPS proxy at localhost:8443 forwarding to port 8080 (for OAuth redirect)

### Install

```bash
cd /path/to/llming-docs

# Install office-connect (sibling repo)
pip install -e ../office-connect

# Install app dependencies
pip install fastapi uvicorn python-dotenv beautifulsoup4
```

### Configure

```bash
cp apps/mail/.env.template apps/mail/.env
# Edit .env with your Azure AD credentials
```

### Run

```bash
# Real O365 mode
python apps/mail/web_app.py

# Mock mode (no credentials needed)
MOCK_MODE=1 python apps/mail/web_app.py
```

Open https://localhost:8443/

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MOCK_MODE` | No | `0` | Set to `1` for synthetic data |
| `O365_CLIENT_ID` | Real mode | — | Azure AD app client ID |
| `O365_CLIENT_SECRET` | Real mode | — | Azure AD app secret |
| `O365_TENANT_ID` | Real mode | `common` | Azure tenant ID |
| `O365_ENDPOINT` | No | `https://graph.microsoft.com/v1.0/` | MS Graph endpoint |
| `SAMPLE_BASE_URL` | No | `https://localhost:8443` | Browser-visible base URL |
| `SAMPLE_PORT` | No | `8080` | Port to bind |
| `OFFICE_CONNECT_PATH` | No | `../../../office-connect` | Path to office-connect repo (if not pip installed) |
| `FACES_DIR` | No | `apps/mail/assets/faces` | Directory with face photo JPEGs |

## Tech Stack

- **Backend:** FastAPI (Python)
- **Frontend:** Vue 3 + Quasar Framework (UMD, no build step)
- **Icons:** Phosphor Icons + Material Icons
- **Library:** office-connect (`office_con`)

All vendor JS/CSS/fonts are bundled in `static/vendor/`. See [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

## File Structure

```
apps/mail/
├── web_app.py               # FastAPI backend (OAuth, Mail, Calendar, People APIs)
├── .env.template             # Environment variable template
├── THIRD-PARTY-NOTICES.md    # Vendor library licenses
├── static/
│   ├── index.html            # Vue 3 / Quasar SPA
│   ├── app.js                # Application logic
│   ├── app.css               # Outlook-style theme
│   └── vendor/               # Bundled libraries (Vue, Quasar, Phosphor, Material Icons)
└── assets/
    └── faces/                # Profile photos for mock directory (male_*.jpg, female_*.jpg)
```

## Mock Data

When `MOCK_MODE=1`, the app is pre-authenticated with synthetic data from office-connect's mock system:

- **Mail:** 34 messages across 6 folders (Inbox, Sent, Drafts, Deleted, Notifications, Done). Mix of internal (matching directory users) and external senders. Rich HTML with signatures, newsletters, GitHub/Jira/AWS notifications. Fake downloadable attachments.
- **Calendar:** 127 events across 3 months. Daily standups, weekly meetings, 1:1s, customer demos, OOF/vacation, Teams calls, all-day events, tentative/free blocks.
- **Directory:** 25 users with org hierarchy (CEO → VPs → Directors → ICs), 7 departments, phone numbers, and real face photos from `assets/faces/`.
- **Teams/Chats:** 2 teams, 2 chats with basic structure.

Face photos are loaded by gender from `assets/faces/` (26 photos, 348 KB total, sourced from pravatar.cc).

## Dependencies on office-connect

This app imports from `office_con`:

```python
from office_con.msgraph.ms_graph_handler import MsGraphInstance
from office_con.mcp_server import export_keyfile
from office_con.auth.office_user_instance import OfficeUserInstance
from office_con.testing.fixtures import default_mock_profile
from office_con.testing.mock_data import set_faces_dir
```

Key interfaces used:
- `MsGraphInstance` — OAuth, token management, `run_async()` for raw Graph calls
- `graph.get_mail()` → `OfficeMailHandler` — `email_index_async`, `get_mail_async`, `send_message_async`, `create_draft_async`, `send_draft_async`, `flag_read_async`
- `graph.get_calendar()` → `CalendarHandler` — `get_calendars_async`, `get_events_async`
- `graph.get_directory()` → `DirectoryHandler` — `get_users_async`, `get_user_photo_async`
- `graph.get_profile_async()` → `ProfileHandler`
- `graph.enable_mock(profile)` — activates mock transport
- `export_keyfile()` — writes token JSON with 0600 permissions
- `OfficeUserInstance.PROFILE_SCOPE` etc. — OAuth scope constants (never hardcode scope strings)

### MS Graph timestamp format

office-connect's `parse_mail()` expects `%Y-%m-%dT%H:%M:%SZ` (UTC, Z-suffix). Use `strftime`, not `isoformat()`.

### CID image embedding

The `GET /api/mail/messages/{id}` endpoint resolves `cid:` references in HTML bodies to base64 data URIs using BeautifulSoup before returning to the frontend.
