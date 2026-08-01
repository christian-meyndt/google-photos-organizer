"""LangGraph workflow for processing Google Takeout exports from Drive."""

import shutil
from pathlib import Path

from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel
from rich.console import Console
from rich.table import Table

from .classifier import classify_image
from .config import config
from .dedup import DuplicateDetector, compute_perceptual_hash
from .fetcher import trash_media_item
from .models import DuplicateStatus, MediaItem, ProcessedMedia, QualityVerdict
from .organizer import compute_target_path, organize_file, write_folder_summaries
from .quality import assess_quality
from .takeout import (
    download_and_extract_takeout,
    find_takeout_zips,
    scan_extracted_media,
)

console = Console()


def _format_bytes(b: int) -> str:
    if b >= 1_073_741_824:
        return f"{b / 1_073_741_824:.1f} GB"
    elif b >= 1_048_576:
        return f"{b / 1_048_576:.1f} MB"
    return f"{b / 1024:.1f} KB"


class TakeoutState(BaseModel):
    """State for the Takeout processing pipeline."""

    accounts: list[str] = []
    takeout_zips: list[MediaItem] = []
    media_items: list[MediaItem] = []
    processed: list[ProcessedMedia] = []
    to_delete_from_drive: list[MediaItem] = []  # Takeout ZIPs to trash
    kept: list[ProcessedMedia] = []
    discarded: list[ProcessedMedia] = []
    errors: list[str] = []
    dry_run: bool = True
    images_only: bool = False
    max_items: int | None = None
    batch_size: int | None = None
    staging_dir: Path = Path("/tmp/photos-organizer-takeout")


def find_takeouts_node(state: TakeoutState) -> dict:
    """Find Takeout ZIP files in Google Drive."""
    console.print("[bold cyan]Looking for Takeout exports in Google Drive...[/]")
    all_zips = []

    for account in state.accounts:
        zips = find_takeout_zips(account)
        if zips:
            total_size = sum(z.file_size_bytes or 0 for z in zips)
            console.print(
                f"  [green]OK[/] {account}: {len(zips)} Takeout ZIP(s) "
                f"({_format_bytes(total_size)})"
            )
            all_zips.extend(zips)
        else:
            console.print(f"  [yellow]![/] {account}: no Takeout exports found")

    if not all_zips:
        console.print(
            "\n[yellow]No Takeout files found. Steps to create one:[/]\n"
            "  1. Go to takeout.google.com\n"
            "  2. Deselect all, then select only 'Google Photos'\n"
            "  3. Choose delivery method: 'Add to Drive'\n"
            "  4. Export (may take hours/days for large libraries)\n"
            "  5. Re-run this command once the export appears in Drive"
        )

    if state.batch_size and len(all_zips) > state.batch_size:
        console.print(
            f"\n[cyan]Processing batch of {state.batch_size} / {len(all_zips)} ZIPs. "
            f"Re-run to process the next batch.[/]"
        )
        all_zips = all_zips[: state.batch_size]

    return {"takeout_zips": all_zips, "to_delete_from_drive": all_zips}


def download_extract_node(state: TakeoutState) -> dict:
    """Download and extract Takeout ZIPs, then scan for media."""
    if not state.takeout_zips:
        return {"media_items": []}

    if state.dry_run:
        console.print(f"\n[bold cyan]Takeout ZIPs that would be processed:[/]")
        for z in state.takeout_zips:
            size = _format_bytes(z.file_size_bytes) if z.file_size_bytes else "?"
            console.print(f"  {z.filename} ({size})")
        return {"media_items": []}

    staging = state.staging_dir
    staging.mkdir(parents=True, exist_ok=True)
    all_media: list[MediaItem] = []

    for i, zip_item in enumerate(state.takeout_zips):
        size = _format_bytes(zip_item.file_size_bytes) if zip_item.file_size_bytes else "?"
        console.print(
            f"\n[bold cyan][{i+1}/{len(state.takeout_zips)}] "
            f"Downloading {zip_item.filename} ({size})...[/]"
        )

        try:
            extract_dir = download_and_extract_takeout(zip_item, staging)
            media = scan_extracted_media(
                extract_dir,
                account_label=zip_item.account_label,
                images_only=state.images_only,
                max_items=state.max_items,
            )
            total_size = sum(m.file_size_bytes or 0 for m in media)
            console.print(
                f"  [green]OK[/] Found {len(media)} media files ({_format_bytes(total_size)})"
            )
            all_media.extend(media)
        except Exception as e:
            console.print(f"  [red]FAILED[/] {e}")

    return {"media_items": all_media}


def assess_node(state: TakeoutState) -> dict:
    """Assess quality and detect duplicates."""
    if not state.media_items:
        return {"processed": []}

    console.print(f"\n[bold cyan]Assessing {len(state.media_items)} files...[/]")
    processed = []
    dedup = DuplicateDetector()

    for i, item in enumerate(state.media_items):
        size_str = _format_bytes(item.file_size_bytes) if item.file_size_bytes else "?"
        console.print(
            f"  [{i+1}/{len(state.media_items)}] {item.filename} ({size_str})...", end=" "
        )

        try:
            local_path = Path(item.download_url)  # Already extracted locally

            if not local_path.exists():
                console.print("[red]file missing[/]")
                continue

            media = ProcessedMedia(item=item, local_path=local_path)

            if item.mime_type.startswith("image/"):
                quality, blur_score = assess_quality(local_path)
                media.quality = quality
                media.blur_score = blur_score

                phash = compute_perceptual_hash(local_path)
                media.perceptual_hash = phash

                dup_status = dedup.check(media)
                media.duplicate_status = dup_status

            processed.append(media)

            status = []
            if media.quality == QualityVerdict.BAD:
                status.append("[red]bad quality[/]")
            if media.duplicate_status == DuplicateStatus.DUPLICATE:
                status.append("[yellow]duplicate[/]")
            if not status:
                status.append("[green]ok[/]")
            console.print(" ".join(status))

        except Exception as e:
            console.print(f"[red]error: {e}[/]")

    return {"processed": processed}


def classify_node(state: TakeoutState) -> dict:
    """Classify images using the vision model."""
    to_classify = [
        m for m in state.processed
        if m.quality != QualityVerdict.BAD
        and m.duplicate_status != DuplicateStatus.DUPLICATE
        and m.item.mime_type.startswith("image/")
    ]

    if not to_classify:
        return {"processed": state.processed}

    console.print(f"\n[bold cyan]Classifying {len(to_classify)} images with vision model...[/]")

    for i, media in enumerate(to_classify):
        console.print(f"  [{i+1}/{len(to_classify)}] {media.item.filename}...", end=" ")
        try:
            result = classify_image(media.local_path)
            media.category = result.category
            media.description = result.description
            console.print(f"[green]{result.category}[/]")
        except Exception as e:
            media.category = "uncategorized"
            console.print(f"[yellow]fallback ({e})[/]")

    return {"processed": state.processed}


def decide_node(state: TakeoutState) -> dict:
    """Decide what to keep and what to discard."""
    discarded = []
    kept = []

    for media in state.processed:
        if media.quality == QualityVerdict.BAD:
            discarded.append(media)
        elif media.duplicate_status == DuplicateStatus.DUPLICATE:
            discarded.append(media)
        else:
            kept.append(media)

    kept_size = sum(m.item.file_size_bytes or 0 for m in kept)
    discarded_size = sum(m.item.file_size_bytes or 0 for m in discarded)

    console.print(
        f"\n[bold]Decision:[/]\n"
        f"  Organize locally: {len(kept)} files ({_format_bytes(kept_size)})\n"
        f"  Discard: {len(discarded)} "
        f"({sum(1 for m in discarded if m.quality == QualityVerdict.BAD)} bad quality, "
        f"{sum(1 for m in discarded if m.duplicate_status == DuplicateStatus.DUPLICATE)} duplicates, "
        f"{_format_bytes(discarded_size)})"
    )
    return {"kept": kept, "discarded": discarded}


def organize_node(state: TakeoutState) -> dict:
    """Organize kept files into folder structure."""
    if not state.kept:
        return {}

    console.print(f"\n[bold cyan]Organizing {len(state.kept)} files...[/]")

    for media in state.kept:
        target = compute_target_path(media)
        if state.dry_run:
            console.print(f"  [dim]-> {target / media.item.filename}[/]")
        else:
            result_path = organize_file(media)
            console.print(f"  [green]->[/] {result_path}")

    if not state.dry_run and state.kept:
        summaries = write_folder_summaries(state.kept)
        for s in summaries:
            console.print(f"  [blue]>[/] {s.path.name}: {s.description}")

    return {}


def trash_zips_node(state: TakeoutState) -> dict:
    """Trash the Takeout ZIP files from Drive to free space."""
    if not state.to_delete_from_drive:
        return {}

    zip_size = sum(z.file_size_bytes or 0 for z in state.to_delete_from_drive)
    console.print(
        f"\n[bold cyan]Trashing {len(state.to_delete_from_drive)} Takeout ZIP(s) "
        f"from Drive ({_format_bytes(zip_size)})...[/]"
    )

    if state.dry_run:
        for z in state.to_delete_from_drive:
            size = _format_bytes(z.file_size_bytes) if z.file_size_bytes else ""
            console.print(f"  [dim]trash: {z.filename} ({size})[/]")
        console.print("  [yellow]Dry run - nothing actually deleted.[/]")
    else:
        for z in state.to_delete_from_drive:
            success = trash_media_item(z.account_label, z.id)
            status = "[green]OK[/]" if success else "[red]FAILED[/]"
            console.print(f"  {status} {z.filename}")

    return {}


def cleanup_node(state: TakeoutState) -> dict:
    """Clean up local staging directory."""
    if not state.dry_run and state.staging_dir.exists():
        shutil.rmtree(state.staging_dir, ignore_errors=True)
        console.print("\n[dim]Cleaned up staging directory.[/]")
    return {}


def summary_node(state: TakeoutState) -> dict:
    """Print final summary."""
    console.print("\n")
    table = Table(title="Takeout Processing Summary")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Takeout ZIPs found", str(len(state.takeout_zips)))
    zip_size = sum(z.file_size_bytes or 0 for z in state.takeout_zips)
    table.add_row("Takeout total size", _format_bytes(zip_size))
    table.add_row("Media files found", str(len(state.media_items)))
    table.add_row("Saved locally", str(len(state.kept)))

    bad = [m for m in state.discarded if m.quality == QualityVerdict.BAD]
    dups = [m for m in state.discarded if m.duplicate_status == DuplicateStatus.DUPLICATE]
    table.add_row("Discarded (bad quality)", str(len(bad)))
    table.add_row("Discarded (duplicate)", str(len(dups)))

    kept_size = sum(m.item.file_size_bytes or 0 for m in state.kept)
    table.add_row("Local storage used", _format_bytes(kept_size))
    table.add_row("Drive space freed", _format_bytes(zip_size))
    table.add_row("Errors", str(len(state.errors)))

    console.print(table)

    if state.dry_run:
        console.print("\n[yellow bold]This was a DRY RUN. Use --execute to apply changes.[/]")
    else:
        console.print(
            "\n[green bold]Done![/] Your photos are organized locally.\n"
            "You can now safely delete them from Google Photos to free up storage.\n"
            "  -> photos.google.com -> Storage -> Review and free up space"
        )

    return {}


def build_takeout_workflow() -> StateGraph:
    """Construct the LangGraph workflow for Takeout processing."""
    workflow = StateGraph(TakeoutState)

    workflow.add_node("find_takeouts", find_takeouts_node)
    workflow.add_node("download_extract", download_extract_node)
    workflow.add_node("assess", assess_node)
    workflow.add_node("classify", classify_node)
    workflow.add_node("decide", decide_node)
    workflow.add_node("organize", organize_node)
    workflow.add_node("trash_zips", trash_zips_node)
    workflow.add_node("cleanup", cleanup_node)
    workflow.add_node("summary", summary_node)

    workflow.add_edge(START, "find_takeouts")
    workflow.add_edge("find_takeouts", "download_extract")
    workflow.add_edge("download_extract", "assess")
    workflow.add_edge("assess", "classify")
    workflow.add_edge("classify", "decide")
    workflow.add_edge("decide", "organize")
    workflow.add_edge("organize", "trash_zips")
    workflow.add_edge("trash_zips", "cleanup")
    workflow.add_edge("cleanup", "summary")
    workflow.add_edge("summary", END)

    return workflow.compile()
