"""Microsoft Graph provider -- wraps the office-connect library.

Requires: pip install office-connect
"""
from __future__ import annotations


class MsGraphProvider:
    """MS Graph adapter using the office-connect library.

    Translates calls into ``office_con.msgraph.MsGraphInstance`` operations
    and maps the raw MS Graph JSON responses into unified provider models.

    Usage::

        provider = MsGraphProvider(
            client_id="...",
            client_secret="...",
            tenant_id="...",
        )
        url = provider.build_login_url("http://localhost:8000/callback")
        # ... after OAuth redirect ...
        await provider.handle_oauth_callback(code, redirect_uri)
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        tenant_id: str = "common",
        endpoint: str = "https://graph.microsoft.com/v1.0/",
        scopes: list[str] | None = None,
    ):
        try:
            from office_con.msgraph.ms_graph_handler import MsGraphInstance
            from office_con.auth.office_user_instance import OfficeUserInstance
        except ImportError as exc:
            raise ImportError(
                "office-connect is required for the MS Graph provider. "
                "Install it with: pip install office-connect"
            ) from exc

        if scopes is None:
            scopes = list(set(
                OfficeUserInstance.PROFILE_SCOPE
                + OfficeUserInstance.MAIL_SCOPE
                + OfficeUserInstance.CALENDAR_SCOPE
                + OfficeUserInstance.DIRECTORY_SCOPE
            ))

        self._graph = MsGraphInstance(
            scopes=scopes,
            client_id=client_id,
            client_secret=client_secret,
            tenant_id=tenant_id,
            endpoint=endpoint,
            select_account=True,
        )
        self._scopes = scopes

    # -- Properties ----------------------------------------------------------

    @property
    def graph(self):
        """Access the underlying ``MsGraphInstance``."""
        return self._graph

    @property
    def provider_name(self) -> str:
        return "msgraph"

    @property
    def is_authenticated(self) -> bool:
        return bool(self._graph.cache_dict.get("access_token"))

    @property
    def user_email(self) -> str | None:
        return self._graph.email

    @property
    def user_name(self) -> str | None:
        return self._graph.full_name

    # -- Auth ----------------------------------------------------------------

    def build_login_url(self, redirect_uri: str) -> str:
        """Return the OAuth2 authorization URL for the user to visit."""
        return self._graph.build_auth_url(redirect_uri)

    async def handle_oauth_callback(self, code: str, redirect_uri: str) -> bool:
        """Exchange the authorization *code* for an access token.

        Returns ``True`` on success, ``False`` on failure.
        """
        from fastapi.responses import HTMLResponse

        result = await self._graph.acquire_token_async(code, redirect_uri)
        return not (isinstance(result, HTMLResponse) and result.status_code >= 400)

    # -- Mail ----------------------------------------------------------------

    # TODO: list_folders() -> list[Folder]
    #       Map office_con mail folder dicts to unified Folder model.

    # TODO: list_messages(folder_id, top, skip) -> MessageList
    #       Map office_con message dicts to unified Message model.

    # TODO: get_message(message_id) -> Message
    #       Fetch a single message and map to unified model.

    # TODO: send_message(draft: DraftMessage) -> None
    #       Compose and send via office_con.

    # TODO: reply_message(message_id, body) -> None

    # TODO: forward_message(message_id, to, body) -> None

    # TODO: move_message(message_id, folder_id) -> None

    # TODO: delete_message(message_id) -> None

    # -- Calendar ------------------------------------------------------------

    # TODO: list_calendars() -> list[Calendar]

    # TODO: list_events(calendar_id, start, end) -> EventList
    #       Map office_con event dicts to unified Event model.

    # TODO: get_event(event_id) -> Event

    # TODO: create_event(event: Event) -> Event

    # TODO: update_event(event_id, event: Event) -> Event

    # TODO: delete_event(event_id) -> None

    # -- People / Directory --------------------------------------------------

    # TODO: list_people(query, top) -> PersonList
    #       Map office_con directory user dicts to unified Person model.

    # TODO: get_person(person_id) -> Person

    # TODO: get_person_photo(person_id) -> bytes | None

    # TODO: get_user_profile() -> UserProfile

    # -- Files / OneDrive ----------------------------------------------------

    # TODO: list_drives() -> list[Drive]

    # TODO: list_drive_items(drive_id, folder_path) -> DriveItemList

    # TODO: get_drive_item(drive_id, item_id) -> DriveItem

    # TODO: download_drive_item(drive_id, item_id) -> bytes

    # TODO: upload_drive_item(drive_id, folder_path, name, content) -> DriveItem
