"""Fetch media items from Google Photos API."""

import tempfile
from datetime import datetime
from pathlib import Path

import requests
from rich.progress import Progress

from .config import config
from .google_auth import get_photos_service
from .models import MediaItem


def list_media_items(account_label: str, max_items: int = 500) -> list[MediaItem]:
    """List media items from a Google Photos account, largest first."""
    service = get_photos_service(account_label)
    items = []
    page_token = None

    with Progress() as progress:
        task = progress.add_task(f"[cyan]Listing items ({account_label})...", total=None)

        while len(items) < max_items:
            body = {"pageSize": 100}
            if page_token:
                body["pageToken"] = page_token

            results = service.mediaItems().list(**body).execute()
            media_items = results.get("mediaItems", [])

            for item in media_items:
                metadata = item.get("mediaMetadata", {})
                creation_time = metadata.get("creationTime", "")

                width = int(metadata.get("width", 0))
                height = int(metadata.get("height", 0))

                try:
                    ct = datetime.fromisoformat(creation_time.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    ct = datetime.now()

                items.append(
                    MediaItem(
                        id=item["id"],
                        filename=item.get("filename", "unknown"),
                        mime_type=item.get("mimeType", ""),
                        creation_time=ct,
                        width=width,
                        height=height,
                        account_label=account_label,
                        download_url=item["baseUrl"],
                    )
                )

            progress.update(task, advance=len(media_items))
            page_token = results.get("nextPageToken")
            if not page_token:
                break

    items.sort(key=lambda x: (x.width * x.height), reverse=True)
    return items[:max_items]


def download_media(item: MediaItem, download_dir: Path | None = None) -> Path:
    """Download a media item to a local file."""
    if download_dir is None:
        download_dir = Path(tempfile.mkdtemp())
    download_dir.mkdir(parents=True, exist_ok=True)

    suffix = "=d" if item.mime_type.startswith("video/") else "=d"
    url = f"{item.download_url}{suffix}"

    response = requests.get(url, stream=True, timeout=120)
    response.raise_for_status()

    local_path = download_dir / item.filename
    with open(local_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    return local_path


def delete_media_item(account_label: str, item_id: str) -> bool:
    """Move a media item to trash in Google Photos."""
    service = get_photos_service(account_label)
    try:
        service.mediaItems().batchRemoveMediaItems(
            body={"mediaItemIds": [item_id]}
        ).execute()
        return True
    except Exception:
        return False
