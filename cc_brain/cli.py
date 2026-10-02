"""CLI entry point for cc-brain."""

import json
import sys

import click

from .config import load_config
from .search import WikiSearch


@click.group()
@click.version_option(package_name="cc-brain", prog_name="cc-brain")
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
        log_path = Path(config["error_log"]).with_name("daemon.log")
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
@click.option("--apply", "do_apply", is_flag=True, help="Write pages and commit (default: dry run)")
@click.pass_context
def compact(ctx, do_apply):
    """Merge duplicate ## sections and drop repeated bullets in the wiki."""
    import subprocess
    from .compact import compact_wiki

    wiki_dir = ctx.obj["config"]["wiki_dir"]
    if do_apply:
        dirty = subprocess.run(["git", "-C", wiki_dir, "status", "--porcelain"],
                               capture_output=True, text=True).stdout.strip()
        if dirty:
            click.echo("Wiki has uncommitted changes; commit or stash first.", err=True)
            sys.exit(1)
    changes = compact_wiki(wiki_dir, write=do_apply)
    for rel, before, after in changes:
        click.echo(f"{rel}: {before} -> {after} bytes ({after - before:+d})")
    if not changes:
        click.echo("Nothing to compact.")
        return
    if not do_apply:
        click.echo("Dry run. Re-run with --apply to write.")
        return
    subprocess.run(["git", "-C", wiki_dir, "add", "-A"], check=True)
    subprocess.run(["git", "-C", wiki_dir, "commit", "-qm", "compact: merge duplicate sections/bullets"], check=True)
    ws = WikiSearch(ctx.obj["config"]["search_db"], wiki_dir)
    click.echo(f"Compacted {len(changes)} pages, reindexed {ws.rebuild()} pages.")
    ws.close()


def _brain(ctx):
    from .brain import Brain
    return Brain(ctx.obj["config"]["brain_db"], ctx.obj["config"])


def _since(value):
    """'yesterday', 'today', '7d', or YYYY-MM-DD -> YYYY-MM-DD."""
    from datetime import date, timedelta
    if not value:
        return None
    v = value.strip().lower()
    if v == "today":
        return date.today().isoformat()
    if v == "yesterday":
        return (date.today() - timedelta(days=1)).isoformat()
    if v.endswith("d") and v[:-1].isdigit():
        return (date.today() - timedelta(days=int(v[:-1]))).isoformat()
    return value


@main.command("index-episodes")
@click.option("--embed/--no-embed", default=True, help="Embed chunks (needs Ollama)")
@click.pass_context
def index_episodes(ctx, embed):
    """Index session summaries as time-stamped episodes."""
    b = _brain(ctx)
    files, chunks = b.ingest_summaries(ctx.obj["config"]["summary_dir"], embed=False)
    click.echo(f"Indexed {files} changed summaries ({chunks} chunks).")
    if embed:
        click.echo(f"Embedded {b.embed_missing('episodes')} episode chunks.")
    click.echo(json.dumps(b.stats()))


@main.command()
@click.option("--project", "-p", default=None)
@click.option("--since", "-s", default=None, help="today | yesterday | 7d | YYYY-MM-DD")
@click.option("--until", "-u", default=None)
@click.option("--query", "-q", default=None)
@click.option("--limit", "-n", default=10)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def timeline(ctx, project, since, until, query, limit, as_json):
    """What happened when: sessions in a time window."""
    items = _brain(ctx).timeline(project, _since(since), _since(until), query, limit)
    if as_json:
        click.echo(json.dumps(items, indent=2))
        return
    for it in items:
        click.echo(f"\n[{it['day']}] {it['project']} — {it['title']}")
        click.echo("  " + it["overview"].replace("\n", "\n  "))
        for r in it["recent"]:
            click.echo(f"    {r}")
        if it.get("match"):
            click.echo("  match: " + it["match"][:200].replace("\n", " "))


@main.command()
@click.argument("query")
@click.option("--project", "-p", default=None)
@click.option("--kind", "-k", default=None)
@click.option("--limit", "-n", default=8)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def recall(ctx, query, project, kind, limit, as_json):
    """Recall facts (hybrid BM25 + embeddings, ranked)."""
    hits = _brain(ctx).recall(query, project=project, kind=kind, limit=limit, touch=False)
    if as_json:
        click.echo(json.dumps(hits, indent=2))
        return
    for h in hits:
        click.echo(f"#{h['id']} [{h['kind']}/{h['project']} {h['date']}] {h['text']}")


@main.command()
@click.argument("text")
@click.option("--kind", "-k", default="fact")
@click.option("--project", "-p", default="global")
@click.option("--importance", "-i", default=2)
@click.pass_context
def remember(ctx, text, kind, project, importance):
    """Store one fact (deduplicated)."""
    fid, op = _brain(ctx).add_fact(text, kind=kind, project=project, importance=importance, source="cli")
    click.echo(f"{op} #{fid}")


@main.command()
@click.argument("alias")
@click.argument("canonical")
@click.pass_context
def alias(ctx, alias, canonical):
    """Map an entity alias to its canonical name (query expansion)."""
    _brain(ctx).add_alias(alias, canonical)
    click.echo(f"{alias} -> {canonical}")


@main.command("migrate-v3")
@click.option("--apply", "do_apply", is_flag=True, help="Write facts (default: dry run)")
@click.pass_context
def migrate_v3(ctx, do_apply):
    """Migrate llm-wiki pages into brain.db facts (lossless; pages untouched)."""
    from collections import Counter
    from .migrate_v3 import plan, apply
    cfg = ctx.obj["config"]
    facts = plan(cfg["wiki_dir"])
    click.echo(f"{len(facts)} candidate facts: {dict(Counter(f['kind'] for f in facts))}")
    if not do_apply:
        click.echo("Dry run. Re-run with --apply to write.")
        return
    b = _brain(ctx)
    click.echo(json.dumps(apply(b, facts)))
    click.echo(f"Indexed {b.index_docs(cfg['wiki_dir'])} doc chunks from skills/.")
    click.echo(json.dumps(b.stats()))


@main.command("brain-stats")
@click.pass_context
def brain_stats(ctx):
    """Counts in brain.db."""
    click.echo(json.dumps(_brain(ctx).stats(), indent=2))


@main.command("render")
@click.option("--no-commit", is_flag=True, help="Write pages but don't git-commit the wiki")
@click.pass_context
def render_cmd(ctx, no_commit):
    """Render live facts into the wiki (generated view; pages <= 25 KB)."""
    from .render import render
    click.echo(json.dumps(render(ctx.obj["config"], brain=_brain(ctx), commit=not no_commit)))


@main.command("sleep")
@click.option("--dry-run", is_flag=True, help="Count clusters / long facts, no LLM calls")
@click.option("--max-calls", default=60, show_default=True)
@click.pass_context
def sleep_cmd(ctx, dry_run, max_calls):
    """Merge near-duplicate facts and shorten long ones (originals kept)."""
    from .daemon import _call_api
    from .memory_ops import sleep
    click.echo(json.dumps(sleep(ctx.obj["config"], _call_api, brain=_brain(ctx), dry_run=dry_run,
                                max_calls=max_calls)))


@main.command()
@click.pass_context
def mcp(ctx):
    """Run the MCP stdio server."""
    from .mcp_server import run_mcp
    run_mcp(ctx.obj["config"])


@main.command()
@click.option("--yes", "-y", is_flag=True, help="No prompts: accept every default")
@click.option("--no-service", is_flag=True, help="Don't install the background service")
@click.option("--no-mcp", is_flag=True, help="Don't register the MCP server with agents")
@click.option("--no-pi-extension", is_flag=True, help="Don't link the Pi auto-recall extension")
def init(yes, no_service, no_mcp, no_pi_extension):
    """Set up this machine: config, providers, embeddings, service, MCP, Pi extension. Safe to re-run."""
    from .installer import run_init
    run_init(yes, service=not no_service, mcp=not no_mcp, pi_extension=not no_pi_extension)


@main.command()
def doctor():
    """Check the install: providers, embeddings, daemon, MCP registrations, Pi extension."""
    from .installer import run_doctor
    sys.exit(run_doctor())


@main.command()
@click.option("--purge", is_flag=True, help="Also delete ~/.cc-brain (all memory)")
@click.option("--yes", "-y", is_flag=True)
def uninstall(purge, yes):
    """Remove the service, MCP registrations and Pi extension. Keeps memory unless --purge."""
    from .installer import run_uninstall
    run_uninstall(purge, yes)
