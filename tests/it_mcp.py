"""MCP end-to-end over real stdio against a COPY of the live brain.db."""

import asyncio
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

LIVE = Path.home() / ".cc-brain" / "brain.db"
# Content probes depend on YOUR memory: tests/local/mcp_probes.json (gitignored), shape as in the example.
_probes = Path(__file__).parent / "local" / "mcp_probes.json"
P = json.loads((_probes if _probes.exists() else Path(__file__).parent / "mcp_probes.example.json").read_text())


async def main():
    tmp = Path(tempfile.mkdtemp())
    db = tmp / "brain.db"
    src = sqlite3.connect(LIVE)
    src.backup(sqlite3.connect(db))  # consistent snapshot even while the daemon writes
    cfg = tmp / "config.json"
    live_cfg = json.loads((Path.home() / ".cc-brain" / "config.json").read_text())
    live_cfg["brain_db"] = str(db)
    cfg.write_text(json.dumps(live_cfg))

    params = StdioServerParameters(command="cc-brain", args=["-c", str(cfg), "mcp"])
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        names = {t.name for t in (await s.list_tools()).tools}
        assert {"recall", "timeline", "remember", "correct", "forget", "wiki_search"} <= names, names

        async def call(name, **args):
            res = await s.call_tool(name, args)
            return res.content[0].text

        out = await call("recall", query=P["recall"][0])
        assert P["recall"][1] in out, out
        print("recall ok:", len(out), "bytes")

        out = await call("timeline", since=P["timeline_day"], until=P["timeline_day"])
        assert P["timeline_expect"] in out, out[:300]
        print("timeline ok:", len(out), "bytes")

        out = await call("remember", text="cc-brain it_mcp probe: zebra-quartz-17 is the test token", kind="note")
        assert out.startswith("ADD fact #"), out
        fid = int(out.split("#")[1].split()[0])
        again = await call("remember", text="cc-brain it_mcp probe: zebra-quartz-17 is the test token", kind="note")
        assert again.startswith("NOOP"), again
        print("remember/dedup ok:", out, "|", again)

        out = await call("correct", id=fid, text="cc-brain it_mcp probe: zebra-quartz-18 is the test token")
        assert "superseded" in out, out
        rec = await call("recall", query="zebra quartz test token")
        assert "zebra-quartz-18" in rec and "zebra-quartz-17" not in rec, rec
        print("correct ok: old retired, new recalled")

        out = await call("remember", text="api_key = 'sk-abcdefghijklmnopqrstuvwxyz123'")
        assert out.startswith("Rejected"), out

        out = await call("wiki_search", query=P["search"])
        data = json.loads(out)
        assert data["facts"] and "episodes" in data, out[:300]
        print("wiki_search ok:", len(out), "bytes", {k: len(v) for k, v in data.items()})
    print("PASS")


asyncio.run(main())
