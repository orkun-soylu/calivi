#!/usr/bin/env python3
"""A scripted OpenAI-compatible model server for the install tests (#95). Standard library only.

The last user message is the script:

    RUN: <command>   → the first reply is a `bash` tool call with that command; once the tool
                       result is in, the reply is "ran: " + the first line of that result
    SLOW: <seconds>  → the reply streams one word a second for that long, then "finished"
    NOTES?           → "notes: " + the first line of the machine notes in the system layer
                       (#110), or "notes: none"
    anything else    → "ok"

    fake_model.py [port]     (default 8099, bound to 127.0.0.1 — a QEMU user-network guest
                              reaches it as 10.0.2.2)
"""
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = "fake"


def _last_user(messages):
    for m in reversed(messages):
        if m.get("role") == "user":
            c = m.get("content")
            return c if isinstance(c, str) else ""
    return ""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("fake-model: " + fmt % args + "\n")

    def do_GET(self):
        if self.path.rstrip("/") != "/v1/models":
            self.send_error(404)
            return
        body = json.dumps({"object": "list", "data": [{"id": MODEL, "object": "model"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path.rstrip("/") != "/v1/chat/completions":
            self.send_error(404)
            return
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        messages = req.get("messages") or []
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()

        script = _last_user(messages).strip()
        if messages and messages[-1].get("role") == "tool":
            result = messages[-1].get("content") or ""
            # calivi wraps tool output as untrusted text; the proof line is inside it.
            line = next((ln for ln in result.splitlines() if ln.startswith("proof:")), result[:200])
            self._text("ran: " + line)
        elif script.startswith("RUN:") and req.get("tools"):
            self._tool_call("bash", {"command": script[4:].strip()})
        elif script == "NOTES?":
            system = next((m.get("content") or "" for m in messages if m.get("role") == "system"), "")
            marker = "----- ~/.calivi/AGENTS.md -----\n"
            first = system.split(marker, 1)[1].splitlines()[0] if marker in system else "none"
            self._text("notes: " + first)
        elif script.startswith("SLOW:"):
            for i in range(int(script[5:].strip())):
                self._chunk({"content": f"w{i} "})
                time.sleep(1)
            self._text("finished")
        else:
            self._text("ok")
        self._done()

    def _chunk(self, delta, finish=None):
        data = {"id": "x", "object": "chat.completion.chunk", "model": MODEL,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
        self.wfile.write(f"data: {json.dumps(data)}\n\n".encode())
        self.wfile.flush()

    def _text(self, text):
        self._chunk({"role": "assistant", "content": text})
        self._chunk({}, "stop")

    def _tool_call(self, name, args):
        self._chunk({"role": "assistant", "tool_calls": [
            {"index": 0, "id": "call_1", "type": "function",
             "function": {"name": name, "arguments": json.dumps(args)}}]})
        self._chunk({}, "tool_calls")

    def _done(self):
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
