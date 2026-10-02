import json, threading, time, tempfile, os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from cc_brain import daemon
from cc_brain.pi_sessions import PiSessionTracker

calls = []
MODE = {"seq": ["length", "length"]}
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        calls.append(body["messages"][0]["content"][-120:])
        fr = MODE["seq"].pop(0) if MODE["seq"] else "stop"
        out = {"choices": [{"finish_reason": fr, "message": {"content": "# PARTIAL CUT" if fr == "length" else "# new summary\n## Goal\nok"}}]}
        data = json.dumps(out).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def log_message(self, *a): pass
srv = HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()

tmp = Path(tempfile.mkdtemp())
cfg = {"summary_dir": str(tmp), "state_dir": str(tmp), "llm": {"default": {"api_base_url": f"http://127.0.0.1:{srv.server_port}", "model": "x"}}}
sess = tmp / "s.jsonl"
sess.write_text(json.dumps({"type": "session", "cwd": str(Path.home() / "code" / "example-app"), "id": "abc", "timestamp": "2026-10-01T10:00:00Z"}) + "\n"
                + json.dumps({"type": "message", "timestamp": "2026-10-01T10:01:00Z", "message": {"role": "user", "content": "hello work"}}) + "\n")
t = PiSessionTracker(cfg, daemon._call_api, lambda *a, **k: None)
from cc_brain.pi_sessions import _header, _summary_path
sp = _summary_path(cfg, _header(sess), sess); sp.write_text("# GOOD OLD SUMMARY\n")

t._summarize(str(sess))
print("case1 both truncated: calls=%d, file=%r, offset_saved=%s" % (len(calls), sp.read_text().strip(), str(sess) in t._offsets))
assert sp.read_text() == "# GOOD OLD SUMMARY\n" and len(calls) == 2 and "Compress harder" in calls[1]

calls.clear(); MODE["seq"] = ["length"]
t._summarize(str(sess))
print("case2 retry succeeds: calls=%d, file=%r" % (len(calls), sp.read_text().strip()[:20]))
assert sp.read_text().startswith("# new summary") and len(calls) == 2
print("PASS")
