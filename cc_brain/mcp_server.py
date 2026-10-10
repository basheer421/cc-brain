"""MCP stdio server exposing cc-brain memory to agents.

v3 tools return small, ranked results (~2 KB) so agents can afford to query constantly:
  recall   — durable facts (pitfalls, decisions, preferences, corrections...)
  timeline — what happened when (session episodes)
  remember / correct / forget — write path (deterministic dedup, no LLM in this process)
v2 tools kept for compatibility: wiki_search (now = recall + docs + episodes), wiki_read,
wiki_list, wiki_suggest (now writes a fact directly).
"""

import json
import re
from datetime import date, timedelta
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .brain import KINDS, Brain
from .config import load_config
from .queue import _has_secrets

RECALL_DESC = (
    "IMPORTANT: query this BEFORE suggesting, planning, debugging or asking the user about past work. "
    "Searches the user's long-term memory: atomic facts (pitfalls, decisions, preferences, corrections, "
    "people, procedures) ranked by relevance x recency x importance. Hybrid keyword + semantic, entity "
    "aliases expanded. Returns ~8 short facts (~2 KB) — cheap, call it often with 2-3 phrasings."
)
TIMELINE_DESC = (
    "Episodic memory: what happened in past agent sessions, by time. Use for 'what did I do yesterday / "
    "this week', 'where did we leave X', 'when did we decide Y'. since/until accept today, yesterday, "
    "7d, or YYYY-MM-DD. Add query to rank sessions by topic instead of time."
)


def _day(value):
    if not value:
        return None
    v = str(value).strip().lower()
    if v == "today":
        return date.today().isoformat()
    if v == "yesterday":
        return (date.today() - timedelta(days=1)).isoformat()
    if re.fullmatch(r"\d+d", v):
        return (date.today() - timedelta(days=int(v[:-1]))).isoformat()
    return value


def _kind_from_target(target):
    stem = Path(target or "").stem.lower()
    for k in KINDS:
        if k in stem:
            return k
    if "quirk" in stem or "failure" in stem:
        return "pitfall"
    if target and target.startswith("identity/"):
        return "preference"
    return "fact"


def _project_from_target(target):
    if target and target.startswith("projects/"):
        return re.sub(r"-memory$", "", Path(target).stem)
    return "global"


def _text(obj):
    return [TextContent(type="text", text=obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False))]


def run_mcp(config=None):
    if config is None:
        config = load_config()

    server = Server("cc-brain")
    wiki_dir = Path(config.get("wiki_dir", str(Path.home() / "llm-wiki")))
    brain = Brain(config["brain_db"], config)

    proj_prop = {"type": "string", "description": "Repo slug to boost, e.g. my-api, web (optional)"}

    @server.list_tools()
    async def list_tools():
        return [
            Tool(name="recall", description=RECALL_DESC, inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Concrete terms: names, repo, error text, task"},
                    "project": proj_prop,
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "limit": {"type": "integer", "default": 8},
                },
                "required": ["query"],
            }),
            Tool(name="timeline", description=TIMELINE_DESC, inputSchema={
                "type": "object",
                "properties": {
                    "project": proj_prop,
                    "since": {"type": "string"}, "until": {"type": "string"},
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 8},
                },
            }),
            Tool(name="remember", description=(
                "Store ONE durable fact (<=200 chars ideal: rule + why). Use for corrections from the user, "
                "tool quirks, decisions, preferences. Near-duplicates are merged automatically. No secrets."),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "kind": {"type": "string", "enum": list(KINDS), "default": "fact"},
                        "project": {"type": "string", "default": "global"},
                        "importance": {"type": "integer", "enum": [1, 2, 3], "default": 2},
                    },
                    "required": ["text"],
                }),
            Tool(name="correct", description=(
                "A recalled fact is wrong or outdated: retire fact `id` and store the corrected text "
                "(old version kept as history)."),
                inputSchema={"type": "object", "properties": {
                    "id": {"type": "integer"}, "text": {"type": "string"}}, "required": ["id", "text"]}),
            Tool(name="forget", description="Retire a fact that is no longer true and has no replacement.",
                 inputSchema={"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}),
            Tool(name="wiki_search", description=(
                "Search the brain: facts + skill docs + recent session episodes in one call. "
                "Prefer recall/timeline for focused queries."),
                inputSchema={"type": "object", "properties": {
                    "query": {"type": "string"},
                    "scope": {"type": "string", "description": "projects, skills, failures, identity, or all"},
                    "limit": {"type": "integer", "default": 5}}, "required": ["query"]}),
            Tool(name="wiki_read", description="Read a wiki page by path (generated view of the brain, or a skill doc)",
                 inputSchema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}),
            Tool(name="wiki_suggest", description="Store knowledge (compat alias of remember; target picks kind/project)",
                 inputSchema={"type": "object", "properties": {
                     "target": {"type": "string"}, "content": {"type": "string"},
                     "type": {"type": "string", "enum": ["add", "update", "correction"], "default": "add"}},
                     "required": ["target", "content"]}),
            Tool(name="wiki_list", description="List wiki pages, optionally filtered by directory",
                 inputSchema={"type": "object", "properties": {"directory": {"type": "string"}}}),
        ]

    @server.call_tool()
    async def call_tool(name, arguments):
        a = arguments or {}
        if name == "recall":
            hits = brain.recall(a["query"], project=a.get("project"), kind=a.get("kind"),
                                limit=int(a.get("limit", 8)))
            if not hits:
                return _text("No facts matched. Try other terms, or timeline(query=...).")
            return _text("\n".join(f"#{h['id']} [{h['kind']}/{h['project']} {h['date']}] {h['text']}" for h in hits))

        if name == "timeline":
            items = brain.timeline(a.get("project"), _day(a.get("since")), _day(a.get("until")),
                                   a.get("query"), int(a.get("limit", 8)))
            return _text(items or "No sessions in that window.")

        if name in ("remember", "wiki_suggest"):
            text = a.get("text") or a.get("content", "")
            if _has_secrets(text):
                return _text("Rejected: content contains potential secrets")
            if name == "wiki_suggest":
                kind = "correction" if a.get("type") == "correction" else _kind_from_target(a.get("target"))
                project, importance = _project_from_target(a.get("target")), 3 if kind == "correction" else 2
            else:
                kind, project, importance = a.get("kind", "fact"), a.get("project", "global"), int(a.get("importance", 2))
            fid, op = brain.add_fact(text, kind=kind, project=project, importance=importance, source=f"mcp:{name}")
            return _text(f"{op} fact #{fid}" + (" (already known; reinforced)" if op == "NOOP" else ""))

        if name == "correct":
            if _has_secrets(a["text"]):
                return _text("Rejected: content contains potential secrets")
            new_id = brain.supersede(int(a["id"]), a["text"], source="mcp:correct")
            return _text(f"fact #{a['id']} superseded by #{new_id}" if new_id else f"No fact #{a['id']}")

        if name == "forget":
            brain.forget(int(a["id"]))
            return _text(f"fact #{a['id']} retired")

        if name == "wiki_search":
            scope = a.get("scope")
            limit = int(a.get("limit", 5))
            out = {}
            if scope in (None, "", "all", "projects", "failures", "identity"):
                kind = {"failures": "pitfall", "identity": "preference"}.get(scope or "")
                out["facts"] = brain.recall(a["query"], kind=kind, limit=limit + 3)
            if scope in (None, "", "all", "skills"):
                out["docs"] = brain.search_docs(a["query"], limit=2 if scope != "skills" else limit)
            if scope in (None, "", "all"):
                out["episodes"] = [
                    {k: e[k] for k in ("day", "project", "overview") if k in e}
                    | ({"match": e["match"]} if e.get("match") else {})
                    for e in brain.timeline(query=a["query"], limit=3)
                ]
            return _text(out)

        if name == "wiki_read":
            page_path = wiki_dir / a["path"]
            try:
                page_path.resolve().relative_to(wiki_dir.resolve())
            except ValueError:
                return _text("Access denied: path outside wiki")
            if not page_path.exists():
                return _text(f"Page not found: {a['path']}")
            return _text(page_path.read_text())

        if name == "wiki_list":
            subdir = a.get("directory", "")
            base = wiki_dir / subdir if subdir else wiki_dir
            if not base.exists():
                return _text(f"Directory not found: {subdir}")
            pages = sorted(str(p.relative_to(wiki_dir)) for p in base.rglob("*.md"))
            return _text("\n".join(pages) if pages else "No pages found")

        return _text(f"Unknown tool: {name}")

    import asyncio

    async def _run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(_run())
