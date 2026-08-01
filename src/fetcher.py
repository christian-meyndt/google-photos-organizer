"""Fetch media items from Google Drive API."""

import io
import tempfile
from datetime import datetime
from pathlib import Path

from googleapiclient.http import MediaIoBaseDownload
from rich.progress import Progress
from rich.console import Console

from .config import config
from .google_auth import get_drive_service
from .models import MediaItem

console = Console()

MEDIA_MIME_TYPES = [
    "image/jpeg",
    "image/png",
    "image/heic",
    "image/heif",
    "image/webp",
    "image/gif",
    "video/mp4",
    "video/quicktime",
    "video/3gpp",
    "video/x-msvideo",
    "video/mpeg",
]


def _build_mime_query() -> str:
    """Build a Drive API query to find media files."""
    clauses = [f"mimeType='{mt}'" for mt in MEDIA_MIME_TYPES]
    return f"({' or '.join(clauses)}) and trashed=false"


def list_media_items(account_label: str, max_items: int = 500) -> list[MediaItem]:
    """List media items from Google Drive, sorted by size (largest first)."""
    service = get_drive_service(account_label)
    items = []
    page_token = None

    query = _build_mime_query()
    fields = "nextPageToken, files(id, name, mimeType, size, createdTime, imageMediaMetadata)"

    with Progress() as progress:
        task = progress.add_task(f"[cyan]Listing items ({account_label})...", total=None)

        while len(items) < max_items:
            request = service.files().list(
                q=query,
                pageSize=100,
                fields=fields,
                orderBy="quotaBytesUsed desc",
                pageToken=page_token,
            )
            results = request.execute()
            files = results.get("files", [])

            for f in files:
                created_time = f.get("createdTime", "")
                try:
                    ct = datetime.fromisoformat(created_time.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    ct = datetime.now()

                img_meta = f.get("imageMediaMetadata", {})
                width = img_meta.get("width", 0)
                height = img_meta.get("height", 0)

                items.append(
                    MediaItem(
                        id=f["id"],
                        filename=f.get("name", "unknown"),
                        mime_type=f.get("mimeType", ""),
                        creation_time=ct,
                        width=width,
                        height=height,
                        file_size_bytes=int(f.get("size", 0)),
                        account_label=account_label,
                        download_url="",
                    )
                )

            progress.update(task, advance=len(files))
            page_token = results.get("nextPageToken")
            if not page_token:
                break

    items.sort(key=lambda x: x.file_size_bytes or 0, reverse=True)
    return items[:max_items]


def download_media(item: MediaItem, download_dir: Path | None = None) -> Path:
    """Download a media item from Google Drive."""
    if download_dir is None:
        download_dir = Path(tempfile.mkdtemp())
    download_dir.mkdir(parents=True, exist_ok=True)

    service = get_drive_service(item.account_label)
    request = service.files().get_media(fileId=item.id)

    local_path = download_dir / item.filename
    with open(local_path, "wb") as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

    return local_path


def trash_media_item(account_label: str, item_id: str) -> bool:
    """Move a media item to trash in Google Drive."""
    service = get_drive_service(account_label)
    try:
        service.files().update(fileId=item_id, body={"trashed": True}).execute()
        return True
    except Exception as e:
        console.print(f"  [red]Delete failed: {e}[/]")
        return False


def get_storage_usage(account_label: str) -> dict:
    """Get storage usage info for the account."""
    service = get_drive_service(account_label)
    about = service.about().get(fields="storageQuota").execute()
    quota = about.get("storageQuota", {})
    return {
        "total": int(quota.get("limit", 0)),
        "used": int(quota.get("usage", 0)),
        "used_in_drive": int(quota.get("usageInDrive", 0)),
        "used_in_trash": int(quota.get("usageInDriveTrash", 0)),
    }
