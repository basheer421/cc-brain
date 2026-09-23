"""CLI entry point for cc-brain."""

import json
import sys

import click

from .config import load_config
from .search import WikiSearch


@click.group()
@click.option("--config", "-c", default=None, help="Config file path")
@click.pass_context
def main(ctx, config):
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config
    ctx.obj["config"] = load_config(config)


@main.command()
@click.pass_context
def start(ctx):
    """Start the cc-brain daemon."""
    from .daemon import run_daemon
    run_daemon(ctx.obj["config_path"])


@main.command()
@click.pass_context
def status(ctx):
    """Show daemon status."""
    from pathlib import Path
    import os

    config = ctx.obj["config"]
    pid_path = Path(config["pid_file"])

    if not pid_path.exists():
        click.echo("cc-brain: not running")
        sys.exit(1)

    pid = int(pid_path.read_text().strip())
    try:
        os.kill(pid, 0)
        click.echo(f"cc-brain: running (pid {pid})")
    except ProcessLookupError:
        click.echo("cc-brain: stale pid file (not running)")
        pid_path.unlink(missing_ok=True)
        sys.exit(1)


@main.command()
@click.argument("query")
@click.option("--scope", "-s", default=None, help="Scope to subdirectory")
@click.option("--limit", "-n", default=5, help="Max results")
@click.pass_context
def search(ctx, query, scope, limit):
    """Search the llm-wiki index."""
    config = ctx.obj["config"]
    ws = WikiSearch(config["search_db"], config["wiki_dir"])
    results = ws.search(query, limit=limit, scope=scope)
    ws.close()

    if not results:
        click.echo("No results.")
        return

    for r in results:
        click.echo(f"\n{r['title'] or r['path']} (score: {r['score']})")
        click.echo(f"  {r['path']}")
        click.echo(f"  {r['snippet']}")


@main.command()
@click.pass_context
def reindex(ctx):
    """Rebuild the search index."""
    config = ctx.obj["config"]
    ws = WikiSearch(config["search_db"], config["wiki_dir"])
    count = ws.rebuild()
    ws.close()
    click.echo(f"Indexed {count} pages.")


@main.command()
@click.pass_context
def queue(ctx):
    """Show pending suggestions."""
    from .queue import list_pending
    config = ctx.obj["config"]
    pending = list_pending(config["queue_dir"])

    if not pending:
        click.echo("No pending suggestions.")
        return

    for item in pending:
        click.echo(f"\n[{item['id'][:8]}] {item['target']} ({item['type']})")
        click.echo(f"  {item['content'][:120]}...")


@main.command()
@click.pass_context
def mcp(ctx):
    """Run the MCP stdio server."""
    from .mcp_server import run_mcp
    run_mcp(ctx.obj["config"])
