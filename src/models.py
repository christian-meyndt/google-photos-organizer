"""Data models for the pipeline."""

from datetime import datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel


class QualityVerdict(str, Enum):
    GOOD = "good"
    BAD = "bad"
    MARGINAL = "marginal"


class DuplicateStatus(str, Enum):
    UNIQUE = "unique"
    DUPLICATE = "duplicate"
    BEST_OF_GROUP = "best_of_group"


class MediaItem(BaseModel):
    id: str
    filename: str
    mime_type: str
    creation_time: datetime
    width: int
    height: int
    file_size_bytes: int | None = None
    account_label: str
    download_url: str


class ProcessedMedia(BaseModel):
    item: MediaItem
    local_path: Path
    perceptual_hash: str | None = None
    blur_score: float | None = None
    quality: QualityVerdict = QualityVerdict.GOOD
    duplicate_status: DuplicateStatus = DuplicateStatus.UNIQUE
    category: str = "uncategorized"
    description: str = ""
    target_folder: Path | None = None


class FolderSummary(BaseModel):
    path: Path
    description: str
    file_count: int
    categories: list[str]
