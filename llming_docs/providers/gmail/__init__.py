"""Google Workspace provider -- Gmail, Google Calendar, Drive, Slides, Sheets.

Requires: pip install google-auth google-api-python-client
"""
from __future__ import annotations


class GmailProvider:
    """Google Workspace adapter.  Not yet implemented.

    Planned scope covers Gmail, Google Calendar, Google Drive,
    Google Slides, and Google Sheets -- mirroring the same unified
    interface as the MS Graph and mock providers.

    Contributions welcome!
    """

    def __init__(self, **kwargs):  # noqa: ARG002
        raise NotImplementedError(
            "Gmail provider is not yet implemented. Contributions welcome!"
        )

    @property
    def provider_name(self) -> str:
        return "gmail"
