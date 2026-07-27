"""Quality assessment: blur detection and resolution checks."""

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .config import config
from .models import QualityVerdict


def compute_blur_score(image_path: Path) -> float:
    """Compute Laplacian variance as a blur metric. Higher = sharper."""
    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0.0
    return cv2.Laplacian(img, cv2.CV_64F).var()


def check_resolution(image_path: Path) -> bool:
    """Check if image meets minimum resolution requirements."""
    try:
        with Image.open(image_path) as img:
            w, h = img.size
            return w >= config.min_resolution_width and h >= config.min_resolution_height
    except Exception:
        return False


def assess_quality(image_path: Path) -> tuple[QualityVerdict, float]:
    """Assess overall quality of an image."""
    if not image_path.exists():
        return QualityVerdict.BAD, 0.0

    if not check_resolution(image_path):
        return QualityVerdict.BAD, 0.0

    blur_score = compute_blur_score(image_path)

    if blur_score < config.blur_threshold * 0.5:
        return QualityVerdict.BAD, blur_score
    elif blur_score < config.blur_threshold:
        return QualityVerdict.MARGINAL, blur_score
    else:
        return QualityVerdict.GOOD, blur_score
