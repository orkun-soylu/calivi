"""Human-in-the-loop approval for state-changing tools.

The loop runs inside a StreamingResponse, so these tests drive the stream in one task while
resolving the approval from another — the same shape as a browser answering the prompt while
the response is still open.
"""
import asyncio
import json

import pytest

from app import approvals, llm, models
from app.database import SessionLocal
from app.routers import chats as chats_router
from app.routers.chats import build_stream_response
from app.tools.registry import ERROR_PREFIX, Tool, registry

TARGET = {"name": "s", "type": "ollama", "host": "h", "port": 1, "base_url": None, "api_key": None}
TOOL = "dangerous_tool"


@pytest.fixture
def chat(admin_user):
    db = SessionLocal()
    try:
        c = models.Chat(user_id=admin_user, title="t")
        db.add(c)
        db.commit()
        db.add(models.Message(chat_id=c.id, role="user", content="hi"))
        db.commit()
        return c.id
    finally:
        db.close()


@pytest.fixture
def admin_user():
    db = SessionLocal()
    try:
        u = models.User(email="a@test.local", username="a", password_hash="x", role="admin")
        db.add(u)
        db.commit()
        return u.id
    finally:
        db.close()


@pytest.fixture
def mutating_tool():
    ran = []

    async def handler(args):
        ran.append(args)
        return "state changed"

    registry.register(
        Tool(name=TOOL, description="d", parameters={"type": "object", "properties": {}},
             handler=handler, mutating=True)
    )
    yield ran
    registry._tools.pop(TOOL, None)


def _llm_asking_for(tool_name):
    turns = [
        [{"type": "tool_calls", "calls": [{"id": "c1", "name": tool_name, "arguments": {"x": 1}}]}],
        [{"type": "content", "text": "done"}],
    ]

    async def stream_chat(target, model, messages, tools=None):
        for piece in turns.pop(0) if turns else []:
            yield piece

    return stream_chat


async def _drive(chat_id, user_id, decide=None):
    """Consumes the stream; when the approval request appears, runs `decide(approval_id)`."""
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
                await decide(event["id"])
    return events


def _types(events):
    return [e["type"] for e in events]


@pytest.mark.anyio
async def test_mutating_tool_asks_before_running(monkeypatch, chat, admin_user, mutating_tool):
    monkeypatch.setattr(llm, "stream_chat", _llm_asking_for(TOOL))

    async def approve(approval_id):
        assert approvals.resolve(approval_id, chat, admin_user, True)

    events = await _drive(chat, admin_user, approve)

    assert "approval_request" in _types(events)
    request = next(e for e in events if e["type"] == "approval_request")
    # The card has to show what will actually run.
    assert request["name"] == TOOL and request["args"] == {"x": 1}
    assert next(e for e in events if e["type"] == "approval_result")["approved"] is True
    assert next(e for e in events if e["type"] == "tool_result")["ok"] is True
    assert mutating_tool == [{"x": 1}]  # it ran, once


@pytest.mark.anyio
async def test_denial_stops_the_tool_and_is_reported_as_a_failure(
    monkeypatch, chat, admin_user, mutating_tool
):
    monkeypatch.setattr(llm, "stream_chat", _llm_asking_for(TOOL))

    async def deny(approval_id):
        approvals.resolve(approval_id, chat, admin_user, False)

    events = await _drive(chat, admin_user, deny)

    assert next(e for e in events if e["type"] == "approval_result")["approved"] is False
    assert next(e for e in events if e["type"] == "tool_result")["ok"] is False
    assert mutating_tool == []  # never ran


@pytest.mark.anyio
async def test_silence_is_a_denial_not_consent(monkeypatch, chat, admin_user, mutating_tool):
    """A timeout must deny. The opposite default would turn walking away from the keyboard into
    a blanket grant."""
    monkeypatch.setattr(chats_router, "APPROVAL_TIMEOUT", 0.05)
    monkeypatch.setattr(chats_router, "APPROVAL_HEARTBEAT", 0.01)
    monkeypatch.setattr(llm, "stream_chat", _llm_asking_for(TOOL))

    events = await _drive(chat, admin_user, decide=None)

    assert next(e for e in events if e["type"] == "approval_result")["approved"] is False
    assert mutating_tool == []


@pytest.mark.anyio
async def test_pings_keep_the_connection_alive_while_waiting(
    monkeypatch, chat, admin_user, mutating_tool
):
    """No bytes flow while a human decides, and Traefik drops idle connections after 180s."""
    monkeypatch.setattr(chats_router, "APPROVAL_TIMEOUT", 0.2)
    monkeypatch.setattr(chats_router, "APPROVAL_HEARTBEAT", 0.02)
    monkeypatch.setattr(llm, "stream_chat", _llm_asking_for(TOOL))

    events = await _drive(chat, admin_user, decide=None)

    assert _types(events).count("ping") >= 3


@pytest.mark.anyio
async def test_a_read_only_tool_is_never_asked_about(monkeypatch, chat, admin_user):
    async def handler(args):
        return "fine"

    registry.register(
        Tool(name="safe_tool", description="d", parameters={"type": "object", "properties": {}},
             handler=handler, mutating=False)
    )
    try:
        monkeypatch.setattr(llm, "stream_chat", _llm_asking_for("safe_tool"))
        events = await _drive(chat, admin_user)
    finally:
        registry._tools.pop("safe_tool", None)

    assert "approval_request" not in _types(events)
    assert next(e for e in events if e["type"] == "tool_result")["ok"] is True


@pytest.mark.anyio
async def test_the_pending_entry_is_dropped_when_the_stream_ends(
    monkeypatch, chat, admin_user, mutating_tool
):
    """A closed tab raises CancelledError (a BaseException); without the finally the process
    would accumulate pending approvals forever."""
    monkeypatch.setattr(chats_router, "APPROVAL_TIMEOUT", 0.05)
    monkeypatch.setattr(chats_router, "APPROVAL_HEARTBEAT", 0.01)
    monkeypatch.setattr(llm, "stream_chat", _llm_asking_for(TOOL))

    await _drive(chat, admin_user, decide=None)

    assert approvals._pending == {}


# ── Ownership ─────────────────────────────────────────────────────────────────


def test_another_user_cannot_approve():
    """Approving grants a capability; it must not be possible on someone else's behalf."""
    approval_id = approvals.create(chat_id=1, user_id=1, tool="t", args={})

    assert approvals.resolve(approval_id, chat_id=1, user_id=2, approved=True) is False
    assert approvals.resolve(approval_id, chat_id=99, user_id=1, approved=True) is False
    assert approvals.get(approval_id).approved is False

    assert approvals.resolve(approval_id, chat_id=1, user_id=1, approved=True) is True


def test_unknown_approval_is_rejected():
    assert approvals.resolve("nope", chat_id=1, user_id=1, approved=True) is False


def test_approval_ids_are_unguessable():
    """The id is a capability: it travels in a URL and must not be enumerable."""
    ids = {approvals.create(1, 1, "t", {}) for _ in range(50)}
    assert len(ids) == 50
    assert all(len(i) >= 20 for i in ids)


@pytest.mark.anyio
async def test_endpoint_rejects_a_chat_that_is_not_yours(client, user_client):
    from tests.conftest import register

    await register(client, "owner")
    await register(user_client, "intruder")
    chat_id = (await client.post("/api/chats", json={"title": "t"})).json()["id"]
    approval_id = approvals.create(chat_id, 1, "t", {})

    resp = await user_client.post(
        f"/api/chats/{chat_id}/approvals/{approval_id}", json={"approved": True}
    )

    assert resp.status_code == 404
    assert approvals.get(approval_id).approved is False
