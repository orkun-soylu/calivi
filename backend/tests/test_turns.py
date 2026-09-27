"""Background turns (turns.py, #85): a reply outlives the request that started it.

The fake model yields a first piece, waits on a gate, then yields a second — so each test
decides exactly when the reply is "in progress". Following is exercised through
`turns.follow` directly: httpx's ASGI transport buffers a whole response, so an HTTP read of a
turn that is waiting on the gate would never return. Everything that is not a stream (409s,
cancel, the chat detail, ownership) goes over HTTP.
"""
import asyncio
import json

import pytest

from app import approvals, llm, models, turns
from app.database import SessionLocal
from app.routers import chats as chats_router
from app.routers.chats import build_stream_response
from app.tools.registry import Tool, registry
from tests.conftest import register

TARGET = {"name": "s", "type": "ollama", "host": "h", "port": 1, "base_url": None, "api_key": None}


@pytest.fixture
def gate(monkeypatch):
    g = asyncio.Event()

    async def stream_chat(target, model, messages, tools=None):
        yield {"type": "content", "text": "first "}
        await g.wait()
        yield {"type": "content", "text": "second"}

    monkeypatch.setattr(llm, "stream_chat", stream_chat)
    return g


@pytest.fixture
async def owned(admin):
    """(client, chat_id) — a chat of the signed-in super admin, with one user message."""
    chat_id = (await admin.post("/api/chats", json={})).json()["id"]
    db = SessionLocal()
    try:
        db.add(models.Message(chat_id=chat_id, role="user", content="hi"))
        db.commit()
    finally:
        db.close()
    return admin, chat_id


def _start(chat_id, user_id=1):
    resp = build_stream_response(chat_id, TARGET, "m", [{"role": "user", "content": "hi"}], user_id=user_id)
    return resp, turns.get(chat_id)


def _replies(chat_id):
    db = SessionLocal()
    try:
        return [m.content for m in db.query(models.Message).filter_by(chat_id=chat_id, role="assistant")]
    finally:
        db.close()


async def _first_line(resp):
    it = resp.body_iterator
    line = await it.__anext__()
    await it.aclose()  # the browser goes away
    return json.loads(line)


async def _drain(agen):
    return [json.loads(line) for line in [x async for x in agen]]


async def test_a_closed_tab_does_not_stop_the_reply(owned, gate):
    _, chat_id = owned
    resp, turn = _start(chat_id)
    assert (await _first_line(resp))["text"] == "first "
    gate.set()
    await turn.task
    assert _replies(chat_id) == ["first second"]
    assert not turns.is_active(chat_id)


async def test_re_attaching_replays_then_continues(owned, gate):
    _, chat_id = owned
    resp, turn = _start(chat_id)
    await _first_line(resp)
    follower = asyncio.create_task(_drain(turns.follow(turn)))
    await asyncio.sleep(0)
    gate.set()
    events = await follower
    assert [e["text"] for e in events if e["type"] == "content"] == ["first ", "second"]


async def test_the_follower_pings_while_nothing_happens(owned, gate):
    _, chat_id = owned
    resp, turn = _start(chat_id)
    await _first_line(resp)
    agen = turns.follow(turn, heartbeat=0.01)
    assert json.loads(await agen.__anext__())["type"] == "content"  # the replay
    assert json.loads(await agen.__anext__())["type"] == "ping"  # then silence → ping
    await agen.aclose()
    gate.set()
    await turn.task


async def test_stop_saves_the_partial_reply(owned, gate):
    client, chat_id = owned
    resp, turn = _start(chat_id)
    await _first_line(resp)
    assert (await client.post(f"/api/chats/{chat_id}/turn/cancel")).status_code == 204
    with pytest.raises(asyncio.CancelledError):
        await turn.task
    assert _replies(chat_id) == ["first "]
    assert (await client.post(f"/api/chats/{chat_id}/turn/cancel")).status_code == 404


async def test_the_chat_detail_says_when_to_re_attach(owned, gate):
    client, chat_id = owned
    resp, turn = _start(chat_id)
    await _first_line(resp)
    assert (await client.get(f"/api/chats/{chat_id}")).json()["active_turn"] is True
    gate.set()
    await turn.task
    assert (await client.get(f"/api/chats/{chat_id}")).json()["active_turn"] is False
    assert (await client.get(f"/api/chats/{chat_id}/turn")).status_code == 404


async def test_one_turn_per_chat(owned, gate):
    client, chat_id = owned
    await client.post("/api/servers", json={"name": "s", "host": "127.0.0.1", "port": 1})
    resp, turn = _start(chat_id)
    await _first_line(resp)
    msg_id = SessionLocal().query(models.Message).filter_by(chat_id=chat_id).first().id
    body = {"content": "again", "server_id": 1, "model": "m"}

    assert (await client.post(f"/api/chats/{chat_id}/messages", json=body)).status_code == 409
    assert (await client.put(f"/api/chats/{chat_id}/messages/{msg_id}", json=body)).status_code == 409
    assert (await client.delete(f"/api/chats/{chat_id}/messages/{msg_id}")).status_code == 409
    assert (await client.post(f"/api/chats/{chat_id}/compact", json={"server_id": 1, "model": "m"})).status_code == 409
    # Refused means untouched: the send saved no user message, and the edit neither rewrote
    # the message nor truncated after it. (Without the guard, `turns.start` still answers 409
    # — but only after the edit has already changed the history under the running reply.)
    db = SessionLocal()
    assert [m.content for m in db.query(models.Message).filter_by(chat_id=chat_id)] == ["hi"]
    db.close()
    gate.set()
    await turn.task


async def test_deleting_the_chat_stops_its_reply(owned, gate):
    client, chat_id = owned
    resp, turn = _start(chat_id)
    await _first_line(resp)
    assert (await client.delete(f"/api/chats/{chat_id}")).status_code == 204
    with pytest.raises(asyncio.CancelledError):
        await turn.task  # and its final save found the chat gone instead of failing
    assert not turns.is_active(chat_id)
    assert _replies(chat_id) == []


async def test_deleting_a_user_stops_their_replies(owned, gate, user_client):
    client, _ = owned
    other = await register(user_client, "second")
    chat_id = (await user_client.post("/api/chats", json={})).json()["id"]
    resp, turn = _start(chat_id, user_id=other["id"])
    await _first_line(resp)
    assert (await client.delete(f"/api/users/{other['id']}")).status_code == 204
    with pytest.raises(asyncio.CancelledError):
        await turn.task


async def test_deleting_your_own_account_stops_your_replies(owned, gate, user_client):
    other = await register(user_client, "second")
    chat_id = (await user_client.post("/api/chats", json={})).json()["id"]
    resp, turn = _start(chat_id, user_id=other["id"])
    await _first_line(resp)
    assert (await user_client.delete("/api/users/me")).status_code == 204
    with pytest.raises(asyncio.CancelledError):
        await turn.task


async def test_a_chat_deleted_mid_save_is_not_an_error(owned, gate, monkeypatch):
    """The delete endpoint runs in a worker thread, the reply on the loop: the save can see the
    chat, then lose it before the insert. That race is simulated here — the existence check is
    told the chat is there while the row is already gone — and must end quietly."""
    from sqlalchemy.orm import Session

    _, chat_id = owned
    resp, turn = _start(chat_id)
    await _first_line(resp)
    db = SessionLocal()
    db.query(models.Message).filter_by(chat_id=chat_id).delete()
    db.query(models.Chat).filter_by(id=chat_id).delete()
    db.commit()
    db.close()
    real_get = Session.get
    monkeypatch.setattr(Session, "get", lambda self, entity, ident, **kw:
                        object() if entity is models.Chat else real_get(self, entity, ident, **kw))
    gate.set()
    await turn.task  # no IntegrityError out of the task
    assert _replies(chat_id) == []


async def test_someone_else_cannot_follow_or_stop_it(owned, gate, user_client):
    _, chat_id = owned
    resp, turn = _start(chat_id)
    await _first_line(resp)
    await register(user_client, "second")
    assert (await user_client.get(f"/api/chats/{chat_id}/turn")).status_code == 404
    assert (await user_client.post(f"/api/chats/{chat_id}/turn/cancel")).status_code == 404
    assert turns.is_active(chat_id)
    gate.set()
    await turn.task


async def test_a_pending_approval_survives_a_closed_tab_and_goes_on_stop(owned, monkeypatch):
    """The card comes back on re-attach; Stop — not a disconnect — is what withdraws it."""
    _, chat_id = owned

    async def handler(args):
        return "ran"

    registry.register(Tool(name="turn_test_tool", description="d",
                           parameters={"type": "object", "properties": {}}, handler=handler, mutating=True))
    turns_ = [[{"type": "tool_calls", "calls": [{"id": "c1", "name": "turn_test_tool", "arguments": {}}]}],
              [{"type": "content", "text": "done"}]]

    async def stream_chat(target, model, messages, tools=None):
        for piece in turns_.pop(0) if turns_ else []:
            yield piece

    monkeypatch.setattr(llm, "stream_chat", stream_chat)
    monkeypatch.setattr(chats_router.tools_config, "is_enabled", lambda: True)
    monkeypatch.setattr(chats_router.tools_config, "tool_enabled", lambda name: True)
    try:
        resp = build_stream_response(chat_id, TARGET, "m", [{"role": "user", "content": "hi"}],
                                     use_tools=True, user_id=1)
        turn = turns.get(chat_id)
        it = resp.body_iterator
        while json.loads(await it.__anext__())["type"] != "approval_request":
            pass
        await it.aclose()  # tab closed while the card is up
        await asyncio.sleep(0)
        assert len(approvals._pending) == 1  # still waiting for a decision

        replay = turns.follow(turn)
        types = []
        async for line in replay:
            types.append(json.loads(line)["type"])
            if types[-1] == "approval_request":
                break
        await replay.aclose()
        assert "approval_request" in types  # the card is back

        turns.cancel(chat_id)
        with pytest.raises(asyncio.CancelledError):
            await turn.task
        assert approvals._pending == {}
    finally:
        registry._tools.pop("turn_test_tool", None)
