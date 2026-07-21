"""What the agentic loop persists: the assistant message and the tool-usage chips.

Both behaviours here were found by running the app, not by reading it — a real chat ended up
with a blank assistant bubble, and a reloaded chat gave no clue that an MCP server had been
consulted.
"""
import json

import pytest

from app import llm, models
from app.database import SessionLocal
from app.routers.chats import _inject_attachments, build_stream_response
from app.tools import mcp_client
from app.tools.registry import Tool, registry

TARGET = {"name": "s", "type": "ollama", "host": "h", "port": 1, "base_url": None, "api_key": None}


@pytest.fixture
def chat_id():
    db = SessionLocal()
    try:
        user = models.User(email="p@test.local", username="persist", password_hash="x", role="admin")
        db.add(user)
        db.commit()
        chat = models.Chat(user_id=user.id, title="t")
        db.add(chat)
        db.commit()
        db.add(models.Message(chat_id=chat.id, role="user", content="hi"))
        db.commit()
        return chat.id
    finally:
        db.close()


def _scripted_llm(script):
    """Yields one scripted turn per call, in order."""
    remaining = list(script)

    async def stream_chat(target, model, messages, tools=None):
        for piece in remaining.pop(0) if remaining else []:
            yield piece

    return stream_chat


async def _run(monkeypatch, chat_id, script, web_search=True):
    monkeypatch.setattr(llm, "stream_chat", _scripted_llm(script))
    resp = build_stream_response(
        chat_id, TARGET, "m", [{"role": "user", "content": "hi"}], web_search=web_search
    )
    events = []
    async for chunk in resp.body_iterator:
        for line in chunk.splitlines():
            if line.strip():
                events.append(json.loads(line))
    return events


def _messages(chat_id):
    db = SessionLocal()
    try:
        return (
            db.query(models.Message)
            .filter(models.Message.chat_id == chat_id)
            .order_by(models.Message.id)
            .all()
        )
    finally:
        db.close()


def _register(name, result="fine"):
    async def handler(args):
        return result

    registry.register(
        Tool(name=name, description="d", parameters={"type": "object", "properties": {}}, handler=handler)
    )


# ── The blank assistant bubble ────────────────────────────────────────────────


async def test_no_content_and_no_error_saves_nothing(monkeypatch, chat_id):
    """A model turn that produced no text must not leave an empty assistant row: it renders as
    a blank bubble that cannot be told apart from a real reply. Seen in production."""
    await _run(monkeypatch, chat_id, [[]])

    roles = [m.role for m in _messages(chat_id)]
    assert roles == ["user"], f"an empty assistant message was persisted: {roles}"


async def test_whitespace_only_content_saves_nothing(monkeypatch, chat_id):
    await _run(monkeypatch, chat_id, [[{"type": "content", "text": "   \n  "}]])
    assert [m.role for m in _messages(chat_id)] == ["user"]


async def test_real_content_is_still_saved(monkeypatch, chat_id):
    """The other direction — the guard must not swallow genuine answers."""
    await _run(monkeypatch, chat_id, [[{"type": "content", "text": "a real answer"}]])

    msgs = _messages(chat_id)
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert msgs[-1].content == "a real answer"


async def test_upstream_error_still_saves_a_visible_marker(monkeypatch, chat_id):
    """An error with no content must still be recorded — silence would hide the failure."""

    async def boom(target, model, messages, tools=None):
        raise RuntimeError("upstream exploded")
        yield  # pragma: no cover

    monkeypatch.setattr(llm, "stream_chat", boom)
    resp = build_stream_response(chat_id, TARGET, "m", [{"role": "user", "content": "hi"}], web_search=False)
    async for _ in resp.body_iterator:
        pass

    msgs = _messages(chat_id)
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert msgs[-1].content.startswith("⚠️")


# ── Tool provenance chips ─────────────────────────────────────────────────────


async def test_mcp_tool_leaves_a_chip(monkeypatch, chat_id):
    """Without this, a reloaded chat gives no sign that an MCP server was consulted."""
    name = mcp_client.namespaced("context7", "query-docs")
    _register(name, result="documentation body")
    try:
        await _run(
            monkeypatch,
            chat_id,
            [[{"type": "tool_calls", "calls": [{"id": "c1", "name": name, "arguments": {}}]}],
             [{"type": "content", "text": "answer"}]],
        )
    finally:
        registry._tools.pop(name, None)

    chips = _messages(chat_id)[0].attachments
    assert [c["name"] for c in chips] == ["🔧 context7: query-docs"]


async def test_mcp_chip_carries_no_text_so_it_is_not_re_injected(monkeypatch, chat_id):
    """Attachment text is re-injected into every later turn. A documentation dump would be
    re-sent for the rest of the conversation for no benefit — the answer is already in the
    history."""
    name = mcp_client.namespaced("context7", "query-docs")
    _register(name, result="x" * 5000)
    try:
        await _run(
            monkeypatch,
            chat_id,
            [[{"type": "tool_calls", "calls": [{"id": "c1", "name": name, "arguments": {}}]}],
             [{"type": "content", "text": "answer"}]],
        )
    finally:
        registry._tools.pop(name, None)

    chip = _messages(chat_id)[0].attachments[0]
    assert "text" not in chip or not chip.get("text")

    # ...and the injection step must skip it rather than crash on the missing key.
    injected = _inject_attachments([{"role": "user", "content": "q", "attachments": [chip]}])
    assert injected[0]["content"] == "q"


async def test_web_search_chip_keeps_its_query_and_text(monkeypatch, chat_id):
    """Existing behaviour, deliberately unchanged: the search result stays in context."""
    await _run(
        monkeypatch,
        chat_id,
        [[{"type": "tool_calls",
           "calls": [{"id": "c1", "name": "web_search", "arguments": {"query": "bitcoin"}}]}],
         [{"type": "content", "text": "answer"}]],
    )

    chip = _messages(chat_id)[0].attachments[0]
    assert chip["name"] == "🔍 bitcoin"
    assert chip["text"]


async def test_repeated_calls_do_not_pile_up_duplicate_chips(monkeypatch, chat_id):
    name = mcp_client.namespaced("context7", "query-docs")
    _register(name)
    try:
        await _run(
            monkeypatch,
            chat_id,
            [[{"type": "tool_calls", "calls": [
                {"id": "c1", "name": name, "arguments": {"q": "a"}},
                {"id": "c2", "name": name, "arguments": {"q": "b"}},
            ]}],
             [{"type": "content", "text": "answer"}]],
        )
    finally:
        registry._tools.pop(name, None)

    assert len(_messages(chat_id)[0].attachments) == 1


async def test_failed_tool_leaves_no_chip(monkeypatch, chat_id):
    """A chip claims "this ran and informed the answer" — a failure must not claim that."""
    await _run(
        monkeypatch,
        chat_id,
        [[{"type": "tool_calls", "calls": [{"id": "c1", "name": "no_such_tool", "arguments": {}}]}],
         [{"type": "content", "text": "answer"}]],
    )
    assert not (_messages(chat_id)[0].attachments or [])


# ── The namespace has one owner ───────────────────────────────────────────────


def test_display_label_round_trips_with_namespaced():
    assert mcp_client.display_label(mcp_client.namespaced("context7", "query-docs")) == "context7: query-docs"


def test_display_label_ignores_non_mcp_names():
    assert mcp_client.display_label("web_search") is None
