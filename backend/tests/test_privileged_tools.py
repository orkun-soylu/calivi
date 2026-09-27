"""The agentic loop's side of privileged tools and per-call approval
(routers/chats.py::build_stream_response).

The registry enforces both gates (test_tools_registry.py); these check that the loop feeds it
the right caller. Privilege is the **super admin** (id 1) alone: an ordinary admin of the same
instance must not get the host's shell.
"""
import json

import pytest

from app import approvals, llm, models, tools_config
from app.database import SessionLocal
from app.routers.chats import build_stream_response
from app.tools.registry import Tool, registry

TARGET = {"name": "s", "type": "ollama", "host": "h", "port": 1, "base_url": None, "api_key": None}


def _user(name, role):
    db = SessionLocal()
    try:
        u = models.User(email=f"{name}@test.local", username=name, password_hash="x", role=role)
        db.add(u)
        db.commit()
        return u.id
    finally:
        db.close()


def _chat(user_id):
    db = SessionLocal()
    try:
        c = models.Chat(user_id=user_id, title="t")
        db.add(c)
        db.commit()
        db.add(models.Message(chat_id=c.id, role="user", content="hi"))
        db.commit()
        return c.id
    finally:
        db.close()


@pytest.fixture
def owner():
    uid = _user("owner", "admin")
    assert uid == 1  # the rule under test is "id 1", so make sure this really is id 1
    return uid


@pytest.fixture
def other_admin(owner):
    return _user("second", "admin")


@pytest.fixture(autouse=True)
def tools_on(monkeypatch):
    monkeypatch.setattr(tools_config, "is_enabled", lambda: True)
    monkeypatch.setattr(tools_config, "tool_enabled", lambda name: True)


@pytest.fixture
def host_tool():
    ran = []

    async def handler(args):
        ran.append(args)
        return "ran"

    registry.register(Tool(
        name="host_test_shell", description="d",
        parameters={"type": "object", "properties": {}}, handler=handler,
        privileged=True, needs_approval=lambda args: args.get("cmd", "").startswith("rm"),
    ))
    yield ran
    registry._tools.pop("host_test_shell", None)


async def _drive(monkeypatch, chat_id, user_id, cmd, decide=None):
    """One turn calling host_test_shell with `cmd`, then a final answer. Returns (events,
    the tool names offered on the first turn)."""
    offered = []
    turns = [
        [{"type": "tool_calls", "calls": [
            {"id": "c1", "name": "host_test_shell", "arguments": {"cmd": cmd}}
        ]}],
        [{"type": "content", "text": "done"}],
    ]

    async def stream_chat(target, model, messages, tools=None):
        if not offered:
            offered.append([t["function"]["name"] for t in tools or []])
        for piece in turns.pop(0) if turns else []:
            yield piece

    monkeypatch.setattr(llm, "stream_chat", stream_chat)
    resp = build_stream_response(
        chat_id, TARGET, "m", [{"role": "user", "content": "hi"}], use_tools=True, user_id=user_id
    )
    events = []
    async for chunk in resp.body_iterator:
        for line in chunk.splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            events.append(event)
            if event["type"] == "approval_request" and decide is not None:
                assert approvals.resolve(event["id"], chat_id, user_id, decide)
    return events, offered[0]


def _types(events):
    return [e["type"] for e in events]


async def test_owner_is_offered_and_runs_the_host_tool(monkeypatch, owner, host_tool):
    events, offered = await _drive(monkeypatch, _chat(owner), owner, "ls")
    assert "host_test_shell" in offered
    assert "approval_request" not in _types(events)  # harmless command → no card
    assert host_tool == [{"cmd": "ls"}]


async def test_another_admin_never_sees_or_runs_it(monkeypatch, other_admin, host_tool):
    events, offered = await _drive(monkeypatch, _chat(other_admin), other_admin, "ls")
    assert "host_test_shell" not in offered
    assert "approval_request" not in _types(events)  # no card for a tool they do not have
    assert next(e for e in events if e["type"] == "tool_result")["ok"] is False
    assert host_tool == []


async def test_unidentified_caller_is_not_privileged(monkeypatch, owner, host_tool):
    events, offered = await _drive(monkeypatch, _chat(owner), None, "ls")
    assert "host_test_shell" not in offered
    assert host_tool == []


async def test_risky_arguments_ask_first(monkeypatch, owner, host_tool):
    events, _ = await _drive(monkeypatch, _chat(owner), owner, "rm -rf /tmp/x", decide=True)
    request = next(e for e in events if e["type"] == "approval_request")
    assert request["args"] == {"cmd": "rm -rf /tmp/x"}
    assert host_tool == [{"cmd": "rm -rf /tmp/x"}]


async def test_denied_risky_arguments_do_not_run(monkeypatch, owner, host_tool):
    events, _ = await _drive(monkeypatch, _chat(owner), owner, "rm -rf /tmp/x", decide=False)
    assert next(e for e in events if e["type"] == "tool_result")["ok"] is False
    assert host_tool == []


async def test_no_approval_card_for_a_tool_the_caller_does_not_have(
    monkeypatch, other_admin, host_tool
):
    """Risky arguments to a hidden tool: the operator must not be asked to approve a tool that
    would be refused anyway — a card is a claim that saying yes does something."""
    events, _ = await _drive(monkeypatch, _chat(other_admin), other_admin, "rm -rf /tmp/x")
    assert "approval_request" not in _types(events)
    assert host_tool == []
