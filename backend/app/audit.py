"""Audit log of host-tool calls (#115): what ran on this machine, when, and who approved it.

The agent timeline lives with the chat, so a deleted chat, a fork or compaction loses it. This
log does not: one JSON line per event, appended by the backend to `CALIVI_AUDIT_LOG`
(`/var/log/calivi/host-tools.jsonl` on calivi-vm, empty — off — everywhere else).

**Two lines per call.** A `call` line before the tool runs (tool, arguments, approval) and a
`result` line after it (ok, exit code, output hash and size, duration), joined by `id`. Written
before, because the command that matters most is the one that never comes back: a
`systemctl restart calivi`, a reboot, a backend that dies mid-call. A `call` with no `result`
is exactly that record.

**Hashes, not content.** The output, and the file content `write_file` / `edit_file` carry, are
recorded as sha256 + size: tool output and config files hold secrets, and a log that keeps them
is a second copy nobody rotates out of mind. The command itself and the paths are recorded
verbatim — they are what the record is for.

**A seatbelt, like the approval policy.** The file belongs to the service account in a `0750`
directory, so the owner's account — the one the model's commands run as — cannot write it
without sudo. It has sudo by design. The log survives the chat; it does not survive a model
that sets out to erase it.

**A write that fails does not stop the tool.** It is logged to the journal instead. Refusing
every host call because `/var/log` is full would turn a full disk into a machine the owner
can no longer repair through the chat.
"""
import hashlib
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

from app import config

log = logging.getLogger(__name__)

FORMAT_VERSION = 1
# Arguments that carry file content rather than say what to do — hashed like the output.
_CONTENT_ARGS = {"write_file": ("content",), "edit_file": ("old_string", "new_string")}
_READ_TAIL_BYTES = 8 * 1024 * 1024  # per file; older lines stay on disk for journalctl-style reading
MAX_LIMIT = 1000


def enabled() -> bool:
    return bool(config.AUDIT_LOG_FILE)


def digest(text: str) -> dict:
    data = text.encode(errors="replace")
    return {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


def _recorded_args(tool: str, args: dict) -> dict:
    out = dict(args or {})
    for key in _CONTENT_ARGS.get(tool, ()):
        if isinstance(out.get(key), str):
            out[key] = digest(out[key])
    return out


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _append(entry: dict) -> None:
    path = config.AUDIT_LOG_FILE
    if not path:
        return
    line = (json.dumps({"v": FORMAT_VERSION, "ts": _now(), **entry}, ensure_ascii=False,
                       separators=(",", ":"), default=str) + "\n").encode()
    try:
        # One write() on an O_APPEND descriptor: concurrent turns cannot interleave inside a line.
        # Opened per event, so logrotate needs no signal and no copytruncate.
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except OSError as e:
        log.warning("audit log %s not written: %s", path, e)


def record_call(*, chat_id: int, user_id: int | None, server: str, model: str, tool: str,
                args: dict, approval: str) -> str | None:
    """Writes the `call` line and returns its id (None when the log is off).

    `approval`: `auto` (no card was needed), `owner` (the owner said yes) or `denied` (said no,
    or let it time out — the tool does not run, and no `result` line follows).
    """
    if not enabled():
        return None
    call_id = uuid.uuid4().hex
    _append({
        "event": "call", "id": call_id, "chat": chat_id, "user": user_id, "server": server,
        "model": model, "tool": tool, "args": _recorded_args(tool, args), "approval": approval,
    })
    return call_id


def record_result(call_id: str | None, result: str, ok: bool, started: float,
                  cancelled: bool = False) -> None:
    """The `result` line. `cancelled`: the owner pressed Stop while it ran (no output kept)."""
    if call_id is None:
        return
    entry = {"event": "result", "id": call_id, "ok": ok, "exit": getattr(result, "exit_code", None)}
    if cancelled:
        entry["cancelled"] = True
    else:
        entry["output"] = digest(str(result))
    entry["ms"] = round((time.monotonic() - started) * 1000)
    _append(entry)


def _tail_lines(path: str) -> list[str]:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - _READ_TAIL_BYTES))
            data = f.read()
    except OSError:
        return []
    lines = data.decode(errors="replace").splitlines()
    if size > _READ_TAIL_BYTES and lines:
        lines = lines[1:]  # the first one was cut by the seek
    return lines


def read(chat_id: int | None = None, tool: str | None = None, limit: int = 200) -> list[dict]:
    """The calls, newest first, each with its `result` merged in (None if it never came back).

    Reads the live file and the previous rotation (`.1`, kept uncompressed by `delaycompress`);
    anything older is on disk for the owner to read by hand.
    """
    path = config.AUDIT_LOG_FILE
    if not path:
        return []
    calls: dict[str, dict] = {}
    for name in (f"{path}.1", path):
        for line in _tail_lines(name):
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                continue
            if entry.get("event") == "call":
                calls[entry["id"]] = {**entry, "result": None}
            elif entry.get("event") == "result" and entry["id"] in calls:
                calls[entry["id"]]["result"] = {
                    k: entry.get(k) for k in ("ts", "ok", "exit", "output", "ms", "cancelled")
                }
    # File order is time order (appends, oldest file first); timestamps can tie at the millisecond.
    rows = [c for c in reversed(calls.values())
            if (chat_id is None or c.get("chat") == chat_id) and (tool is None or c.get("tool") == tool)]
    return rows[:max(1, min(limit, MAX_LIMIT))]
