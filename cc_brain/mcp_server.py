"""MCP stdio server exposing cc-brain tools to agents."""

import json
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .config import load_config, get_llm_config
from .queue import enqueue
from .search import WikiSearch


def run_mcp(config=None):
    """Run the MCP server over stdio."""
    if config is None:
        config = load_config()

    server = Server("cc-brain")
    wiki_dir = Path(config.get("wiki_dir", str(Path.home() / "llm-wiki")))
    search = WikiSearch(config["search_db"], str(wiki_dir))

    # Ensure index exists
    if search.page_count() == 0:
        search.rebuild()

    @server.list_tools()
    async def list_tools():
        return [
            Tool(
                name="wiki_search",
                description="Search the llm-wiki knowledge base",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "scope": {"type": "string", "description": "Scope: projects, skills, failures, identity, or all"},
                        "limit": {"type": "integer", "default": 5},
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="wiki_read",
                description="Read a wiki page by path",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Wiki page path relative to llm-wiki root"},
                    },
                    "required": ["path"],
                },
            ),
            Tool(
                name="wiki_suggest",
                description="Queue a knowledge suggestion for review and merging into the wiki",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "target": {"type": "string", "description": "Target page (e.g. projects/brain.md) or 'auto'"},
                        "content": {"type": "string", "description": "Knowledge to add"},
                        "type": {"type": "string", "enum": ["add", "update", "correction"], "default": "add"},
                    },
                    "required": ["target", "content"],
                },
            ),
            Tool(
                name="wiki_list",
                description="List wiki pages, optionally filtered by directory",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "directory": {"type": "string", "description": "Subdirectory to list (projects, skills, failures, identity)"},
                    },
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name, arguments):
        if name == "wiki_search":
            results = search.search(
                arguments["query"],
                limit=arguments.get("limit", 5),
                scope=arguments.get("scope"),
            )
            return [TextContent(type="text", text=json.dumps(results, indent=2))]

        elif name == "wiki_read":
            page_path = wiki_dir / arguments["path"]
            if not page_path.exists():
                return [TextContent(type="text", text=f"Page not found: {arguments['path']}")]
            # Prevent path traversal
            try:
                page_path.resolve().relative_to(wiki_dir.resolve())
            except ValueError:
                return [TextContent(type="text", text="Access denied: path outside wiki")]
            text = page_path.read_text()
            return [TextContent(type="text", text=text)]

        elif name == "wiki_suggest":
            sid, err = enqueue(
                config["queue_dir"],
                arguments["target"],
                arguments["content"],
                arguments.get("type", "add"),
            )
            if err:
                return [TextContent(type="text", text=f"Rejected: {err}")]
            return [TextContent(type="text", text=f"Queued suggestion {sid[:8]}")]

        elif name == "wiki_list":
            subdir = arguments.get("directory", "")
            base = wiki_dir / subdir if subdir else wiki_dir
            if not base.exists():
                return [TextContent(type="text", text=f"Directory not found: {subdir}")]
            pages = sorted(str(p.relative_to(wiki_dir)) for p in base.rglob("*.md"))
            return [TextContent(type="text", text="\n".join(pages) if pages else "No pages found")]

        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    import asyncio

    async def _run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(_run())
