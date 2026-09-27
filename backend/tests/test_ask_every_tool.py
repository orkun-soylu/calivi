""""Ask before every tool" — the operator's strict mode (#78).

The default policy asks only for risky calls, so an operator who wants to watch every step
turns this on. It must reach the loop from all three streaming endpoints, and it can only
*add* approval cards.
"""
import json

import pytest

from app import config, llm, models, tools_config
from app.database import SessionLocal
from app.routers import chats as chats_router
from app.routers.chats import build_stream_response
from app.tools.registry import Tool, registry
from tests.conftest import register

TARGET = {"name": "s", "type": "ollama", "host": "h", "port": 1, "base_url": None, "api_key": None}


@pytest.fixture(autouse=True)
def tools_on(monkeypatch):
    monkeypatch.setattr(tools_config, "is_enabled", lambda: True)
    monkeypatch.setattr(tools_config, "tool_enabled", lambda name: True)


@pytest.fixture
def harmless_tool():
    ran = []

    async def handler(args):
        ran.append(args)
        return "ran"

    registry.register(Tool(name="harmless_test_tool", description="d",
                           parameters={"type": "object", "properties": {}}, handler=handler))
    yield ran
    registry._tools.pop("harmless_test_tool", None)


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


async def _drive(monkeypatch, user_id, chat_id, ask_every_tool, decide):
    turns = [
        [{"type": "tool_calls", "calls": [{"id": "c1", "name": "harmless_test_tool", "arguments": {}}]}],
        [{"type": "content", "text": "done"}],
    ]

    async def stream_chat(target, model, messages, tools=None):
        for piece in turns.pop(0) if turns else []:
            yield piece

    monkeypatch.setattr(llm, "stream_chat", stream_chat)
    resp = build_stream_response(
        chat_id, TARGET, "m", [{"role": "user", "content": "hi"}], use_tools=True,
        user_id=user_id, ask_every_tool=ask_every_tool,
    )
    from app import approvals

    events = []
    async for chunk in resp.body_iterator:
        for line in chunk.splitlines():
            if line.strip():
                event = json.loads(line)
                events.append(event)
                if event["type"] == "approval_request":
                    assert approvals.resolve(event["id"], chat_id, user_id, decide)
    return [e["type"] for e in events]


async def test_off_a_harmless_tool_just_runs(monkeypatch, owner_chat, harmless_tool):
    types = await _drive(monkeypatch, *owner_chat, ask_every_tool=False, decide=True)
    assert "approval_request" not in types
    assert harmless_tool == [{}]


async def test_on_a_harmless_tool_asks_and_runs_on_yes(monkeypatch, owner_chat, harmless_tool):
    types = await _drive(monkeypatch, *owner_chat, ask_every_tool=True, decide=True)
    assert "approval_request" in types
    assert harmless_tool == [{}]


async def test_on_a_no_means_it_does_not_run(monkeypatch, owner_chat, harmless_tool):
    types = await _drive(monkeypatch, *owner_chat, ask_every_tool=True, decide=False)
    assert "approval_request" in types
    assert harmless_tool == []


# --- The flag reaches the loop from every streaming endpoint --------------------------------


@pytest.fixture
def captured(monkeypatch):
    seen = []

    def fake_build(*args, **kwargs):
        seen.append(kwargs)
        from fastapi.responses import StreamingResponse

        async def empty():
            yield ""

        return StreamingResponse(empty(), headers=kwargs.get("extra_headers") or {})

    monkeypatch.setattr(chats_router, "build_stream_response", fake_build)
    return seen


@pytest.fixture
async def chat_with_message(admin):
    await admin.post("/api/servers", json={"name": "s", "host": "127.0.0.1", "port": 1})
    chat_id = (await admin.post("/api/chats", json={})).json()["id"]
    db = SessionLocal()
    try:
        m = models.Message(chat_id=chat_id, role="user", content="hi")
        db.add(m)
        db.commit()
        return admin, chat_id, m.id
    finally:
        db.close()


@pytest.mark.parametrize("flag", [True, False])
async def test_every_endpoint_forwards_the_flag(chat_with_message, captured, flag):
    client, chat_id, message_id = chat_with_message
    body = {"content": "x", "server_id": 1, "model": "m", "ask_every_tool": flag}
    await client.post(f"/api/chats/{chat_id}/messages", json=body)
    await client.put(f"/api/chats/{chat_id}/messages/{message_id}", json=body)
    await client.post(f"/api/chats/{chat_id}/fork", json={**body, "message_id": message_id})
    assert [kw.get("ask_every_tool") for kw in captured] == [flag, flag, flag]


# --- /me tells the UI whether to show the toggle --------------------------------------------


async def test_host_tools_flag_follows_the_switch_and_id_1(client, monkeypatch):
    me = await register(client, "owner")
    assert me["host_tools"] is False  # switch off: never, not even for id 1

    monkeypatch.setattr(config, "HOST_TOOLS_ENABLED", True)
    assert (await client.get("/api/auth/me")).json()["host_tools"] is True

    await client.post("/api/auth/logout")
    second = await register(client, "second")
    assert second["host_tools"] is False  # a second user never gets the host
    assert (await client.get("/api/auth/me")).json()["host_tools"] is False
