"""Process Google Takeout exports delivered to Google Drive."""

import json
import zipfile
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.progress import Progress

from .config import config
from .fetcher import download_media, trash_media_item
from .google_auth import get_drive_service
from .models import MediaItem

console = Console()

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif", ".tiff", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".3gp", ".mpg", ".mpeg", ".m4v"}
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

MIME_MAP = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".3gp": "video/3gpp",
    ".mpg": "video/mpeg",
    ".mpeg": "video/mpeg",
    ".m4v": "video/mp4",
}


def find_takeout_zips(account_label: str) -> list[MediaItem]:
    """Find Google Takeout ZIP files in Drive."""
    service = get_drive_service(account_label)

    query = (
        "(name contains 'takeout' or name contains 'Takeout') "
        "and (mimeType='application/zip' or mimeType='application/x-zip' "
        "or mimeType='application/x-zip-compressed') "
        "and trashed=false "
        "and 'me' in owners"
    )

    results = service.files().list(
        q=query,
        pageSize=100,
        fields="files(id, name, size, createdTime)",
        orderBy="name",
    ).execute()
    files = results.get("files", [])

    items = []
    for f in files:
        created_time = f.get("createdTime", "")
        try:
            ct = datetime.fromisoformat(created_time.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            ct = datetime.now()

        items.append(
            MediaItem(
                id=f["id"],
                filename=f.get("name", "unknown"),
                mime_type="application/zip",
                creation_time=ct,
                width=0,
                height=0,
                file_size_bytes=int(f.get("size", 0)),
                account_label=account_label,
                download_url="",
            )
        )

    return items


def download_and_extract_takeout(
    zip_item: MediaItem, staging_dir: Path
) -> Path:
    """Download a Takeout ZIP from Drive and extract it."""
    zip_path = download_media(zip_item, staging_dir)

    extract_dir = staging_dir / zip_item.filename.replace(".zip", "")
    extract_dir.mkdir(parents=True, exist_ok=True)

    console.print(f"  Extracting {zip_item.filename}...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)

    # Remove the zip to save local disk space
    zip_path.unlink()

    return extract_dir


def _get_creation_time(media_path: Path) -> datetime:
    """Get creation time from companion JSON metadata, filename, or file stats."""
    # Try companion JSON (Takeout puts metadata as filename.ext.json)
    json_candidates = [
        media_path.with_suffix(media_path.suffix + ".json"),
        media_path.parent / (media_path.stem + ".json"),
    ]

    for json_path in json_candidates:
        if json_path.exists():
            try:
                meta = json.loads(json_path.read_text())
                timestamp = meta.get("photoTakenTime", {}).get("timestamp")
                if timestamp:
                    return datetime.fromtimestamp(int(timestamp))
            except (json.JSONDecodeError, ValueError, OSError):
                pass

    # Try parsing date from filename (IMG_20240730_191216, VID_20241109_123057, etc.)
    import re
    patterns = [
        r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})",  # 20240730_191216
        r"(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})",  # 2024-07-30-19-12-16
        r"(\d{4})-(\d{2})-(\d{2})",  # 2024-07-30
    ]

    for pattern in patterns:
        match = re.search(pattern, media_path.stem)
        if match:
            groups = match.groups()
            try:
                if len(groups) == 6:
                    return datetime(
                        int(groups[0]), int(groups[1]), int(groups[2]),
                        int(groups[3]), int(groups[4]), int(groups[5])
                    )
                elif len(groups) == 3:
                    return datetime(int(groups[0]), int(groups[1]), int(groups[2]))
            except ValueError:
                continue

    # Last resort: file modification time
    return datetime.fromtimestamp(media_path.stat().st_mtime)


def scan_extracted_media(
    extract_dir: Path,
    account_label: str,
    images_only: bool = False,
    max_items: int | None = None,
) -> list[MediaItem]:
    """Scan extracted Takeout folder for media files."""
    allowed_extensions = IMAGE_EXTENSIONS if images_only else MEDIA_EXTENSIONS

    media_files: list[Path] = []
    for f in extract_dir.rglob("*"):
        if f.suffix.lower() in allowed_extensions and not f.name.startswith("."):
            media_files.append(f)

    media_files.sort(key=lambda f: f.stat().st_size, reverse=True)

    if max_items:
        media_files = media_files[:max_items]

    items = []
    for f in media_files:
        size = f.stat().st_size
        creation_time = _get_creation_time(f)
        ext = f.suffix.lower()
        mime_type = MIME_MAP.get(ext, "application/octet-stream")

        items.append(
            MediaItem(
                id=str(f),  # local path as ID for takeout items
                filename=f.name,
                mime_type=mime_type,
                creation_time=creation_time,
                width=0,
                height=0,
                file_size_bytes=size,
                account_label=account_label,
                download_url=str(f),  # local path, already extracted
            )
        )

    return items
