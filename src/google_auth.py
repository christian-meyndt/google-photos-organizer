"""Google Photos API authentication for multiple accounts."""

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .config import config

SCOPES = [
    "https://www.googleapis.com/auth/photoslibrary.readonly",
    "https://www.googleapis.com/auth/photoslibrary.edit.mediaItems",
]


def get_credentials(account_label: str) -> Credentials:
    """Get or refresh credentials for a specific account."""
    config.ensure_dirs()
    token_path = config.token_dir / f"token_{account_label}.json"

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(config.client_secrets_file), SCOPES
            )
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())

    return creds


def get_photos_service(account_label: str):
    """Build Google Photos API service for an account."""
    creds = get_credentials(account_label)
    return build("photoslibrary", "v1", credentials=creds, static_discovery=False)
