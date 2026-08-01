"""CLI interface for the Google Drive Photos Organizer."""

import os

import typer
from rich.console import Console

from .config import config
from .workflow import PipelineState, build_workflow
from .takeout_workflow import TakeoutState, build_takeout_workflow

app = typer.Typer(
    name="photos-organizer",
    help="Organize, deduplicate, and classify photos/videos from Google Drive using local AI.",
)
console = Console()


@app.command()
def run(
    accounts: str = typer.Option(
        os.getenv("ACCOUNTS", "christian,wife"),
        help="Comma-separated account labels to process",
    ),
    max_items: int = typer.Option(
        100,
        help="Maximum items to fetch per account (sorted by size, largest first)",
    ),
    execute: bool = typer.Option(
        False,
        "--execute",
        help="Actually move files and trash from Google Drive (default is dry run)",
    ),
    images_only: bool = typer.Option(
        False,
        "--images-only",
        help="Skip videos, only process image files",
    ),
):
    """Run the photo organization pipeline."""
    console.print("[bold]Google Drive Photos Organizer[/]\n")

    if not execute:
        console.print("[yellow]Running in DRY RUN mode. Use --execute to apply changes.[/]\n")

    account_list = [a.strip() for a in accounts.split(",")]

    workflow = build_workflow()

    initial_state = PipelineState(
        accounts=account_list,
        max_items_per_account=max_items,
        dry_run=not execute,
        images_only=images_only,
    )

    workflow.invoke(initial_state)


@app.command()
def takeout(
    accounts: str = typer.Option(
        os.getenv("ACCOUNTS", "christian,wife"),
        help="Comma-separated account labels to process",
    ),
    execute: bool = typer.Option(
        False,
        "--execute",
        help="Actually process files and trash ZIPs from Drive (default is dry run)",
    ),
    images_only: bool = typer.Option(
        False,
        "--images-only",
        help="Skip videos, only process image files",
    ),
    max_items: int = typer.Option(
        None,
        help="Maximum media files to process (default: all)",
    ),
):
    """Process Google Takeout exports stored in Google Drive.

    Finds Takeout ZIP files in Drive, downloads and extracts them,
    deduplicates and classifies the photos/videos, organizes them
    locally, then trashes the ZIPs from Drive to free space.

    Steps to use:
      1. Go to takeout.google.com
      2. Select only 'Google Photos'
      3. Choose delivery: 'Add to Drive'
      4. Wait for export to complete
      5. Run: photos-organizer takeout --execute
    """
    console.print("[bold]Google Takeout Photos Processor[/]\n")

    if not execute:
        console.print("[yellow]Running in DRY RUN mode. Use --execute to apply changes.[/]\n")

    account_list = [a.strip() for a in accounts.split(",")]

    workflow = build_takeout_workflow()

    initial_state = TakeoutState(
        accounts=account_list,
        dry_run=not execute,
        images_only=images_only,
        max_items=max_items,
    )

    workflow.invoke(initial_state)


@app.command()
def auth(
    account: str = typer.Argument(help="Account label (e.g., 'christian' or 'wife')"),
):
    """Authenticate a Google account (run this first for each account)."""
    from .google_auth import get_credentials

    console.print(f"[cyan]Authenticating account: {account}[/]")
    console.print("A browser window will open for Google sign-in.\n")

    try:
        get_credentials(account)
        console.print(f"[green]OK[/] Successfully authenticated '{account}'")
        console.print(f"  Token saved to: {config.token_dir}/token_{account}.json")
    except Exception as e:
        console.print(f"[red]FAILED[/] Authentication failed: {e}")
        raise typer.Exit(1)


@app.command()
def storage(
    accounts: str = typer.Option(
        os.getenv("ACCOUNTS", "christian,wife"),
        help="Comma-separated account labels",
    ),
):
    """Show storage usage for each Google Drive account."""
    from .fetcher import get_storage_usage

    account_list = [a.strip() for a in accounts.split(",")]

    for account in account_list:
        try:
            usage = get_storage_usage(account)
            total = usage["total"]
            used = usage["used"]
            pct = (used / total * 100) if total else 0

            bar_len = 30
            filled = int(bar_len * pct / 100)
            bar = "[green]" + "=" * filled + "[/]" + "-" * (bar_len - filled)

            console.print(f"\n[bold]{account}[/]")
            console.print(f"  [{bar}] {pct:.1f}%")
            console.print(f"  Used: {used / 1_073_741_824:.2f} GB / {total / 1_073_741_824:.0f} GB")
            console.print(f"  In trash: {usage['used_in_trash'] / 1_048_576:.0f} MB")
        except Exception as e:
            console.print(f"\n[bold]{account}[/]")
            console.print(f"  [red]Error: {e}[/]")


@app.command()
def status():
    """Show configuration and auth status."""
    console.print("[bold]Configuration[/]\n")
    console.print(f"  Output directory: {config.output_dir}")
    console.print(f"  Ollama model: {config.ollama_model}")
    console.print(f"  Ollama URL: {config.ollama_base_url}")
    console.print(f"  Min file size: {config.min_file_size_bytes / 1024:.0f} KB")
    console.print(f"  Blur threshold: {config.blur_threshold}")
    console.print(f"  Hash distance: {config.hash_distance_threshold}")

    console.print("\n[bold]Authenticated accounts[/]\n")
    token_dir = config.token_dir
    if token_dir.exists():
        tokens = list(token_dir.glob("token_*.json"))
        if tokens:
            for t in tokens:
                label = t.stem.replace("token_", "")
                console.print(f"  [green]OK[/] {label}")
        else:
            console.print("  [yellow]No accounts authenticated yet.[/]")
    else:
        console.print("  [yellow]No accounts authenticated yet.[/]")

    console.print("\n[bold]Ollama status[/]\n")
    try:
        import requests
        resp = requests.get(f"{config.ollama_base_url}/api/tags", timeout=5)
        if resp.ok:
            models = [m["name"] for m in resp.json().get("models", [])]
            if config.ollama_model in models or any(config.ollama_model in m for m in models):
                console.print(f"  [green]OK[/] Ollama running, model '{config.ollama_model}' available")
            else:
                console.print(f"  [yellow]![/] Ollama running but model '{config.ollama_model}' not found")
                console.print(f"    Available: {', '.join(models[:5])}")
                console.print(f"    Run: ollama pull {config.ollama_model}")
        else:
            console.print("  [red]X[/] Ollama not responding")
    except Exception:
        console.print("  [red]X[/] Ollama not running. Start with: ollama serve")


if __name__ == "__main__":
    app()
