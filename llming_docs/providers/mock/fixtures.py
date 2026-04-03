"""Standalone synthetic data for the mock provider.

Generates mail folders, messages, calendar events, and directory users
without any external dependencies.  All data uses the same JSON shapes
as the MS Graph API so that consumers can work with either provider
interchangeably.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return str(uuid.uuid4())


def _dt(dt: datetime) -> str:
    """ISO-8601 without timezone (MS Graph dateTime format)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.0000000")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Mail Folders (9 folders)
# ---------------------------------------------------------------------------

def default_mail_folders() -> list[dict]:
    """Return ~9 synthetic mail folders with realistic Outlook structure."""
    def _folder(
        fid: str,
        name: str,
        parent_id: str | None = None,
        child_count: int = 0,
        unread: int = 0,
        total: int = 0,
    ) -> dict:
        return {
            "id": fid,
            "displayName": name,
            "parentFolderId": parent_id or "root",
            "childFolderCount": child_count,
            "unreadItemCount": unread,
            "totalItemCount": total,
        }

    return [
        _folder("inbox", "Inbox", child_count=2, unread=4, total=10),
        _folder("drafts", "Drafts", total=2),
        _folder("sentitems", "Sent Items", total=3),
        _folder("deleteditems", "Deleted Items", total=1),
        _folder("archive", "Archive", total=0),
        _folder("junkemail", "Junk Email", total=0),
        _folder("outbox", "Outbox", total=0),
        _folder("inbox-notifications", "Notifications", parent_id="inbox", total=2),
        _folder("inbox-done", "Done", parent_id="inbox", total=1),
    ]


# ---------------------------------------------------------------------------
# Mail Messages (~18 across folders)
# ---------------------------------------------------------------------------

def default_mail_messages() -> list[dict]:
    """Return synthetic mail messages across multiple folders.

    Each message includes a ``_folder_id`` key for folder filtering.
    Mix of HTML and plain-text bodies, internal and external senders.
    """
    now = _now()

    def _msg(
        subject: str,
        sender_name: str,
        sender_email: str,
        body: str,
        folder_id: str = "inbox",
        minutes_ago: int = 0,
        is_read: bool = False,
        is_draft: bool = False,
        has_attachments: bool = False,
        importance: str = "normal",
        content_type: str | None = None,
    ) -> dict:
        received = now - timedelta(minutes=minutes_ago)
        ts = received.strftime("%Y-%m-%dT%H:%M:%SZ")
        if content_type is None:
            content_type = "html" if body.lstrip().startswith("<") else "text"
        preview = body[:200].replace("<", "").replace(">", "")[:120]
        return {
            "id": _uid(),
            "subject": subject,
            "from": {
                "emailAddress": {"name": sender_name, "address": sender_email},
            },
            "toRecipients": [
                {"emailAddress": {"name": "Mock User", "address": "mock@example.com"}},
            ],
            "receivedDateTime": ts,
            "sentDateTime": ts,
            "isRead": is_read,
            "isDraft": is_draft,
            "importance": importance,
            "hasAttachments": has_attachments,
            "bodyPreview": preview,
            "body": {"contentType": content_type, "content": body},
            "categories": [],
            "flag": {"flagStatus": "notFlagged"},
            "webLink": f"https://outlook.office.com/mail/mock/{_uid()}",
            "conversationId": _uid(),
            "_folder_id": folder_id,
        }

    messages: list[dict] = []

    # ── Inbox ──────────────────────────────────────────────────────

    messages.append(_msg(
        "All-Hands Meeting: Q2 Strategy Update",
        "Heinrich Fischer", "heinrich.fischer@example.com",
        "<p>Dear Team,</p>"
        "<p>Please join us for the quarterly all-hands this Friday at 14:00.</p>"
        "<p><strong>Agenda:</strong></p>"
        "<ul><li>Q1 results</li><li>Product roadmap</li><li>Q&amp;A</li></ul>"
        "<p>Best regards,<br>Heinrich</p>",
        folder_id="inbox", minutes_ago=30, importance="high",
    ))

    messages.append(_msg(
        "Sprint 24 Review Notes",
        "Lisa Braun", "lisa.braun@example.com",
        "<p>Hi team, great sprint review today! Key outcomes:</p>"
        "<ul>"
        "<li>ENG-1042: API rate limiting -- Done</li>"
        "<li>ENG-1038: Dashboard widgets -- Done</li>"
        "<li>ENG-1060: CI/CD staging -- 80% (carried over)</li>"
        "</ul>"
        "<p>Sprint 25 planning is Monday at 10:00.</p>",
        folder_id="inbox", minutes_ago=90, is_read=True,
    ))

    messages.append(_msg(
        "URGENT: Customer Escalation - Acme Corp",
        "Anna Schmidt", "anna.schmidt@example.com",
        "<p>Acme Corp integration has been returning 503 errors since 08:30. "
        "They cannot process orders. Can Engineering investigate immediately?</p>"
        "<p>I have a follow-up call with their CTO at 15:00.</p>",
        folder_id="inbox", minutes_ago=25, importance="high",
        has_attachments=True,
    ))

    messages.append(_msg(
        "[example-org/api-gateway] PR #347: Fix rate limiter overflow",
        "GitHub", "noreply@github.com",
        "<p>max.mustermann requested your review on "
        "<strong>#347 Fix rate limiter token bucket overflow</strong></p>"
        "<p>Changes: bucket.py (+47 -12), test_bucket.py, CHANGELOG.md</p>",
        folder_id="inbox", minutes_ago=55,
    ))

    messages.append(_msg(
        "TechCrunch Weekly: AI Agents & Cloud Costs",
        "TechCrunch Weekly", "newsletter@techcrunch-weekly.com",
        "<p>This week: AI agents reshaping enterprise software, "
        "FinOps as the new DevOps, and 5 developer tools to try.</p>",
        folder_id="inbox", minutes_ago=180, is_read=True,
    ))

    messages.append(_msg(
        "AWS Billing Alert: Monthly charges exceed $2,500",
        "Amazon Web Services", "billing@aws.amazon.com",
        "Your estimated AWS charges have exceeded the $2,500 threshold.\n\n"
        "EC2: $1,247.83 | RDS: $682.40 | S3: $341.17 | Lambda: $189.52\n"
        "Total: $2,617.00",
        folder_id="inbox", minutes_ago=240, is_read=True,
        has_attachments=True,
    ))

    messages.append(_msg(
        "Meeting Follow-up: Architecture Review",
        "Klaus Weber", "klaus.weber@example.com",
        "<p>Decisions: event-driven architecture for orders, "
        "PostgreSQL + Redis, API versioning via URL path.</p>"
        "<p>Action items assigned to Tobias, Stefan, Sandra, and Max.</p>",
        folder_id="inbox", minutes_ago=320, is_read=True,
        has_attachments=True,
    ))

    messages.append(_msg(
        "Benefits Enrollment Closes April 15",
        "Christine Wagner", "christine.wagner@example.com",
        "Reminder: the annual benefits enrollment window closes on April 15. "
        "If you make no changes your current elections roll over automatically.",
        folder_id="inbox", minutes_ago=400, is_read=True,
    ))

    messages.append(_msg(
        "New Confluence Page: Onboarding Checklist v3",
        "Jens Lorenz", "jens.lorenz@example.com",
        "I have published the updated onboarding checklist on Confluence. "
        "Please review and leave comments by Friday.",
        folder_id="inbox", minutes_ago=500, is_read=True,
    ))

    messages.append(_msg(
        "RE: Office Supplies Order",
        "Melanie Schreiber", "melanie.schreiber@example.com",
        "The monitors and keyboards have been ordered. "
        "Expected delivery next Wednesday.",
        folder_id="inbox", minutes_ago=600, is_read=True,
    ))

    # ── Sent Items ─────────────────────────────────────────────────

    messages.append(_msg(
        "RE: Sprint 24 Review Notes",
        "Mock User", "mock@example.com",
        "Thanks Lisa! Great sprint. I will groom my backlog items before Monday.",
        folder_id="sentitems", minutes_ago=80, is_read=True,
    ))

    messages.append(_msg(
        "RE: Architecture Review",
        "Mock User", "mock@example.com",
        "Klaus, I will have the migration guide draft ready by April 14.",
        folder_id="sentitems", minutes_ago=310, is_read=True,
    ))

    messages.append(_msg(
        "Vacation Request: April 20-24",
        "Mock User", "mock@example.com",
        "Hi Christine, I would like to take PTO from April 20 through April 24. "
        "My tasks will be covered by Stefan during that week.",
        folder_id="sentitems", minutes_ago=1440, is_read=True,
    ))

    # ── Drafts ─────────────────────────────────────────────────────

    messages.append(_msg(
        "RE: Customer Escalation - Acme Corp",
        "Mock User", "mock@example.com",
        "Anna, I investigated the 503 errors. Root cause is a misconfigured "
        "rate limiter threshold deployed in last night's release.",
        folder_id="drafts", is_draft=True,
    ))

    messages.append(_msg(
        "Proposal: Migrate CI to GitHub Actions",
        "Mock User", "mock@example.com",
        "Team, I have been evaluating GitHub Actions as a replacement for "
        "our current Jenkins setup. Key advantages...",
        folder_id="drafts", is_draft=True,
    ))

    # ── Deleted Items ──────────────────────────────────────────────

    messages.append(_msg(
        "Your LinkedIn invitation was accepted",
        "LinkedIn", "notifications@linkedin.com",
        "Thomas Keller accepted your invitation. You can now message each other.",
        folder_id="deleteditems", minutes_ago=2880, is_read=True,
    ))

    # ── Notifications sub-folder ───────────────────────────────────

    messages.append(_msg(
        "Jira: ENG-1060 moved to In Review",
        "Jira", "jira@example-jira.atlassian.net",
        "Tobias Neumann moved ENG-1060 (CI/CD staging pipeline) to In Review.",
        folder_id="inbox-notifications", minutes_ago=120, is_read=True,
    ))

    messages.append(_msg(
        "Jira: ENG-1063 unblocked",
        "Jira", "jira@example-jira.atlassian.net",
        "Stefan Hoffmann resolved the blocker on ENG-1063 (search indexing).",
        folder_id="inbox-notifications", minutes_ago=200, is_read=True,
    ))

    # ── Done sub-folder ────────────────────────────────────────────

    messages.append(_msg(
        "RE: Office WiFi Issues",
        "Bernd Vogel", "bernd.vogel@example.com",
        "The access point on floor 3 has been replaced. "
        "Please let me know if you still experience dropouts.",
        folder_id="inbox-done", minutes_ago=3000, is_read=True,
    ))

    return messages


# ---------------------------------------------------------------------------
# Calendar Events (~50+ spanning 2 months)
# ---------------------------------------------------------------------------

def default_calendar_events() -> list[dict]:
    """Return synthetic calendar events spanning the current and next month."""
    now = _now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    monday = today - timedelta(days=today.weekday())

    first_of_month = today.replace(day=1)
    if first_of_month.month <= 10:
        end_of_range = first_of_month.replace(month=first_of_month.month + 2, day=28)
    else:
        end_of_range = first_of_month.replace(
            year=first_of_month.year + 1,
            month=(first_of_month.month + 2 - 1) % 12 + 1,
            day=28,
        )

    def _event(
        subject: str,
        start: datetime,
        end: datetime,
        organizer_name: str = "Max Mustermann",
        organizer_email: str = "max.mustermann@example.com",
        is_all_day: bool = False,
        location: str = "",
        online_meeting_url: str = "",
        show_as: str = "busy",
        body_preview: str = "",
    ) -> dict:
        return {
            "id": _uid(),
            "subject": subject,
            "start": {"dateTime": _dt(start), "timeZone": "Europe/Berlin"},
            "end": {"dateTime": _dt(end), "timeZone": "Europe/Berlin"},
            "isAllDay": is_all_day,
            "organizer": {
                "emailAddress": {"name": organizer_name, "address": organizer_email},
            },
            "attendees": [
                {
                    "emailAddress": {"name": organizer_name, "address": organizer_email},
                    "status": {"response": "accepted"},
                    "type": "required",
                },
            ],
            "bodyPreview": body_preview,
            "location": {"displayName": location},
            "isOnlineMeeting": bool(online_meeting_url),
            "onlineMeeting": {"joinUrl": online_meeting_url} if online_meeting_url else None,
            "showAs": show_as,
            "responseStatus": {"response": "accepted"},
            "sensitivity": "normal",
            "importance": "normal",
        }

    def _iter_weekdays(target_weekday: int, start: datetime = first_of_month,
                       end: datetime = end_of_range):
        cur = start
        while cur.weekday() != target_weekday:
            cur += timedelta(days=1)
        while cur <= end:
            yield cur
            cur += timedelta(weeks=1)

    events: list[dict] = []

    # ── Recurring: Daily Standup Mon-Fri 9:00-9:30 ────────────────
    for wd in range(5):
        for day in _iter_weekdays(wd):
            events.append(_event(
                "Daily Standup",
                day.replace(hour=9, minute=0),
                day.replace(hour=9, minute=30),
                location="Microsoft Teams",
                online_meeting_url="https://teams.microsoft.com/l/meetup-join/standup",
                body_preview="Quick sync: yesterday, today, blockers.",
            ))

    # ── Weekly Team Meeting Wed 10:00-11:00 ───────────────────────
    for wed in _iter_weekdays(2):
        events.append(_event(
            "Weekly Team Meeting",
            wed.replace(hour=10, minute=0),
            wed.replace(hour=11, minute=0),
            organizer_name="Klaus Weber",
            organizer_email="klaus.weber@example.com",
            location="Conference Room A",
            body_preview="Status updates, blockers, milestones.",
        ))

    # ── Biweekly 1:1 with Manager Thu 14:00-14:30 ────────────────
    toggle = True
    for thu in _iter_weekdays(3):
        if toggle:
            events.append(_event(
                "1:1 with Manager",
                thu.replace(hour=14, minute=0),
                thu.replace(hour=14, minute=30),
                organizer_name="Klaus Weber",
                organizer_email="klaus.weber@example.com",
                body_preview="Career growth, sprint feedback.",
            ))
        toggle = not toggle

    # ── Monthly All-Hands (first Monday of each month) ────────────
    seen_months: set[tuple[int, int]] = set()
    for mon_day in _iter_weekdays(0):
        key = (mon_day.year, mon_day.month)
        if key not in seen_months and mon_day.day <= 7:
            seen_months.add(key)
            events.append(_event(
                "Monthly All-Hands",
                mon_day.replace(hour=15, minute=0),
                mon_day.replace(hour=16, minute=0),
                organizer_name="Heinrich Fischer",
                organizer_email="heinrich.fischer@example.com",
                location="Auditorium / Teams Live",
                body_preview="Company updates and Q&A.",
            ))

    # ── One-off events ────────────────────────────────────────────

    events.append(_event(
        "Project Alpha Design Review",
        (monday + timedelta(days=1)).replace(hour=14),
        (monday + timedelta(days=1)).replace(hour=15),
        organizer_name="Anna Schmidt",
        organizer_email="anna.schmidt@example.com",
        location="Meeting Room B",
        body_preview="Review wireframes and UX flow.",
    ))

    events.append(_event(
        "Customer Demo - Acme Corp",
        (monday + timedelta(days=2)).replace(hour=13),
        (monday + timedelta(days=2)).replace(hour=14),
        organizer_name="Petra Schneider",
        organizer_email="petra.schneider@example.com",
        show_as="tentative",
        body_preview="Product demo for Acme Corp.",
    ))

    events.append(_event(
        "Sprint Planning",
        monday.replace(hour=11),
        monday.replace(hour=12),
        organizer_name="Lisa Braun",
        organizer_email="lisa.braun@example.com",
        location="Innovation Lab",
        body_preview="Capacity, priorities, story pointing.",
    ))

    events.append(_event(
        "Sprint Retrospective",
        (monday + timedelta(weeks=1, days=4)).replace(hour=15),
        (monday + timedelta(weeks=1, days=4)).replace(hour=16),
        organizer_name="Lisa Braun",
        organizer_email="lisa.braun@example.com",
        location="Innovation Lab",
        body_preview="What went well, what can improve.",
    ))

    events.append(_event(
        "Cloud Architecture Workshop",
        (monday + timedelta(weeks=2, days=1)).replace(hour=9, minute=30),
        (monday + timedelta(weeks=2, days=1)).replace(hour=12),
        organizer_name="Petra Schneider",
        organizer_email="petra.schneider@example.com",
        location="Training Room 1",
        body_preview="Hands-on: migrating workloads to Azure.",
    ))

    events.append(_event(
        "Security Training",
        (monday + timedelta(weeks=3, days=2)).replace(hour=13),
        (monday + timedelta(weeks=3, days=2)).replace(hour=15),
        organizer_name="Klaus Weber",
        organizer_email="klaus.weber@example.com",
        location="Auditorium",
        body_preview="Mandatory annual security awareness.",
    ))

    events.append(_event(
        "Quarterly Business Review",
        (monday + timedelta(weeks=4, days=1)).replace(hour=10),
        (monday + timedelta(weeks=4, days=1)).replace(hour=12),
        organizer_name="Heinrich Fischer",
        organizer_email="heinrich.fischer@example.com",
        location="Executive Boardroom",
        body_preview="Key metrics, revenue targets, strategy.",
    ))

    events.append(_event(
        "Product Roadmap Alignment",
        (monday + timedelta(weeks=4, days=3)).replace(hour=15),
        (monday + timedelta(weeks=4, days=3)).replace(hour=16, minute=30),
        organizer_name="Anna Schmidt",
        organizer_email="anna.schmidt@example.com",
        location="Meeting Room A",
        body_preview="Engineering and product roadmap sync.",
    ))

    events.append(_event(
        "Innovation Hackathon Kickoff",
        (monday + timedelta(weeks=5, days=2)).replace(hour=9),
        (monday + timedelta(weeks=5, days=2)).replace(hour=10),
        organizer_name="Lisa Braun",
        organizer_email="lisa.braun@example.com",
        location="Innovation Lab",
        body_preview="Theme announcement and team formation.",
    ))

    # ── All-day events ────────────────────────────────────────────

    vacation_start = monday + timedelta(weeks=3)
    for d in range(5):
        vday = vacation_start + timedelta(days=d)
        events.append(_event(
            "Vacation",
            vday,
            vday + timedelta(days=1),
            is_all_day=True,
            show_as="oof",
            body_preview="Out of office.",
        ))

    next_friday = monday + timedelta(weeks=1, days=4)
    events.append(_event(
        "Company Holiday",
        next_friday,
        next_friday + timedelta(days=1),
        is_all_day=True,
        organizer_name="HR Department",
        organizer_email="hr@example.com",
        body_preview="Office closed.",
    ))

    offsite_day = monday + timedelta(weeks=5, days=3)
    events.append(_event(
        "Team Offsite",
        offsite_day,
        offsite_day + timedelta(days=2),
        is_all_day=True,
        organizer_name="Klaus Weber",
        organizer_email="klaus.weber@example.com",
        location="Riverside Conference Center",
        body_preview="Strategy, team building, workshops.",
    ))

    return events


# ---------------------------------------------------------------------------
# Company Directory (25 users)
# ---------------------------------------------------------------------------

def default_company_directory() -> list[dict]:
    """Return ~25 synthetic directory users with org hierarchy."""
    ceo_id = _uid()
    vp_tech_id = _uid()
    vp_sales_id = _uid()
    vp_hr_id = _uid()
    vp_finance_id = _uid()
    vp_marketing_id = _uid()
    dir_eng_id = _uid()
    dir_ops_id = _uid()

    def _user(
        uid: str,
        given: str,
        surname: str,
        email: str,
        title: str,
        dept: str,
        gender: str,
        manager_id: str | None = None,
        location: str = "Headquarters",
    ) -> dict:
        return {
            "id": uid,
            "displayName": f"{given} {surname}",
            "givenName": given,
            "surname": surname,
            "mail": email,
            "userPrincipalName": email,
            "jobTitle": title,
            "department": dept,
            "officeLocation": location,
            "mobilePhone": f"+49 170 {uid[:7].replace('-', '')}",
            "businessPhones": [f"+49 7123 {uid[:4].replace('-', '')}"],
            "accountEnabled": True,
            "manager": {"id": manager_id} if manager_id else None,
            "_gender": gender,
        }

    return [
        # Executive
        _user(ceo_id, "Heinrich", "Fischer", "heinrich.fischer@example.com",
              "CEO", "Executive Board", "male"),
        _user(vp_tech_id, "Klaus", "Weber", "klaus.weber@example.com",
              "VP Technology", "Engineering", "male", manager_id=ceo_id),
        _user(vp_sales_id, "Sabine", "Mueller", "sabine.mueller@example.com",
              "VP Sales", "Sales", "female", manager_id=ceo_id),
        _user(vp_hr_id, "Petra", "Schneider", "petra.schneider@example.com",
              "VP Human Resources", "HR", "female", manager_id=ceo_id),
        _user(vp_finance_id, "Werner", "Hartmann", "werner.hartmann@example.com",
              "VP Finance", "Finance", "male", manager_id=ceo_id),
        _user(vp_marketing_id, "Monika", "Krueger", "monika.krueger@example.com",
              "VP Marketing", "Marketing", "female", manager_id=ceo_id),

        # Directors
        _user(dir_eng_id, "Frank", "Zimmermann", "frank.zimmermann@example.com",
              "Director of Engineering", "Engineering", "male", manager_id=vp_tech_id),
        _user(dir_ops_id, "Claudia", "Lehmann", "claudia.lehmann@example.com",
              "Director of Operations", "Operations", "female", manager_id=vp_tech_id),

        # Engineering
        _user(_uid(), "Lisa", "Braun", "lisa.braun@example.com",
              "Scrum Master", "Engineering", "female", manager_id=dir_eng_id),
        _user(_uid(), "Max", "Mustermann", "max.mustermann@example.com",
              "Senior Software Engineer", "Engineering", "male", manager_id=dir_eng_id),
        _user(_uid(), "Thomas", "Keller", "thomas.keller@example.com",
              "Data Scientist", "Engineering", "male", manager_id=dir_eng_id),
        _user(_uid(), "Stefan", "Hoffmann", "stefan.hoffmann@example.com",
              "DevOps Engineer", "Engineering", "male", manager_id=dir_eng_id),
        _user(_uid(), "Katrin", "Schwarz", "katrin.schwarz@example.com",
              "UX Designer", "Engineering", "female", manager_id=dir_eng_id),
        _user(_uid(), "Tobias", "Neumann", "tobias.neumann@example.com",
              "Backend Developer", "Engineering", "male", manager_id=dir_eng_id),
        _user(_uid(), "Sandra", "Koch", "sandra.koch@example.com",
              "Frontend Developer", "Engineering", "female", manager_id=dir_eng_id),

        # Operations
        _user(_uid(), "Bernd", "Vogel", "bernd.vogel@example.com",
              "Systems Administrator", "Operations", "male", manager_id=dir_ops_id),
        _user(_uid(), "Melanie", "Schreiber", "melanie.schreiber@example.com",
              "IT Support Specialist", "Operations", "female", manager_id=dir_ops_id),

        # Sales
        _user(_uid(), "Anna", "Schmidt", "anna.schmidt@example.com",
              "Sales Manager", "Sales", "female", manager_id=vp_sales_id),
        _user(_uid(), "Julia", "Richter", "julia.richter@example.com",
              "Sales Representative", "Sales", "female", manager_id=vp_sales_id),
        _user(_uid(), "Markus", "Bauer", "markus.bauer@example.com",
              "Key Account Manager", "Sales", "male", manager_id=vp_sales_id,
              location="Stuttgart"),

        # HR
        _user(_uid(), "Christine", "Wagner", "christine.wagner@example.com",
              "HR Business Partner", "HR", "female", manager_id=vp_hr_id),
        _user(_uid(), "Jens", "Lorenz", "jens.lorenz@example.com",
              "Recruiter", "HR", "male", manager_id=vp_hr_id),

        # Finance
        _user(_uid(), "Anja", "Beyer", "anja.beyer@example.com",
              "Financial Controller", "Finance", "female", manager_id=vp_finance_id),
        _user(_uid(), "Ralf", "Seidel", "ralf.seidel@example.com",
              "Accountant", "Finance", "male", manager_id=vp_finance_id),

        # Marketing
        _user(_uid(), "Daniela", "Engel", "daniela.engel@example.com",
              "Marketing Manager", "Marketing", "female", manager_id=vp_marketing_id),
    ]


# ---------------------------------------------------------------------------
# Chat Conversations (~12 threads)
# ---------------------------------------------------------------------------

def default_chat_conversations() -> list[dict]:
    """Return ~12 synthetic chat threads (1:1, group, meeting)."""
    now = _now()

    def _chat_msg(
        sender_name: str,
        sender_email: str,
        content: str,
        minutes_ago: int,
        is_from_me: bool = False,
        reactions: list[dict] | None = None,
    ) -> dict:
        return {
            "id": _uid(),
            "senderName": sender_name,
            "senderEmail": sender_email,
            "content": content,
            "timestamp": (now - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "isFromMe": is_from_me,
            "reactions": reactions or [],
        }

    def _chat(
        topic: str | None,
        chat_type: str,
        members: list[dict],
        messages: list[dict],
        created_minutes_ago: int = 10000,
    ) -> dict:
        last = messages[0] if messages else None
        return {
            "id": _uid(),
            "topic": topic,
            "chatType": chat_type,
            "createdDateTime": (now - timedelta(minutes=created_minutes_ago)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "members": members,
            "lastMessage": {
                "content": last["content"] if last else "",
                "senderName": last["senderName"] if last else "",
                "timestamp": last["timestamp"] if last else "",
            } if last else None,
            "messages": messages,
        }

    me = {"displayName": "Mock User", "email": "mock@example.com"}

    # ── 1:1 Chats ────────────────────────────────────────────────
    chats: list[dict] = []

    # 1:1 with Anna Schmidt
    chats.append(_chat(
        topic=None,
        chat_type="oneOnOne",
        members=[me, {"displayName": "Anna Schmidt", "email": "anna.schmidt@example.com"}],
        messages=[
            _chat_msg("Anna Schmidt", "anna.schmidt@example.com",
                      "Acme hat gerade angerufen, die wollen morgen einen Call. Passt dir 10 Uhr?",
                      12),
            _chat_msg("Mock User", "mock@example.com",
                      "10 Uhr passt perfekt. Schick mir bitte die Agenda vorab.",
                      10, is_from_me=True),
            _chat_msg("Anna Schmidt", "anna.schmidt@example.com",
                      "Mach ich! Danke dir.", 8,
                      reactions=[{"emoji": "\U0001F44D", "count": 1}]),
            _chat_msg("Mock User", "mock@example.com",
                      "Hast du die Zahlen von Q1 schon zusammen?", 180, is_from_me=True),
            _chat_msg("Anna Schmidt", "anna.schmidt@example.com",
                      "Ja, schicke ich gleich per Mail.", 175),
            _chat_msg("Mock User", "mock@example.com",
                      "Super, danke!", 170, is_from_me=True),
        ],
        created_minutes_ago=50000,
    ))

    # 1:1 with Klaus Weber
    chats.append(_chat(
        topic=None,
        chat_type="oneOnOne",
        members=[me, {"displayName": "Klaus Weber", "email": "klaus.weber@example.com"}],
        messages=[
            _chat_msg("Klaus Weber", "klaus.weber@example.com",
                      "The architecture review went well. Let's finalize the ADR this week.", 45),
            _chat_msg("Mock User", "mock@example.com",
                      "Agreed. I'll draft the decision record today.", 40, is_from_me=True),
            _chat_msg("Klaus Weber", "klaus.weber@example.com",
                      "Perfect. Tag me for review once it's ready.", 38,
                      reactions=[{"emoji": "\U0001F64F", "count": 1}]),
            _chat_msg("Mock User", "mock@example.com",
                      "Will do. Also, should we invite Petra to the next meeting?", 35,
                      is_from_me=True),
            _chat_msg("Klaus Weber", "klaus.weber@example.com",
                      "Good idea. She had useful input on the infrastructure side.", 30),
            _chat_msg("Mock User", "mock@example.com",
                      "I'll add her to the invite.", 28, is_from_me=True),
            _chat_msg("Klaus Weber", "klaus.weber@example.com",
                      "\U0001F44D", 25),
        ],
        created_minutes_ago=80000,
    ))

    # 1:1 with Lisa Braun
    chats.append(_chat(
        topic=None,
        chat_type="oneOnOne",
        members=[me, {"displayName": "Lisa Braun", "email": "lisa.braun@example.com"}],
        messages=[
            _chat_msg("Lisa Braun", "lisa.braun@example.com",
                      "Sprint 25 planning is confirmed for Monday 10:00.", 120),
            _chat_msg("Mock User", "mock@example.com",
                      "Got it. I'll have my backlog groomed by then.", 115, is_from_me=True),
            _chat_msg("Lisa Braun", "lisa.braun@example.com",
                      "Great! Don't forget the carry-over items from Sprint 24.", 110),
            _chat_msg("Mock User", "mock@example.com",
                      "Already on my list. The CI/CD staging task is almost done.", 105,
                      is_from_me=True),
            _chat_msg("Lisa Braun", "lisa.braun@example.com",
                      "Awesome, that was the biggest carry-over. Thanks!", 100,
                      reactions=[{"emoji": "\U0001F389", "count": 2}]),
        ],
        created_minutes_ago=60000,
    ))

    # 1:1 with Max Mustermann
    chats.append(_chat(
        topic=None,
        chat_type="oneOnOne",
        members=[me, {"displayName": "Max Mustermann", "email": "max.mustermann@example.com"}],
        messages=[
            _chat_msg("Max Mustermann", "max.mustermann@example.com",
                      "Hey, can you review my PR #347? It fixes the rate limiter overflow.", 200),
            _chat_msg("Mock User", "mock@example.com",
                      "Sure, I'll take a look after lunch.", 195, is_from_me=True),
            _chat_msg("Max Mustermann", "max.mustermann@example.com",
                      "Thanks! The main change is in bucket.py.", 190),
            _chat_msg("Mock User", "mock@example.com",
                      "Reviewed and approved. Nice fix!", 60, is_from_me=True,
                      reactions=[{"emoji": "\U0001F680", "count": 1}]),
            _chat_msg("Max Mustermann", "max.mustermann@example.com",
                      "Merged! Thanks for the quick turnaround.", 55),
        ],
        created_minutes_ago=40000,
    ))

    # 1:1 with Tobias Neumann
    chats.append(_chat(
        topic=None,
        chat_type="oneOnOne",
        members=[me, {"displayName": "Tobias Neumann", "email": "tobias.neumann@example.com"}],
        messages=[
            _chat_msg("Tobias Neumann", "tobias.neumann@example.com",
                      "Die staging pipeline l\u00e4uft jetzt durch. Alle Tests gr\u00fcn.", 300),
            _chat_msg("Mock User", "mock@example.com",
                      "Super! Hast du auch die Integration-Tests gecheckt?", 295, is_from_me=True),
            _chat_msg("Tobias Neumann", "tobias.neumann@example.com",
                      "Ja, alles sauber. Ich merge das heute Abend.", 290),
            _chat_msg("Mock User", "mock@example.com",
                      "Top, danke Tobias!", 285, is_from_me=True,
                      reactions=[{"emoji": "\U0001F44D", "count": 1}]),
            _chat_msg("Tobias Neumann", "tobias.neumann@example.com",
                      "Kein Ding \U0001F60E", 280),
        ],
        created_minutes_ago=30000,
    ))

    # 1:1 with Stefan Hoffmann
    chats.append(_chat(
        topic=None,
        chat_type="oneOnOne",
        members=[me, {"displayName": "Stefan Hoffmann", "email": "stefan.hoffmann@example.com"}],
        messages=[
            _chat_msg("Stefan Hoffmann", "stefan.hoffmann@example.com",
                      "I unblocked ENG-1063. The search indexer was hitting a timeout.", 400),
            _chat_msg("Mock User", "mock@example.com",
                      "Nice catch. What was the root cause?", 395, is_from_me=True),
            _chat_msg("Stefan Hoffmann", "stefan.hoffmann@example.com",
                      "Connection pool was exhausted. Bumped the limit and added retry logic.", 390),
            _chat_msg("Mock User", "mock@example.com",
                      "Good fix. We should add a metric for pool utilization.", 385,
                      is_from_me=True),
            _chat_msg("Stefan Hoffmann", "stefan.hoffmann@example.com",
                      "Already on it. I'll push the Grafana dashboard update tomorrow.", 380,
                      reactions=[{"emoji": "\U0001F4AA", "count": 2}]),
        ],
        created_minutes_ago=45000,
    ))

    # ── Group Chats ──────────────────────────────────────────────

    # Project Alpha
    chats.append(_chat(
        topic="Project Alpha",
        chat_type="group",
        members=[
            me,
            {"displayName": "Anna Schmidt", "email": "anna.schmidt@example.com"},
            {"displayName": "Katrin Schwarz", "email": "katrin.schwarz@example.com"},
            {"displayName": "Sandra Koch", "email": "sandra.koch@example.com"},
            {"displayName": "Max Mustermann", "email": "max.mustermann@example.com"},
        ],
        messages=[
            _chat_msg("Katrin Schwarz", "katrin.schwarz@example.com",
                      "Wireframes sind fertig. Feedback bitte bis Freitag.", 20),
            _chat_msg("Sandra Koch", "sandra.koch@example.com",
                      "Sieht super aus! Ich fange Montag mit der Implementierung an.", 18,
                      reactions=[{"emoji": "\U0001F525", "count": 3}]),
            _chat_msg("Mock User", "mock@example.com",
                      "Great work Katrin! I'll review the API contracts this afternoon.", 15,
                      is_from_me=True),
            _chat_msg("Max Mustermann", "max.mustermann@example.com",
                      "I can pair with Sandra on the frontend components.", 13),
            _chat_msg("Anna Schmidt", "anna.schmidt@example.com",
                      "Perfect. Let's sync in tomorrow's standup.", 10),
            _chat_msg("Mock User", "mock@example.com",
                      "Sounds good. I'll prepare the endpoint specs.", 8, is_from_me=True),
            _chat_msg("Katrin Schwarz", "katrin.schwarz@example.com",
                      "I also uploaded the design system tokens to Figma.", 5),
            _chat_msg("Sandra Koch", "sandra.koch@example.com",
                      "\U0001F64C danke!", 3),
        ],
        created_minutes_ago=100000,
    ))

    # Lunch Group
    chats.append(_chat(
        topic="Lunch Group",
        chat_type="group",
        members=[
            me,
            {"displayName": "Lisa Braun", "email": "lisa.braun@example.com"},
            {"displayName": "Tobias Neumann", "email": "tobias.neumann@example.com"},
            {"displayName": "Sandra Koch", "email": "sandra.koch@example.com"},
            {"displayName": "Bernd Vogel", "email": "bernd.vogel@example.com"},
        ],
        messages=[
            _chat_msg("Lisa Braun", "lisa.braun@example.com",
                      "Heute Mensa oder Italiener?", 65),
            _chat_msg("Tobias Neumann", "tobias.neumann@example.com",
                      "Italiener! Die haben neue Pizza-Sorten \U0001F355", 63),
            _chat_msg("Sandra Koch", "sandra.koch@example.com",
                      "Bin dabei. 12:15?", 60),
            _chat_msg("Mock User", "mock@example.com",
                      "Klingt gut, ich komme mit!", 58, is_from_me=True),
            _chat_msg("Bernd Vogel", "bernd.vogel@example.com",
                      "Muss leider passen, hab ein Meeting bis 13:00 \U0001F622", 55),
            _chat_msg("Lisa Braun", "lisa.braun@example.com",
                      "Schade Bernd! Dann morgen?", 53),
            _chat_msg("Bernd Vogel", "bernd.vogel@example.com",
                      "Morgen bin ich dabei \U0001F44D", 50),
        ],
        created_minutes_ago=200000,
    ))

    # Sprint Team
    chats.append(_chat(
        topic="Sprint Team",
        chat_type="group",
        members=[
            me,
            {"displayName": "Lisa Braun", "email": "lisa.braun@example.com"},
            {"displayName": "Max Mustermann", "email": "max.mustermann@example.com"},
            {"displayName": "Tobias Neumann", "email": "tobias.neumann@example.com"},
            {"displayName": "Stefan Hoffmann", "email": "stefan.hoffmann@example.com"},
            {"displayName": "Sandra Koch", "email": "sandra.koch@example.com"},
        ],
        messages=[
            _chat_msg("Lisa Braun", "lisa.braun@example.com",
                      "Sprint 24 velocity: 42 points. Best sprint this quarter!", 500),
            _chat_msg("Max Mustermann", "max.mustermann@example.com",
                      "Nice! The rate limiter fix alone was 8 points.", 495,
                      reactions=[{"emoji": "\U0001F389", "count": 4}]),
            _chat_msg("Mock User", "mock@example.com",
                      "Great teamwork everyone. Let's keep the momentum.", 490, is_from_me=True),
            _chat_msg("Stefan Hoffmann", "stefan.hoffmann@example.com",
                      "The unblocked items helped a lot. Less context switching.", 485),
            _chat_msg("Tobias Neumann", "tobias.neumann@example.com",
                      "Agreed. The CI pipeline improvements saved us hours.", 480),
            _chat_msg("Sandra Koch", "sandra.koch@example.com",
                      "Frontend velocity was up too. The component library paid off.", 475),
            _chat_msg("Lisa Braun", "lisa.braun@example.com",
                      "I'll share the full report in Monday's planning. Have a great weekend!", 470,
                      reactions=[{"emoji": "\U0001F389", "count": 3}, {"emoji": "\U0001F680", "count": 2}]),
        ],
        created_minutes_ago=150000,
    ))

    # ── Meeting Chats ────────────────────────────────────────────

    # Daily Standup
    chats.append(_chat(
        topic="Daily Standup",
        chat_type="meeting",
        members=[
            me,
            {"displayName": "Lisa Braun", "email": "lisa.braun@example.com"},
            {"displayName": "Max Mustermann", "email": "max.mustermann@example.com"},
            {"displayName": "Tobias Neumann", "email": "tobias.neumann@example.com"},
            {"displayName": "Stefan Hoffmann", "email": "stefan.hoffmann@example.com"},
            {"displayName": "Sandra Koch", "email": "sandra.koch@example.com"},
            {"displayName": "Katrin Schwarz", "email": "katrin.schwarz@example.com"},
        ],
        messages=[
            _chat_msg("Lisa Braun", "lisa.braun@example.com",
                      "Good morning! Let's start. Updates from yesterday?", 130),
            _chat_msg("Max Mustermann", "max.mustermann@example.com",
                      "Finished the PR for rate limiter. Starting on caching layer today.", 128),
            _chat_msg("Tobias Neumann", "tobias.neumann@example.com",
                      "Staging pipeline is green. Moving to the monitoring dashboard.", 126),
            _chat_msg("Mock User", "mock@example.com",
                      "Worked on the API contracts for Project Alpha. No blockers.", 124,
                      is_from_me=True),
            _chat_msg("Sandra Koch", "sandra.koch@example.com",
                      "Implementing the new sidebar component. Need design tokens from Katrin.", 122),
            _chat_msg("Katrin Schwarz", "katrin.schwarz@example.com",
                      "I'll send them right after standup!", 120),
            _chat_msg("Stefan Hoffmann", "stefan.hoffmann@example.com",
                      "Deployed the connection pool fix to staging. Monitoring for issues.", 118),
            _chat_msg("Lisa Braun", "lisa.braun@example.com",
                      "Great updates everyone. No blockers - keep up the good work!", 115,
                      reactions=[{"emoji": "\U0001F4AA", "count": 3}]),
        ],
        created_minutes_ago=300000,
    ))

    # Weekly Team Meeting
    chats.append(_chat(
        topic="Weekly Team Meeting",
        chat_type="meeting",
        members=[
            me,
            {"displayName": "Klaus Weber", "email": "klaus.weber@example.com"},
            {"displayName": "Lisa Braun", "email": "lisa.braun@example.com"},
            {"displayName": "Frank Zimmermann", "email": "frank.zimmermann@example.com"},
            {"displayName": "Max Mustermann", "email": "max.mustermann@example.com"},
        ],
        messages=[
            _chat_msg("Klaus Weber", "klaus.weber@example.com",
                      "Welcome everyone. First topic: Q2 OKRs.", 1500),
            _chat_msg("Frank Zimmermann", "frank.zimmermann@example.com",
                      "Engineering OKR draft is ready. Key result: reduce P1 incidents by 30%.", 1495),
            _chat_msg("Lisa Braun", "lisa.braun@example.com",
                      "Sprint metrics support this. We've already reduced incident response time.", 1490),
            _chat_msg("Mock User", "mock@example.com",
                      "I think we should add an OKR around developer experience too.", 1485,
                      is_from_me=True),
            _chat_msg("Klaus Weber", "klaus.weber@example.com",
                      "Good point. Can you draft that and share it by Thursday?", 1480),
            _chat_msg("Mock User", "mock@example.com",
                      "Will do.", 1475, is_from_me=True),
            _chat_msg("Frank Zimmermann", "frank.zimmermann@example.com",
                      "Also, the cloud migration timeline needs an update. Petra has the latest.", 1470),
            _chat_msg("Klaus Weber", "klaus.weber@example.com",
                      "I'll follow up with Petra. Next topic: hiring pipeline.", 1465),
            _chat_msg("Klaus Weber", "klaus.weber@example.com",
                      "We have 3 senior engineer candidates in final rounds. Decisions next week.", 1460),
            _chat_msg("Lisa Braun", "lisa.braun@example.com",
                      "Fingers crossed! We need the help for Q2.", 1455,
                      reactions=[{"emoji": "\U0001F91E", "count": 4}]),
        ],
        created_minutes_ago=400000,
    ))

    return chats


# ---------------------------------------------------------------------------
# Teams & Channels (4 teams)
# ---------------------------------------------------------------------------

def default_teams_channels() -> list[dict]:
    """Return 4 synthetic teams with 2-3 channels each, including messages."""
    now = _now()

    def _ch_msg(
        sender_name: str,
        sender_email: str,
        content: str,
        minutes_ago: int,
        reactions: list[dict] | None = None,
        replies: int = 0,
    ) -> dict:
        return {
            "id": _uid(),
            "senderName": sender_name,
            "senderEmail": sender_email,
            "content": content,
            "timestamp": (now - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "reactions": reactions or [],
            "replies": replies,
        }

    return [
        # ── Data & AI ────────────────────────────────────────────
        {
            "id": "team-data-ai",
            "displayName": "Data & AI",
            "channels": [
                {"id": "ch-dai-general", "displayName": "General",
                 "lastActivity": (now - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")},
                {"id": "ch-dai-devtalk", "displayName": "DevTalk",
                 "lastActivity": (now - timedelta(minutes=90)).strftime("%Y-%m-%dT%H:%M:%SZ")},
                {"id": "ch-dai-papers", "displayName": "Papers & Research",
                 "lastActivity": (now - timedelta(minutes=200)).strftime("%Y-%m-%dT%H:%M:%SZ")},
            ],
            "messages": {
                "ch-dai-general": [
                    _ch_msg("Thomas Keller", "thomas.keller@example.com",
                            "New model deployed to staging. Accuracy improved by 4.2%.", 30,
                            reactions=[{"emoji": "\U0001F389", "count": 5}], replies=3),
                    _ch_msg("Mock User", "mock@example.com",
                            "Great results! What was the main driver?", 28, replies=1),
                    _ch_msg("Thomas Keller", "thomas.keller@example.com",
                            "Feature engineering on the temporal signals. Full write-up in Confluence.", 25),
                    _ch_msg("Frank Zimmermann", "frank.zimmermann@example.com",
                            "Reminder: Data governance review is next Tuesday.", 180, replies=2),
                    _ch_msg("Thomas Keller", "thomas.keller@example.com",
                            "I'll prepare the data lineage report for the review.", 175),
                    _ch_msg("Mock User", "mock@example.com",
                            "Can we also discuss the new privacy requirements?", 170),
                    _ch_msg("Frank Zimmermann", "frank.zimmermann@example.com",
                            "Yes, that's on the agenda. Good thinking.", 165,
                            reactions=[{"emoji": "\U0001F44D", "count": 2}]),
                    _ch_msg("Thomas Keller", "thomas.keller@example.com",
                            "Training pipeline updated to v3.2. Release notes in #devtalk.", 400,
                            replies=4),
                    _ch_msg("Mock User", "mock@example.com",
                            "Nice. Does this include the batch processing improvements?", 395),
                    _ch_msg("Thomas Keller", "thomas.keller@example.com",
                            "Yes, batch throughput is up 60%.", 390,
                            reactions=[{"emoji": "\U0001F680", "count": 3}]),
                ],
                "ch-dai-devtalk": [
                    _ch_msg("Thomas Keller", "thomas.keller@example.com",
                            "Anyone tried the new PyTorch 2.3 compile mode?", 90, replies=5),
                    _ch_msg("Mock User", "mock@example.com",
                            "Not yet, but the benchmark results look promising.", 85),
                    _ch_msg("Thomas Keller", "thomas.keller@example.com",
                            "I ran some tests. 2x speedup on our transformer pipeline.", 80,
                            reactions=[{"emoji": "\U0001F525", "count": 4}]),
                    _ch_msg("Stefan Hoffmann", "stefan.hoffmann@example.com",
                            "Docker image for GPU workers updated. CUDA 12.4 now.", 500,
                            replies=2),
                    _ch_msg("Thomas Keller", "thomas.keller@example.com",
                            "Thanks Stefan! That was blocking our experiments.", 495),
                    _ch_msg("Mock User", "mock@example.com",
                            "Quick question: are we standardizing on Python 3.12 now?", 600),
                    _ch_msg("Frank Zimmermann", "frank.zimmermann@example.com",
                            "Yes, 3.12 is the target. Migration guide in Confluence.", 595,
                            reactions=[{"emoji": "\U0001F44D", "count": 3}]),
                    _ch_msg("Thomas Keller", "thomas.keller@example.com",
                            "New experiment tracking dashboard is live: grafana.internal/ml-experiments", 800,
                            replies=6),
                    _ch_msg("Mock User", "mock@example.com",
                            "Looks great! Can we add GPU utilization metrics?", 795),
                    _ch_msg("Thomas Keller", "thomas.keller@example.com",
                            "Already on the roadmap for next sprint.", 790),
                ],
                "ch-dai-papers": [
                    _ch_msg("Thomas Keller", "thomas.keller@example.com",
                            "Interesting paper: 'Scaling Laws for Neural Language Models'. Worth reading for our capacity planning.", 200,
                            reactions=[{"emoji": "\U0001F4DA", "count": 3}], replies=4),
                    _ch_msg("Mock User", "mock@example.com",
                            "Added to my reading list. The scaling predictions are fascinating.", 195),
                    _ch_msg("Thomas Keller", "thomas.keller@example.com",
                            "Also check out 'Efficient Transformers: A Survey'. Very relevant for our inference optimization.", 1000,
                            replies=2),
                    _ch_msg("Frank Zimmermann", "frank.zimmermann@example.com",
                            "Good finds. Let's do a paper reading session next Friday?", 995),
                    _ch_msg("Thomas Keller", "thomas.keller@example.com",
                            "Great idea! I'll set up a recurring slot.", 990,
                            reactions=[{"emoji": "\U0001F44D", "count": 4}]),
                ],
            },
        },

        # ── Engineering ──────────────────────────────────────────
        {
            "id": "team-engineering",
            "displayName": "Engineering",
            "channels": [
                {"id": "ch-eng-general", "displayName": "General",
                 "lastActivity": (now - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ")},
                {"id": "ch-eng-incidents", "displayName": "Incidents",
                 "lastActivity": (now - timedelta(minutes=60)).strftime("%Y-%m-%dT%H:%M:%SZ")},
                {"id": "ch-eng-releases", "displayName": "Releases",
                 "lastActivity": (now - timedelta(minutes=150)).strftime("%Y-%m-%dT%H:%M:%SZ")},
            ],
            "messages": {
                "ch-eng-general": [
                    _ch_msg("Frank Zimmermann", "frank.zimmermann@example.com",
                            "Team, we're adopting ADRs (Architecture Decision Records) starting this week.", 15,
                            reactions=[{"emoji": "\U0001F44D", "count": 6}], replies=8),
                    _ch_msg("Mock User", "mock@example.com",
                            "Great initiative! Template is in the wiki?", 12),
                    _ch_msg("Frank Zimmermann", "frank.zimmermann@example.com",
                            "Yes, Confluence > Engineering > ADR Template. First one is on event-driven architecture.", 10),
                    _ch_msg("Max Mustermann", "max.mustermann@example.com",
                            "Coding standards doc updated with Go and Rust sections.", 300,
                            replies=5),
                    _ch_msg("Lisa Braun", "lisa.braun@example.com",
                            "Reminder: Tech debt budget is 20% of sprint capacity.", 400),
                    _ch_msg("Sandra Koch", "sandra.koch@example.com",
                            "Component library v2.1 released. Check the changelog.", 450,
                            reactions=[{"emoji": "\U0001F389", "count": 4}], replies=3),
                    _ch_msg("Mock User", "mock@example.com",
                            "The new table component is much better. Thanks Sandra!", 445),
                    _ch_msg("Stefan Hoffmann", "stefan.hoffmann@example.com",
                            "CI build times reduced by 35% after the caching improvements.", 600,
                            reactions=[{"emoji": "\U0001F680", "count": 5}], replies=7),
                    _ch_msg("Tobias Neumann", "tobias.neumann@example.com",
                            "Nice! That saves us almost 10 minutes per pipeline run.", 595),
                    _ch_msg("Frank Zimmermann", "frank.zimmermann@example.com",
                            "Excellent work Stefan. Let's document the approach.", 590),
                    _ch_msg("Klaus Weber", "klaus.weber@example.com",
                            "Q2 engineering OKRs are published. Please review and comment.", 800,
                            replies=12),
                ],
                "ch-eng-incidents": [
                    _ch_msg("Stefan Hoffmann", "stefan.hoffmann@example.com",
                            "\U0001F6A8 P1: API gateway returning 503 for /orders endpoint. Investigating.", 60,
                            reactions=[{"emoji": "\U0001F440", "count": 5}], replies=15),
                    _ch_msg("Mock User", "mock@example.com",
                            "I see it too. Affects Acme Corp integration.", 58),
                    _ch_msg("Stefan Hoffmann", "stefan.hoffmann@example.com",
                            "Root cause: rate limiter config deployed with wrong threshold. Rolling back.", 50,
                            replies=3),
                    _ch_msg("Stefan Hoffmann", "stefan.hoffmann@example.com",
                            "\u2705 Resolved. Rollback complete. Orders flowing again.", 40,
                            reactions=[{"emoji": "\U0001F64F", "count": 7}]),
                    _ch_msg("Frank Zimmermann", "frank.zimmermann@example.com",
                            "Post-mortem scheduled for Thursday 14:00. Please prepare your timeline.", 35,
                            replies=4),
                    _ch_msg("Mock User", "mock@example.com",
                            "I'll have the logs and metrics ready for the review.", 33),
                    _ch_msg("Tobias Neumann", "tobias.neumann@example.com",
                            "\u26a0\ufe0f P2: Search indexer lag increased to 45 minutes. Normal is <5 min.", 2000,
                            replies=8),
                    _ch_msg("Stefan Hoffmann", "stefan.hoffmann@example.com",
                            "Connection pool exhaustion. Fix deployed. Back to normal.", 1900,
                            reactions=[{"emoji": "\U0001F44D", "count": 4}]),
                    _ch_msg("Frank Zimmermann", "frank.zimmermann@example.com",
                            "Monthly incident report: 2 P1s, 3 P2s. Down from 4 P1s last month.", 3000,
                            reactions=[{"emoji": "\U0001F4C9", "count": 3}], replies=6),
                    _ch_msg("Klaus Weber", "klaus.weber@example.com",
                            "Good trend. Let's keep pushing for zero P1s.", 2995),
                ],
                "ch-eng-releases": [
                    _ch_msg("Tobias Neumann", "tobias.neumann@example.com",
                            "\U0001F4E6 api-gateway v2.14.0 deployed to production. Release notes: ...", 150,
                            reactions=[{"emoji": "\U0001F680", "count": 6}], replies=4),
                    _ch_msg("Mock User", "mock@example.com",
                            "Monitoring dashboards look clean. No errors after 30 min.", 120),
                    _ch_msg("Stefan Hoffmann", "stefan.hoffmann@example.com",
                            "Confirmed. All health checks passing.", 115),
                    _ch_msg("Sandra Koch", "sandra.koch@example.com",
                            "\U0001F4E6 frontend-app v3.8.0 deployed. New sidebar and search.", 800,
                            reactions=[{"emoji": "\U0001F389", "count": 5}], replies=9),
                    _ch_msg("Max Mustermann", "max.mustermann@example.com",
                            "\U0001F4E6 auth-service v1.12.0 deployed. Includes MFA improvements.", 2000,
                            replies=3),
                    _ch_msg("Tobias Neumann", "tobias.neumann@example.com",
                            "Release schedule updated for Q2. Bi-weekly releases on Thursdays.", 3000,
                            reactions=[{"emoji": "\U0001F44D", "count": 4}]),
                    _ch_msg("Frank Zimmermann", "frank.zimmermann@example.com",
                            "Feature freeze for v3.0 is April 25. Plan accordingly.", 3500,
                            replies=10),
                ],
            },
        },

        # ── Company General ──────────────────────────────────────
        {
            "id": "team-company",
            "displayName": "Company General",
            "channels": [
                {"id": "ch-co-general", "displayName": "General",
                 "lastActivity": (now - timedelta(minutes=45)).strftime("%Y-%m-%dT%H:%M:%SZ")},
                {"id": "ch-co-random", "displayName": "Random",
                 "lastActivity": (now - timedelta(minutes=75)).strftime("%Y-%m-%dT%H:%M:%SZ")},
            ],
            "messages": {
                "ch-co-general": [
                    _ch_msg("Heinrich Fischer", "heinrich.fischer@example.com",
                            "Great Q1 results everyone! Revenue up 18% YoY. Full report in the all-hands deck.", 45,
                            reactions=[{"emoji": "\U0001F389", "count": 15}, {"emoji": "\U0001F680", "count": 8}],
                            replies=20),
                    _ch_msg("Petra Schneider", "petra.schneider@example.com",
                            "Reminder: Benefits enrollment closes April 15. Don't miss it!", 200,
                            reactions=[{"emoji": "\U0001F44D", "count": 6}], replies=5),
                    _ch_msg("Christine Wagner", "christine.wagner@example.com",
                            "Welcome our new team members: Maria from Engineering and Paul from Sales! \U0001F31F", 500,
                            reactions=[{"emoji": "\U0001F44B", "count": 12}, {"emoji": "\U0001F389", "count": 8}],
                            replies=15),
                    _ch_msg("Jens Lorenz", "jens.lorenz@example.com",
                            "Updated onboarding checklist is live on Confluence. Feedback welcome.", 800,
                            replies=3),
                    _ch_msg("Heinrich Fischer", "heinrich.fischer@example.com",
                            "Company hackathon dates confirmed: May 15-16. Theme TBA.", 1200,
                            reactions=[{"emoji": "\U0001F525", "count": 10}], replies=18),
                    _ch_msg("Monika Krueger", "monika.krueger@example.com",
                            "New brand guidelines published. Please use the updated logo and colors.", 2000,
                            reactions=[{"emoji": "\U0001F3A8", "count": 4}], replies=6),
                    _ch_msg("Werner Hartmann", "werner.hartmann@example.com",
                            "Travel expense policy updated. New limits effective May 1.", 3000,
                            replies=8),
                    _ch_msg("Petra Schneider", "petra.schneider@example.com",
                            "Office renovation on floor 2 starts next week. Temp seating assigned.", 4000,
                            reactions=[{"emoji": "\U0001F6E0\ufe0f", "count": 3}], replies=11),
                    _ch_msg("Heinrich Fischer", "heinrich.fischer@example.com",
                            "Congratulations to the Engineering team for winning the innovation award! \U0001F3C6", 5000,
                            reactions=[{"emoji": "\U0001F3C6", "count": 18}, {"emoji": "\U0001F44F", "count": 12}],
                            replies=25),
                    _ch_msg("Claudia Lehmann", "claudia.lehmann@example.com",
                            "IT maintenance window: Saturday 2:00-6:00 AM. Brief email outage expected.", 6000,
                            reactions=[{"emoji": "\U0001F44D", "count": 5}], replies=2),
                ],
                "ch-co-random": [
                    _ch_msg("Lisa Braun", "lisa.braun@example.com",
                            "Anyone up for table tennis after lunch? \U0001F3D3", 75,
                            reactions=[{"emoji": "\U0001F3D3", "count": 4}], replies=6),
                    _ch_msg("Tobias Neumann", "tobias.neumann@example.com",
                            "Found an amazing coffee place near the office: Kaffee Kontor. Highly recommend!", 300,
                            reactions=[{"emoji": "\u2615", "count": 7}], replies=8),
                    _ch_msg("Sandra Koch", "sandra.koch@example.com",
                            "Office plant update: the monstera is thriving! \U0001F33F", 600,
                            reactions=[{"emoji": "\U0001F33F", "count": 9}], replies=5),
                    _ch_msg("Bernd Vogel", "bernd.vogel@example.com",
                            "Lost and found: someone left a blue umbrella in meeting room B.", 1000),
                    _ch_msg("Mock User", "mock@example.com",
                            "That's mine! Thanks Bernd, I'll pick it up.", 995),
                    _ch_msg("Markus Bauer", "markus.bauer@example.com",
                            "Wer hat Lust auf Feierabend-Bier am Freitag? \U0001F37B", 1500,
                            reactions=[{"emoji": "\U0001F37B", "count": 8}], replies=12),
                    _ch_msg("Julia Richter", "julia.richter@example.com",
                            "Book recommendation: 'Staff Engineer' by Will Larson. Really good!", 2000,
                            reactions=[{"emoji": "\U0001F4DA", "count": 5}], replies=4),
                    _ch_msg("Katrin Schwarz", "katrin.schwarz@example.com",
                            "Design tip of the week: use consistent spacing tokens. Your UIs will thank you.", 3000,
                            reactions=[{"emoji": "\U0001F44D", "count": 6}], replies=3),
                ],
            },
        },

        # ── Sales & Marketing ────────────────────────────────────
        {
            "id": "team-sales-marketing",
            "displayName": "Sales & Marketing",
            "channels": [
                {"id": "ch-sm-general", "displayName": "General",
                 "lastActivity": (now - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")},
                {"id": "ch-sm-deals", "displayName": "Deal Updates",
                 "lastActivity": (now - timedelta(minutes=100)).strftime("%Y-%m-%dT%H:%M:%SZ")},
            ],
            "messages": {
                "ch-sm-general": [
                    _ch_msg("Sabine Mueller", "sabine.mueller@example.com",
                            "Q1 pipeline review: 2.3M in qualified opportunities. Great work team!", 20,
                            reactions=[{"emoji": "\U0001F4B0", "count": 6}], replies=8),
                    _ch_msg("Anna Schmidt", "anna.schmidt@example.com",
                            "New sales deck is ready. Updated competitive positioning and case studies.", 200,
                            reactions=[{"emoji": "\U0001F44D", "count": 4}], replies=5),
                    _ch_msg("Monika Krueger", "monika.krueger@example.com",
                            "Campaign results: 45% open rate on the product launch email. Above benchmark!", 400,
                            reactions=[{"emoji": "\U0001F4C8", "count": 5}], replies=3),
                    _ch_msg("Markus Bauer", "markus.bauer@example.com",
                            "Heading to the Stuttgart trade fair next week. Anyone want to join?", 600,
                            replies=4),
                    _ch_msg("Julia Richter", "julia.richter@example.com",
                            "Customer satisfaction survey results are in: NPS 72! Up from 65.", 800,
                            reactions=[{"emoji": "\U0001F389", "count": 7}], replies=6),
                    _ch_msg("Sabine Mueller", "sabine.mueller@example.com",
                            "New CRM dashboard is live. Check the pipeline view.", 1000,
                            replies=3),
                    _ch_msg("Daniela Engel", "daniela.engel@example.com",
                            "Blog post about our AI features published. Please share on LinkedIn!", 1200,
                            reactions=[{"emoji": "\U0001F680", "count": 4}], replies=5),
                    _ch_msg("Anna Schmidt", "anna.schmidt@example.com",
                            "Acme Corp demo went great. They want a POC starting next month.", 1500,
                            reactions=[{"emoji": "\U0001F525", "count": 6}], replies=9),
                    _ch_msg("Monika Krueger", "monika.krueger@example.com",
                            "Webinar registration: 230 sign-ups so far. Target was 200!", 2000,
                            reactions=[{"emoji": "\U0001F389", "count": 5}], replies=4),
                    _ch_msg("Sabine Mueller", "sabine.mueller@example.com",
                            "Sales kickoff agenda finalized. Two-day event in May.", 2500,
                            replies=7),
                ],
                "ch-sm-deals": [
                    _ch_msg("Anna Schmidt", "anna.schmidt@example.com",
                            "\U0001F31F Deal update: Acme Corp - moved to Negotiation stage. Value: 450K EUR.", 100,
                            reactions=[{"emoji": "\U0001F4B0", "count": 5}], replies=7),
                    _ch_msg("Markus Bauer", "markus.bauer@example.com",
                            "\U0001F31F Deal update: TechStart GmbH - Closed Won! 120K EUR annual.", 300,
                            reactions=[{"emoji": "\U0001F389", "count": 8}, {"emoji": "\U0001F4B0", "count": 4}],
                            replies=12),
                    _ch_msg("Julia Richter", "julia.richter@example.com",
                            "New lead from the webinar: DataFlow Inc. Scheduling intro call.", 500,
                            replies=3),
                    _ch_msg("Anna Schmidt", "anna.schmidt@example.com",
                            "\U0001F31F Deal update: GlobalTech - POC extended by 2 weeks. Good sign.", 800,
                            reactions=[{"emoji": "\U0001F91E", "count": 3}], replies=4),
                    _ch_msg("Sabine Mueller", "sabine.mueller@example.com",
                            "Pipeline review: 5 deals in negotiation, 3 in POC. Total value: 1.8M EUR.", 1200,
                            reactions=[{"emoji": "\U0001F4C8", "count": 4}], replies=6),
                    _ch_msg("Markus Bauer", "markus.bauer@example.com",
                            "Lost deal post-mortem: SmartBuild chose competitor on price. Lessons learned doc attached.", 2000,
                            replies=8),
                    _ch_msg("Julia Richter", "julia.richter@example.com",
                            "\U0001F31F Deal update: MediCare Solutions - moved to Technical Evaluation.", 2500,
                            reactions=[{"emoji": "\U0001F44D", "count": 3}], replies=2),
                    _ch_msg("Anna Schmidt", "anna.schmidt@example.com",
                            "Competitive intel: Main competitor raised prices by 15%. Opportunity for us.", 3000,
                            reactions=[{"emoji": "\U0001F440", "count": 6}], replies=10),
                ],
            },
        },
    ]


# ---------------------------------------------------------------------------
# Drive / Files
# ---------------------------------------------------------------------------

def default_drive_items() -> dict:
    """Return OneDrive-like file structure with recent, my_files, and shared."""
    now = _now()

    def _file(
        name: str,
        file_type: str = "file",
        mime_type: str = "application/octet-stream",
        size: int = 0,
        modified_minutes_ago: int = 60,
        modified_by: str = "Mock User",
        path: str = "/",
    ) -> dict:
        return {
            "id": _uid(),
            "name": name,
            "type": file_type,
            "mimeType": mime_type,
            "size": size,
            "modifiedAt": (now - timedelta(minutes=modified_minutes_ago)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "modifiedBy": modified_by,
            "path": path,
            "webUrl": f"https://onedrive.example.com{path}{name}",
        }

    recent = [
        _file("Q1-Revenue-Report.xlsx",
              mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
              size=245_000, modified_minutes_ago=15, modified_by="Werner Hartmann",
              path="/Documents/Finance/"),
        _file("Architecture-Decision-Record.docx",
              mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
              size=89_000, modified_minutes_ago=40, modified_by="Mock User",
              path="/Documents/Engineering/"),
        _file("Sprint-24-Retro.pptx",
              mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
              size=1_200_000, modified_minutes_ago=120, modified_by="Lisa Braun",
              path="/Documents/Engineering/"),
        _file("api-gateway-design.md",
              mime_type="text/markdown", size=12_400, modified_minutes_ago=180,
              modified_by="Mock User", path="/Projects/api-gateway/"),
        _file("customer-escalation-acme.pdf",
              mime_type="application/pdf", size=340_000, modified_minutes_ago=200,
              modified_by="Anna Schmidt", path="/Documents/Sales/"),
        _file("deploy-pipeline.py",
              mime_type="text/x-python", size=8_700, modified_minutes_ago=300,
              modified_by="Stefan Hoffmann", path="/Projects/infrastructure/"),
        _file("Team-OKRs-Q2.docx",
              mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
              size=67_000, modified_minutes_ago=400, modified_by="Klaus Weber",
              path="/Documents/Engineering/"),
        _file("brand-guidelines-v3.pdf",
              mime_type="application/pdf", size=5_600_000, modified_minutes_ago=500,
              modified_by="Monika Krueger", path="/Documents/Marketing/"),
        _file("onboarding-checklist-v3.docx",
              mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
              size=45_000, modified_minutes_ago=600, modified_by="Jens Lorenz",
              path="/Documents/HR/"),
        _file("budget-forecast-2026.xlsx",
              mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
              size=178_000, modified_minutes_ago=800, modified_by="Anja Beyer",
              path="/Documents/Finance/"),
    ]

    my_files = [
        _file("Documents", file_type="folder", path="/"),
        _file("Projects", file_type="folder", path="/"),
        _file("Shared", file_type="folder", path="/"),
        _file("Downloads", file_type="folder", path="/"),
        _file("meeting-notes.md",
              mime_type="text/markdown", size=4_200, modified_minutes_ago=60,
              modified_by="Mock User", path="/"),
        _file("TODO.md",
              mime_type="text/markdown", size=1_800, modified_minutes_ago=90,
              modified_by="Mock User", path="/"),
        _file("vacation-request.pdf",
              mime_type="application/pdf", size=52_000, modified_minutes_ago=1440,
              modified_by="Mock User", path="/"),
        _file("profile-photo.jpg",
              mime_type="image/jpeg", size=245_000, modified_minutes_ago=10000,
              modified_by="Mock User", path="/"),
        _file("ssh-config-backup.txt",
              mime_type="text/plain", size=2_100, modified_minutes_ago=20000,
              modified_by="Mock User", path="/"),
    ]

    shared = [
        _file("Project-Alpha-Wireframes.pptx",
              mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
              size=3_400_000, modified_minutes_ago=20,
              modified_by="Katrin Schwarz", path="/Shared/Project Alpha/"),
        _file("Engineering-Roadmap-2026.xlsx",
              mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
              size=156_000, modified_minutes_ago=100,
              modified_by="Frank Zimmermann", path="/Shared/Engineering/"),
        _file("Sales-Deck-Q2.pptx",
              mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
              size=8_900_000, modified_minutes_ago=200,
              modified_by="Anna Schmidt", path="/Shared/Sales/"),
        _file("CI-CD-Migration-Plan.docx",
              mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
              size=78_000, modified_minutes_ago=350,
              modified_by="Tobias Neumann", path="/Shared/Engineering/"),
        _file("Company-Handbook.pdf",
              mime_type="application/pdf", size=2_100_000, modified_minutes_ago=5000,
              modified_by="Petra Schneider", path="/Shared/HR/"),
        _file("data-governance-policy.docx",
              mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
              size=92_000, modified_minutes_ago=3000,
              modified_by="Thomas Keller", path="/Shared/Data & AI/"),
        _file("incident-response-runbook.md",
              mime_type="text/markdown", size=15_600, modified_minutes_ago=4000,
              modified_by="Stefan Hoffmann", path="/Shared/Engineering/"),
        _file("marketing-campaign-assets",
              file_type="folder",
              modified_minutes_ago=1000,
              modified_by="Daniela Engel", path="/Shared/Marketing/"),
    ]

    return {
        "recent": recent,
        "my_files": my_files,
        "shared": shared,
    }
