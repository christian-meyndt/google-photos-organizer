"""CLI interface for the Google Photos Organizer."""

import os

import typer
from rich.console import Console

from .config import config
from .workflow import PipelineState, build_workflow

app = typer.Typer(
    name="photos-organizer",
    help="Organize, deduplicate, and classify Google Photos using local AI.",
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
        help="Maximum items to fetch per account",
    ),
    execute: bool = typer.Option(
        False,
        "--execute",
        help="Actually move files and delete from Google Photos (default is dry run)",
    ),
):
    """Run the photo organization pipeline."""
    console.print("[bold]Google Photos Organizer[/]\n")

    if not execute:
        console.print("[yellow]Running in DRY RUN mode. Use --execute to apply changes.[/]\n")

    account_list = [a.strip() for a in accounts.split(",")]

    workflow = build_workflow()

    initial_state = PipelineState(
        accounts=account_list,
        max_items_per_account=max_items,
        dry_run=not execute,
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
        console.print(f"[green]✓ Successfully authenticated '{account}'[/]")
        console.print(f"  Token saved to: {config.token_dir}/token_{account}.json")
    except Exception as e:
        console.print(f"[red]✗ Authentication failed: {e}[/]")
        raise typer.Exit(1)


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
                console.print(f"  [green]✓[/] {label}")
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
                console.print(f"  [green]✓[/] Ollama running, model '{config.ollama_model}' available")
            else:
                console.print(f"  [yellow]⚠[/] Ollama running but model '{config.ollama_model}' not found")
                console.print(f"    Available: {', '.join(models[:5])}")
                console.print(f"    Run: ollama pull {config.ollama_model}")
        else:
            console.print("  [red]✗[/] Ollama not responding")
    except Exception:
        console.print("  [red]✗[/] Ollama not running. Start with: ollama serve")


if __name__ == "__main__":
    app()
