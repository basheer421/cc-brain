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
@click.option("--background/--foreground", "-b/-f", default=False, help="Detach and run in the background")
@click.pass_context
def start(ctx, background):
    """Start the cc-brain daemon."""
    if background:
        import os
        import subprocess
        from pathlib import Path

        config = ctx.obj["config"]
        pid_path = Path(config["pid_file"])
        if pid_path.exists():
            old_pid = int(pid_path.read_text().strip())
            try:
                os.kill(old_pid, 0)
                click.echo(f"cc-brain: already running (pid {old_pid})")
                sys.exit(1)
            except ProcessLookupError:
                pass

        import shutil
        log_path = Path(config["error_log"])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        cc_brain_bin = shutil.which("cc-brain")
        if not cc_brain_bin:
            click.echo("cc-brain: binary not found in PATH", err=True)
            sys.exit(1)
        with open(log_path, "a") as log_fd:
            args = [cc_brain_bin]
            if ctx.obj["config_path"]:
                args.extend(["-c", ctx.obj["config_path"]])
            args.append("start")
            proc = subprocess.Popen(
                args,
                stdout=log_fd,
                stderr=log_fd,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        import time
        time.sleep(2)
        pid_path = Path(config["pid_file"])
        if pid_path.exists():
            pid = int(pid_path.read_text().strip())
            try:
                os.kill(pid, 0)
                click.echo(f"cc-brain: started in background (pid {pid})")
                return
            except ProcessLookupError:
                pass
        click.echo("cc-brain: failed to start — check " + str(log_path), err=True)
        sys.exit(1)

    from .daemon import run_daemon
    run_daemon(ctx.obj["config_path"])


@main.command()
@click.pass_context
def stop(ctx):
    """Stop the cc-brain daemon."""
    import os
    import signal
    from pathlib import Path

    config = ctx.obj["config"]
    pid_path = Path(config["pid_file"])

    if not pid_path.exists():
        click.echo("cc-brain: not running")
        sys.exit(1)

    pid = int(pid_path.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        click.echo(f"cc-brain: stopped (pid {pid})")
    except ProcessLookupError:
        click.echo("cc-brain: stale pid file (not running)")
        pid_path.unlink(missing_ok=True)
        sys.exit(1)


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


@main.command("migrate-pi-memory")
@click.option("--apply", "do_apply", is_flag=True, help="Write pages and commit (default: dry run)")
@click.pass_context
def migrate_pi_memory(ctx, do_apply):
    """Copy pi-hermes-memory stores into llm-wiki pages."""
    import subprocess
    from .migrate import plan, apply

    wiki_dir = ctx.obj["config"]["wiki_dir"]
    pages = plan(wiki_dir)
    for rel, body in pages.items():
        click.echo(f"{rel}: {body.count(chr(10) + '- ')} entries, {len(body)} chars")
    if not pages:
        click.echo("Nothing to migrate.")
        return
    if not do_apply:
        click.echo("Dry run. Re-run with --apply to write.")
        return
    apply(wiki_dir, pages)
    subprocess.run(["git", "-C", wiki_dir, "add", "-A"], check=True)
    subprocess.run(["git", "-C", wiki_dir, "commit", "-qm", "migrate: pi-hermes-memory stores"], check=True)
    ws = WikiSearch(ctx.obj["config"]["search_db"], wiki_dir)
    click.echo(f"Wrote {len(pages)} pages, reindexed {ws.rebuild()} pages.")
    ws.close()


@main.command()
@click.pass_context
def mcp(ctx):
    """Run the MCP stdio server."""
    from .mcp_server import run_mcp
    run_mcp(ctx.obj["config"])
