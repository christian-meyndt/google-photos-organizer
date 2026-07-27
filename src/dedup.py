"""Duplicate detection using perceptual hashing."""

from pathlib import Path

import imagehash
from PIL import Image

from .config import config
from .models import DuplicateStatus, ProcessedMedia


def compute_perceptual_hash(image_path: Path) -> str | None:
    """Compute perceptual hash for an image."""
    try:
        with Image.open(image_path) as img:
            return str(imagehash.phash(img))
    except Exception:
        return None


class DuplicateDetector:
    """Track seen hashes and detect duplicates across all processed media."""

    def __init__(self):
        self.seen_hashes: dict[str, ProcessedMedia] = {}

    def check(self, media: ProcessedMedia) -> DuplicateStatus:
        """Check if this media is a duplicate of something already seen."""
        if media.perceptual_hash is None:
            return DuplicateStatus.UNIQUE

        current_hash = imagehash.hex_to_hash(media.perceptual_hash)

        for existing_hash_str, existing_media in self.seen_hashes.items():
            existing_hash = imagehash.hex_to_hash(existing_hash_str)
            distance = current_hash - existing_hash

            if distance <= config.hash_distance_threshold:
                current_res = media.item.width * media.item.height
                existing_res = existing_media.item.width * existing_media.item.height

                if current_res > existing_res:
                    existing_media.duplicate_status = DuplicateStatus.DUPLICATE
                    self.seen_hashes[media.perceptual_hash] = media
                    return DuplicateStatus.BEST_OF_GROUP
                else:
                    return DuplicateStatus.DUPLICATE

        self.seen_hashes[media.perceptual_hash] = media
        return DuplicateStatus.UNIQUE
