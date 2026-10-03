"""Audit log of host-tool calls (audit.py, #115).

The file format, the hashing of content and output, the loop writing a `call` line before the
tool runs and a `result` line after it, and the owner-only Activity endpoint.
"""
import asyncio
import json

import pytest

from app import approvals, audit, config, llm, models, tools_config, turns
from app.database import SessionLocal
from app.routers.chats import build_stream_response
from app.tools import host
from app.tools.registry import Tool, ToolResult, registry
from tests.conftest import register

TARGET = {"name": "s", "type": "ollama", "host": "h", "port": 1, "base_url": None, "api_key": None}
SECRET = "hunter2-very-secret"


@pytest.fixture
def log_file(tmp_path, monkeypatch):
    path = tmp_path / "host-tools.jsonl"
    monkeypatch.setattr(config, "AUDIT_LOG_FILE", str(path))
    return path


def _lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


# --- the file -------------------------------------------------------------------------------


def test_off_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AUDIT_LOG_FILE", "")
    assert audit.record_call(chat_id=1, user_id=1, server="s", model="m", tool="bash",
                             args={"command": "ls"}, approval="auto") is None
    assert list(tmp_path.iterdir()) == []


def test_call_and_result_lines(log_file):
    call_id = audit.record_call(chat_id=3, user_id=1, server="s", model="m", tool="bash",
                                args={"command": "uptime"}, approval="owner")
    audit.record_result(call_id, ToolResult(f"exit code: 0\n\n{SECRET}", exit_code=0), True, 0.0)
    call, result = _lines(log_file)
    assert call["event"] == "call" and call["id"] == call_id
    assert call["args"] == {"command": "uptime"}  # the command itself is the record
    assert (call["chat"], call["tool"], call["approval"]) == (3, "bash", "owner")
    assert result["event"] == "result" and result["id"] == call_id
    assert result["exit"] == 0 and result["ok"] is True
    assert result["output"]["size"] == len(f"exit code: 0\n\n{SECRET}")
    assert SECRET not in log_file.read_text()  # output is hashed, never kept


def test_file_content_is_hashed(log_file):
    audit.record_call(chat_id=1, user_id=1, server="s", model="m", tool="write_file",
                      args={"path": "~/.env", "content": f"TOKEN={SECRET}"}, approval="auto")
    audit.record_call(chat_id=1, user_id=1, server="s", model="m", tool="edit_file",
                      args={"path": "~/a", "old_string": SECRET, "new_string": SECRET + "x"},
                      approval="auto")
    text = log_file.read_text()
    assert SECRET not in text
    write, edit = _lines(log_file)
    assert write["args"]["path"] == "~/.env"
    assert set(write["args"]["content"]) == {"sha256", "size"}
    assert set(edit["args"]["new_string"]) == {"sha256", "size"}


def test_a_failed_write_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AUDIT_LOG_FILE", str(tmp_path / "missing-dir" / "x.jsonl"))
    call_id = audit.record_call(chat_id=1, user_id=1, server="s", model="m", tool="bash",
                                args={}, approval="auto")
    audit.record_result(call_id, "x", True, 0.0)  # nothing to assert: it must simply not raise


def test_read_merges_filters_and_includes_the_previous_rotation(log_file):
    old = audit.record_call(chat_id=1, user_id=1, server="s", model="m", tool="bash",
                            args={"command": "old"}, approval="auto")
    audit.record_result(old, "x", True, 0.0)
    log_file.rename(str(log_file) + ".1")  # what logrotate does
    lost = audit.record_call(chat_id=2, user_id=1, server="s", model="m", tool="bash",
                             args={"command": "systemctl restart calivi"}, approval="auto")
    audit.record_call(chat_id=2, user_id=1, server="s", model="m", tool="read_file",
                      args={"path": "/etc/hosts"}, approval="auto")
    with open(log_file, "a") as f:
        f.write("not json\n")  # a torn line must not break the view

    rows = audit.read()
    assert [r["args"].get("command") or r["args"].get("path") for r in rows] == [
        "/etc/hosts", "systemctl restart calivi", "old"]
    assert rows[2]["result"]["ok"] is True
    assert next(r for r in rows if r["id"] == lost)["result"] is None  # never came back
    assert [r["tool"] for r in audit.read(tool="read_file")] == ["read_file"]
    assert [r["args"]["command"] for r in audit.read(chat_id=1)] == ["old"]
    assert len(audit.read(limit=1)) == 1


# --- the loop -------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def tools_on(monkeypatch):
    monkeypatch.setattr(tools_config, "is_enabled", lambda: True)
    monkeypatch.setattr(tools_config, "tool_enabled", lambda name: True)


@pytest.fixture
def fake_host_tool():
    """A host-source tool whose risk is in its arguments, like bash."""
    ran = []

    async def handler(args):
        ran.append(args)
        if args.get("hang"):
            await asyncio.sleep(3600)
        return ToolResult("exit code: 3\n\nout", exit_code=3)

    registry.register(Tool(
        name="host_test_tool", description="d", parameters={"type": "object", "properties": {}},
        handler=handler, source=host.SOURCE, privileged=True,
        needs_approval=lambda a: bool(a.get("risky")),
    ))
    yield ran
    registry._tools.pop("host_test_tool", None)


@pytest.fixture
def plain_tool():
    async def handler(args):
        return "ran"

    registry.register(Tool(name="plain_test_tool", description="d",
                           parameters={"type": "object", "properties": {}}, handler=handler))
    yield
    registry._tools.pop("plain_test_tool", None)


@pytest.fixture
def owner_chat():
    db = SessionLocal()
    try:
        u = models.User(email="o@test.local", username="o", password_hash="x", role="admin")
        db.add(u)
        db.commit()
        c = models.Chat(user_id=u.id, title="t")
        db.add(c)
        db.commit()
        return u.id, c.id
    finally:
        db.close()


async def _drive(monkeypatch, user_id, chat_id, name, args, decide=True):
    turns = [
        [{"type": "tool_calls", "calls": [{"id": "c1", "name": name, "arguments": args}]}],
        [{"type": "content", "text": "done"}],
    ]

    async def stream_chat(target, model, messages, tools=None):
        for piece in turns.pop(0) if turns else []:
            yield piece

    monkeypatch.setattr(llm, "stream_chat", stream_chat)
    resp = build_stream_response(chat_id, TARGET, "m", [{"role": "user", "content": "hi"}],
                                 use_tools=True, user_id=user_id)
    async for chunk in resp.body_iterator:
        for line in chunk.splitlines():
            if line.strip():
                event = json.loads(line)
                if event["type"] == "approval_request":
                    assert approvals.resolve(event["id"], chat_id, user_id, decide)


async def test_loop_records_an_auto_call(monkeypatch, log_file, owner_chat, fake_host_tool):
    await _drive(monkeypatch, *owner_chat, "host_test_tool", {"n": 1})
    call, result = _lines(log_file)
    assert (call["tool"], call["args"], call["approval"]) == ("host_test_tool", {"n": 1}, "auto")
    assert (call["chat"], call["user"], call["model"], call["server"]) == (owner_chat[1], 1, "m", "s")
    assert (result["id"], result["exit"], result["ok"]) == (call["id"], 3, True)


async def test_loop_records_the_owners_yes(monkeypatch, log_file, owner_chat, fake_host_tool):
    await _drive(monkeypatch, *owner_chat, "host_test_tool", {"risky": True}, decide=True)
    call, result = _lines(log_file)
    assert call["approval"] == "owner" and result["ok"] is True
    assert fake_host_tool == [{"risky": True}]


async def test_loop_records_a_denial_and_nothing_ran(monkeypatch, log_file, owner_chat, fake_host_tool):
    await _drive(monkeypatch, *owner_chat, "host_test_tool", {"risky": True}, decide=False)
    (call,) = _lines(log_file)
    assert call["approval"] == "denied"
    assert fake_host_tool == []


async def test_loop_leaves_other_tools_out(monkeypatch, log_file, owner_chat, plain_tool):
    await _drive(monkeypatch, *owner_chat, "plain_test_tool", {})
    assert not log_file.exists()


async def test_the_call_line_is_written_before_the_tool_runs(
    monkeypatch, log_file, owner_chat, fake_host_tool
):
    """A command that never returns (a restart of Calivi itself) must still be on record; and
    Stop while it runs is recorded as a cancellation, not as silence."""
    user_id, chat_id = owner_chat
    task = asyncio.create_task(_drive(monkeypatch, user_id, chat_id, "host_test_tool", {"hang": True}))
    for _ in range(200):
        await asyncio.sleep(0.01)
        if fake_host_tool:
            break
    (call,) = _lines(log_file)  # already there while the tool is still running
    assert call["args"] == {"hang": True}
    assert turns.cancel(chat_id)  # Stop
    await asyncio.wait_for(task, 5)
    _, result = _lines(log_file)
    assert result["cancelled"] is True and result["ok"] is False


async def test_bash_reports_its_exit_code(tmp_path, monkeypatch):
    import getpass
    monkeypatch.setattr(host, "_account", lambda: (getpass.getuser(), str(tmp_path)))
    bash = next(t for t in host.TOOLS if t.name == "bash")
    assert (await bash.handler({"command": "exit 7"})).exit_code == 7


# --- the endpoint ---------------------------------------------------------------------------


async def test_activity_is_the_owners_alone(admin, user_client, monkeypatch, log_file):
    await register(user_client, "bob")
    db = SessionLocal()
    try:
        chat = models.Chat(user_id=1, title="disk cleanup")
        bobs = models.Chat(user_id=2, title="bob's private chat")
        db.add_all([chat, bobs])
        db.commit()
        chat_id, bobs_id = chat.id, bobs.id
    finally:
        db.close()
    audit.record_call(chat_id=chat_id, user_id=1, server="s", model="m", tool="bash",
                      args={"command": "df -h"}, approval="auto")
    audit.record_call(chat_id=999, user_id=1, server="s", model="m", tool="bash",
                      args={"command": "ls"}, approval="auto")
    audit.record_call(chat_id=bobs_id, user_id=1, server="s", model="m", tool="bash",
                      args={"command": "pwd"}, approval="auto")

    monkeypatch.setattr(config, "HOST_TOOLS_ENABLED", False)
    assert (await admin.get("/api/activity")).status_code == 404  # no host tools, no route

    monkeypatch.setattr(config, "HOST_TOOLS_ENABLED", True)
    assert (await user_client.get("/api/activity")).status_code == 404  # not the owner
    resp = await admin.get("/api/activity")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    titles = {e["args"]["command"]: e["chat_title"] for e in body["entries"]}
    assert titles == {"df -h": "disk cleanup", "ls": None,  # a deleted chat keeps only its id
                      "pwd": None}  # another user's chat title never shows
    only = (await admin.get(f"/api/activity?chat_id={chat_id}")).json()["entries"]
    assert [e["args"]["command"] for e in only] == ["df -h"]
