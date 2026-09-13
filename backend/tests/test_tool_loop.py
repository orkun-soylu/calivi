"""The agentic loop's tool-result reporting (routers/chats.py::build_stream_response).

This file exists because of a real regression. The loop decides whether a tool call
succeeded by testing an error prefix on the string the registry returns. Both sides used to
carry that prefix as a bare literal ("HATA:"); when the registry's message was translated to
"ERROR:" and the loop's check was not, **every failed tool call started reporting as
successful** — the ✗ in the UI silently became a ✓, and the model's error output was fed back
as if it were a good result. Nothing caught it, because no test drove the loop itself.

So these tests assert the observable contract (the `ok` flag on the emitted tool_result),
not the constant. Mutation-checked: reintroducing a literal on either side fails them.
"""
import json

import pytest

from app import llm, tools_config
from app.database import SessionLocal
from app.routers.chats import FINAL_TURN_NOTICE, build_stream_response
from app.tools.registry import Tool, registry


@pytest.fixture
def chat_id():
    """A chat row to satisfy the assistant-message save in generate()'s finally block."""
    from app import models

    db = SessionLocal()
    try:
        user = models.User(
            email="loop@test.local", username="loop", password_hash="x", role="admin"
        )
        db.add(user)
        db.commit()
        chat = models.Chat(user_id=user.id, title="t")
        db.add(chat)
        db.commit()
        return chat.id
    finally:
        db.close()


def _fake_llm(calls):
    """Emits one tool-call turn, then a plain content turn (the final answer)."""
    turns = [
        [{"type": "tool_calls", "calls": calls}],
        [{"type": "content", "text": "final answer"}],
    ]

    async def stream_chat(target, model, messages, tools=None):
        for piece in turns.pop(0) if turns else []:
            yield piece

    return stream_chat


async def _tool_results(monkeypatch, chat_id, calls):
    """Runs the loop and returns the tool_result events it emitted."""
    monkeypatch.setattr(llm, "stream_chat", _fake_llm(calls))
    resp = build_stream_response(
        chat_id,
        {"name": "s", "type": "ollama", "host": "h", "port": 1, "base_url": None, "api_key": None},
        "m",
        [{"role": "user", "content": "hi"}],
        use_tools=True,
    )
    events = []
    async for chunk in resp.body_iterator:
        for line in chunk.splitlines():
            if line.strip():
                events.append(json.loads(line))
    return [e for e in events if e["type"] == "tool_result"]


async def test_unknown_tool_is_reported_as_failed(monkeypatch, chat_id):
    """The registry rejects an unknown tool with an error string → the loop must emit ok=False."""
    results = await _tool_results(
        monkeypatch, chat_id, [{"id": "c1", "name": "no_such_tool", "arguments": {}}]
    )
    assert results == [{"type": "tool_result", "name": "no_such_tool", "ok": False}]


async def test_mutating_tool_is_reported_as_failed(monkeypatch, chat_id):
    """The Phase 1 read-only gate rejects it — that rejection must reach the user as ✗."""

    async def handler(args):
        return "state changed"

    registry.register(
        Tool(
            name="dangerous_test_tool",
            description="d",
            parameters={"type": "object", "properties": {}},
            handler=handler,
            mutating=True,
        )
    )
    try:
        results = await _tool_results(
            monkeypatch, chat_id, [{"id": "c1", "name": "dangerous_test_tool", "arguments": {}}]
        )
        assert results == [{"type": "tool_result", "name": "dangerous_test_tool", "ok": False}]
    finally:
        registry._tools.pop("dangerous_test_tool", None)


async def test_successful_tool_is_reported_as_ok(monkeypatch, chat_id):
    """The other direction: a good result must NOT be misread as a failure."""

    async def handler(args):
        return "a perfectly good result"

    registry.register(
        Tool(
            name="fine_test_tool",
            description="d",
            parameters={"type": "object", "properties": {}},
            handler=handler,
        )
    )
    try:
        results = await _tool_results(
            monkeypatch, chat_id, [{"id": "c1", "name": "fine_test_tool", "arguments": {}}]
        )
        assert results == [{"type": "tool_result", "name": "fine_test_tool", "ok": True}]
    finally:
        registry._tools.pop("fine_test_tool", None)


# --- The capped last turn ------------------------------------------------------------------
# Regression: the last permitted turn used to lose its tools silently. A local model that still
# wanted to search wrote the call out as text, no tool_calls arrived, and that markup was saved
# as the answer. These drive a model that asks for a tool whenever it is offered one.

_TARGET = {"name": "s", "type": "ollama", "host": "h", "port": 1, "base_url": None, "api_key": None}


@pytest.fixture
def cap_tool():
    async def handler(args):
        return "a result"

    registry.register(
        Tool(
            name="cap_test_tool",
            description="d",
            parameters={"type": "object", "properties": {}},
            handler=handler,
        )
    )
    yield
    registry._tools.pop("cap_test_tool", None)


async def _run_tool_hungry_model(monkeypatch, chat_id, max_iterations):
    """Returns, per turn, the (tools, messages) the model was called with."""
    seen = []

    async def stream_chat(target, model, messages, tools=None):
        seen.append((tools, [dict(m) for m in messages]))
        if tools:
            call = {"id": f"c{len(seen)}", "name": "cap_test_tool", "arguments": {}}
            yield {"type": "tool_calls", "calls": [call]}
        else:
            yield {"type": "content", "text": "final answer"}

    monkeypatch.setattr(llm, "stream_chat", stream_chat)
    monkeypatch.setattr(tools_config, "is_enabled", lambda: True)
    monkeypatch.setattr(tools_config, "tool_enabled", lambda name: True)
    monkeypatch.setattr(tools_config, "get_max_iterations", lambda: max_iterations)
    resp = build_stream_response(
        chat_id, _TARGET, "m", [{"role": "user", "content": "hi"}], use_tools=True
    )
    async for _chunk in resp.body_iterator:
        pass
    return seen


def _has_notice(messages):
    return any(m.get("content") == FINAL_TURN_NOTICE for m in messages)


async def test_capped_last_turn_drops_tools_and_tells_the_model(monkeypatch, chat_id, cap_tool):
    seen = await _run_tool_hungry_model(monkeypatch, chat_id, max_iterations=2)
    assert [bool(tools) for tools, _ in seen] == [True, False]
    assert not _has_notice(seen[0][1])
    assert seen[1][1][-1] == {"role": "user", "content": FINAL_TURN_NOTICE}


async def test_single_turn_budget_sends_no_notice(monkeypatch, chat_id, cap_tool):
    """max_iterations 1: no tool ran, so there are no results for the notice to point at."""
    seen = await _run_tool_hungry_model(monkeypatch, chat_id, max_iterations=1)
    assert len(seen) == 1
    assert not _has_notice(seen[0][1])
