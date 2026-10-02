"""Provider chain against the real providers (agy Gemini, Meridian Sonnet). Needs both running.

1. agy answers a JSON task first, output parses.
2. agy unusable (missing binary) -> HardFail -> cooldown -> Meridian answers.
3. Cooled-down provider is skipped on the next call (no second agy attempt logged).
4. Truncated output (tiny max_tokens) returns None + meta.truncated and does NOT fall through.
5. Every attempt lands in ~/.cc-brain/logs/llm.jsonl.
"""

import http.server
import json
import threading
import time

from cc_brain import llm
from cc_brain.config import load_config
from cc_brain.consolidator import _parse_json

cfg = load_config()
chain = cfg["llm"]["chain"]
agy = next(p for p in chain if p["type"] == "agy")
meridian = next(p for p in chain if p["name"] == "meridian")
MSG = [{"role": "system", "content": 'Return JSON: {"ops": [{"op": "ADD", "text": "<fact>"}]} with one fact.'},
       {"role": "user", "content": "Session: we learned glab api needs --jq not | jq when the token is in a pipe."}]


def log_since(t0):
    return [e for e in map(json.loads, llm.LOG.read_text().splitlines()) if e["ts"] >= int(t0)]


t0 = time.time()
meta = {}
out = llm.call_api(dict(cfg, llm=dict(cfg["llm"], chain=[agy, meridian])), MSG, task="consolidation",
                   json_mode=True, meta=meta)
assert meta["provider"] == "agy" and _parse_json(out)["ops"], (meta, out)
print(f"1 agy ok ({time.time() - t0:.0f}s):", out[:120].replace("\n", " "))

t1 = time.time()
broken = dict(agy, name="agy-broken", bin="/nonexistent/agy")
c2 = dict(cfg, llm=dict(cfg["llm"], chain=[broken, meridian]))
meta = {}
out = llm.call_api(c2, MSG, task="consolidation", json_mode=True, meta=meta)
assert meta["provider"] == "meridian" and _parse_json(out)["ops"], (meta, out)
assert llm._cooldown.get("agy-broken", 0) > time.time()
print(f"2 fallback ok ({time.time() - t1:.0f}s): agy-broken hardfail -> meridian")

meta = {}
out = llm.call_api(c2, MSG, task="consolidation", json_mode=True, meta=meta)
attempts = [e["provider"] for e in log_since(t1)]
assert attempts.count("agy-broken") == 1 and meta["provider"] == "meridian", attempts
print("3 cooldown ok:", attempts)

# Meridian ignores max_tokens (never truncates), so the length path is exercised with a local stub
class Stub(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        body = json.dumps({"choices": [{"finish_reason": "length", "message": {"content": '{"ops": [{"op'}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


srv = http.server.HTTPServer(("127.0.0.1", 0), Stub)
threading.Thread(target=srv.serve_forever, daemon=True).start()
stub = {"name": "stub", "type": "openai", "api_base_url": f"http://127.0.0.1:{srv.server_port}/v1", "model": "x"}
t3 = time.time()
meta = {}
out = llm.call_api(dict(cfg, llm=dict(cfg["llm"], chain=[stub, agy])), MSG, task="consolidation", meta=meta)
srv.shutdown()
assert out is None and meta.get("truncated"), (out, meta)
assert [e["provider"] for e in log_since(t3)] == ["stub"], "truncation must not fall through"
print("4 truncation ok: None + truncated, chain stopped")

statuses = [(e["provider"], e["status"][:20], e["secs"]) for e in log_since(t0)]
assert len(statuses) >= 5, statuses
print("5 log ok:", statuses)
print("PASS")
