"""File organization: move files into date/category folders."""

import shutil
from collections import defaultdict
from pathlib import Path

from .classifier import generate_folder_summary
from .config import config
from .models import FolderSummary, ProcessedMedia


def compute_target_path(media: ProcessedMedia) -> Path:
    """Compute the target folder path: YYYY/MM-MonthName/category/"""
    dt = media.item.creation_time
    month_name = dt.strftime("%m-%B")
    return config.output_dir / str(dt.year) / month_name / media.category


def organize_file(media: ProcessedMedia) -> Path:
    """Move a processed file to its target location."""
    target_dir = compute_target_path(media)
    target_dir.mkdir(parents=True, exist_ok=True)

    target_path = target_dir / media.item.filename

    counter = 1
    while target_path.exists():
        stem = media.item.filename.rsplit(".", 1)[0]
        ext = media.item.filename.rsplit(".", 1)[1] if "." in media.item.filename else ""
        target_path = target_dir / f"{stem}_{counter}.{ext}"
        counter += 1

    shutil.move(str(media.local_path), str(target_path))
    media.target_folder = target_dir
    return target_path


def write_folder_summaries(processed_items: list[ProcessedMedia]) -> list[FolderSummary]:
    """Generate and write README summaries for each folder."""
    folders: dict[Path, list[ProcessedMedia]] = defaultdict(list)

    for item in processed_items:
        if item.target_folder:
            folders[item.target_folder].append(item)

    summaries = []
    for folder_path, items in folders.items():
        descriptions = [item.description for item in items if item.description]
        categories = list(set(item.category for item in items))

        if descriptions:
            summary_text = generate_folder_summary(descriptions, folder_path.name)
        else:
            summary_text = f"Contains {len(items)} media files."

        readme_path = folder_path / "README.txt"
        readme_content = (
            f"Folder: {folder_path.name}\n"
            f"Files: {len(items)}\n"
            f"Categories: {', '.join(categories)}\n\n"
            f"Summary: {summary_text}\n\n"
            "Contents:\n"
        )
        for item in items:
            readme_content += f"  - {item.item.filename}: {item.description}\n"

        readme_path.write_text(readme_content)

        summaries.append(
            FolderSummary(
                path=folder_path,
                description=summary_text,
                file_count=len(items),
                categories=categories,
            )
        )

    return summaries
