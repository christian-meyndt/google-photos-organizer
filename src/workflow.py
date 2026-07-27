"""LangGraph workflow: the agentic pipeline orchestrating all steps."""

from pathlib import Path
from typing import Annotated

from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel
from rich.console import Console
from rich.table import Table

from .classifier import classify_image
from .config import config
from .dedup import DuplicateDetector, compute_perceptual_hash
from .fetcher import delete_media_item, download_media, list_media_items
from .models import DuplicateStatus, MediaItem, ProcessedMedia, QualityVerdict
from .organizer import compute_target_path, organize_file, write_folder_summaries
from .quality import assess_quality

console = Console()


class PipelineState(BaseModel):
    """State that flows through the LangGraph pipeline."""

    accounts: list[str] = []
    media_items: list[MediaItem] = []
    processed: list[ProcessedMedia] = []
    to_delete: list[ProcessedMedia] = []
    kept: list[ProcessedMedia] = []
    errors: list[str] = []
    dry_run: bool = True
    max_items_per_account: int = 100


def fetch_node(state: PipelineState) -> dict:
    """Fetch media items from all configured accounts."""
    console.print("[bold cyan]Fetching media items from Google Photos...[/]")
    all_items = []

    for account in state.accounts:
        try:
            items = list_media_items(account, max_items=state.max_items_per_account)
            all_items.extend(items)
            console.print(f"  [green]✓[/] {account}: {len(items)} items found")
        except Exception as e:
            console.print(f"  [red]✗[/] {account}: {e}")
            return {"errors": state.errors + [f"Fetch failed for {account}: {e}"]}

    return {"media_items": all_items}


def download_and_assess_node(state: PipelineState) -> dict:
    """Download each item, compute quality and hash."""
    console.print(f"\n[bold cyan]Processing {len(state.media_items)} items...[/]")
    processed = []
    download_dir = Path("/tmp/photos-organizer-staging")
    download_dir.mkdir(parents=True, exist_ok=True)

    dedup = DuplicateDetector()

    for i, item in enumerate(state.media_items):
        console.print(f"  [{i+1}/{len(state.media_items)}] {item.filename}...", end=" ")

        try:
            local_path = download_media(item, download_dir)
            file_size = local_path.stat().st_size

            if file_size < config.min_file_size_bytes:
                console.print("[dim]skipped (too small)[/]")
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


def classify_node(state: PipelineState) -> dict:
    """Classify good, unique images using the vision model."""
    to_classify = [
        m for m in state.processed
        if m.quality != QualityVerdict.BAD
        and m.duplicate_status != DuplicateStatus.DUPLICATE
        and m.item.mime_type.startswith("image/")
    ]

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


def decide_node(state: PipelineState) -> dict:
    """Decide what to keep and what to delete."""
    to_delete = []
    kept = []

    for media in state.processed:
        if media.quality == QualityVerdict.BAD:
            to_delete.append(media)
        elif media.duplicate_status == DuplicateStatus.DUPLICATE:
            to_delete.append(media)
        else:
            kept.append(media)

    console.print(f"\n[bold]Decision:[/] keeping {len(kept)}, deleting {len(to_delete)}")
    return {"to_delete": to_delete, "kept": kept}


def organize_node(state: PipelineState) -> dict:
    """Organize kept files into folder structure."""
    console.print(f"\n[bold cyan]Organizing {len(state.kept)} files...[/]")

    for media in state.kept:
        target = compute_target_path(media)
        if state.dry_run:
            console.print(f"  [dim]→ {target / media.item.filename}[/]")
        else:
            result_path = organize_file(media)
            console.print(f"  [green]→[/] {result_path}")

    if not state.dry_run and state.kept:
        summaries = write_folder_summaries(state.kept)
        for s in summaries:
            console.print(f"  [blue]📁[/] {s.path.name}: {s.description}")

    return {}


def delete_node(state: PipelineState) -> dict:
    """Delete (trash) items marked for removal from Google Photos."""
    if not state.to_delete:
        return {}

    console.print(f"\n[bold cyan]Deleting {len(state.to_delete)} items from Google Photos...[/]")

    if state.dry_run:
        for media in state.to_delete:
            reason = "bad quality" if media.quality == QualityVerdict.BAD else "duplicate"
            console.print(f"  [dim]🗑 {media.item.filename} ({reason})[/]")
        console.print("  [yellow]Dry run — nothing actually deleted.[/]")
    else:
        for media in state.to_delete:
            success = delete_media_item(media.item.account_label, media.item.id)
            status = "[green]✓[/]" if success else "[red]✗[/]"
            console.print(f"  {status} {media.item.filename}")

    return {}


def summary_node(state: PipelineState) -> dict:
    """Print final summary."""
    console.print("\n")
    table = Table(title="Run Summary")
    table.add_column("Metric", style="bold")
    table.add_column("Count", justify="right")

    table.add_row("Total fetched", str(len(state.media_items)))
    table.add_row("Processed", str(len(state.processed)))
    table.add_row("Kept", str(len(state.kept)))
    table.add_row("Deleted (bad quality)", str(
        sum(1 for m in state.to_delete if m.quality == QualityVerdict.BAD)
    ))
    table.add_row("Deleted (duplicate)", str(
        sum(1 for m in state.to_delete if m.duplicate_status == DuplicateStatus.DUPLICATE)
    ))
    table.add_row("Errors", str(len(state.errors)))

    console.print(table)

    if state.dry_run:
        console.print("\n[yellow bold]This was a DRY RUN. Use --execute to apply changes.[/]")

    return {}


def build_workflow() -> StateGraph:
    """Construct the LangGraph workflow."""
    workflow = StateGraph(PipelineState)

    workflow.add_node("fetch", fetch_node)
    workflow.add_node("download_and_assess", download_and_assess_node)
    workflow.add_node("classify", classify_node)
    workflow.add_node("decide", decide_node)
    workflow.add_node("organize", organize_node)
    workflow.add_node("delete", delete_node)
    workflow.add_node("summary", summary_node)

    workflow.add_edge(START, "fetch")
    workflow.add_edge("fetch", "download_and_assess")
    workflow.add_edge("download_and_assess", "classify")
    workflow.add_edge("classify", "decide")
    workflow.add_edge("decide", "organize")
    workflow.add_edge("organize", "delete")
    workflow.add_edge("delete", "summary")
    workflow.add_edge("summary", END)

    return workflow.compile()
