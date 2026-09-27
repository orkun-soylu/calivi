"""Images from tools: host `view_image`, and the loop attaching what a tool returns.

Tool messages carry text only, so the loop puts a tool's images in a user message after the
step's tool results — and only when the model can see; a model that cannot is told so in the
tool result instead of getting a request its server would reject.
"""
import base64
import getpass
import json

import pytest

from app import llm, tools_config
from app.database import SessionLocal
from app.routers.chats import NO_VISION_NOTE, TOOL_IMAGES_NOTICE, build_stream_response
from app.tools import host
from app.tools.registry import ERROR_PREFIX, Tool, ToolResult, registry

# A 1x1 PNG.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(host, "_account", lambda: (getpass.getuser(), str(tmp_path)))
    return tmp_path


def _view(path):
    tool = next(t for t in host.TOOLS if t.name == "view_image")
    return tool.handler({"path": path})


# --- the tool -------------------------------------------------------------------------------


async def test_an_image_comes_back_as_a_data_uri(home):
    (home / "shot.png").write_bytes(PNG)
    result = await _view("shot.png")
    assert isinstance(result, ToolResult)
    assert not result.startswith(ERROR_PREFIX)
    assert "image/png" in result
    assert result.images == ["data:image/png;base64," + base64.b64encode(PNG).decode()]


async def test_the_type_comes_from_the_bytes_not_the_name(home):
    (home / "notes.png").write_text("not an image at all")
    result = await _view("~/notes.png")
    assert result.startswith(ERROR_PREFIX)
    assert not getattr(result, "images", None)


async def test_a_missing_file_is_an_error(home):
    result = await _view("nope.png")
    assert result.startswith(ERROR_PREFIX)


async def test_a_file_over_the_limit_is_refused_before_it_is_read(home, monkeypatch):
    (home / "big.png").write_bytes(PNG)
    monkeypatch.setattr(host, "IMAGE_MAX_BYTES", len(PNG) - 1)
    result = await _view("big.png")
    assert result.startswith(ERROR_PREFIX)
    assert "limit" in result


def test_it_is_a_privileged_read_only_tool():
    tool = next(t for t in host.TOOLS if t.name == "view_image")
    assert tool.privileged
    assert not tool.requires_approval({"path": "/etc/passwd"})


# --- the loop -------------------------------------------------------------------------------

_TARGET = {"name": "s", "type": "ollama", "host": "h", "port": 1, "base_url": None, "api_key": None}
_URI = "data:image/png;base64,AAAA"


@pytest.fixture
def chat_id():
    from app import models

    db = SessionLocal()
    try:
        user = models.User(email="img@test.local", username="img", password_hash="x", role="admin")
        db.add(user)
        db.commit()
        chat = models.Chat(user_id=user.id, title="t")
        db.add(chat)
        db.commit()
        return chat.id
    finally:
        db.close()


@pytest.fixture
def image_tool():
    async def handler(args):
        return ToolResult("looked", [_URI])

    registry.register(Tool(
        name="img_test_tool", description="d",
        parameters={"type": "object", "properties": {}}, handler=handler,
    ))
    yield
    registry._tools.pop("img_test_tool", None)


async def _second_call(monkeypatch, chat_id, can_see):
    """Runs one tool step and returns (messages of the model's next call, tool_result events)."""
    seen = []

    async def stream_chat(target, model, messages, tools=None):
        seen.append([dict(m) for m in messages])
        if len(seen) == 1:
            yield {"type": "tool_calls", "calls": [{"id": "c1", "name": "img_test_tool", "arguments": {}}]}
        else:
            yield {"type": "content", "text": "done"}

    async def vision_models(server, names):
        return list(names) if can_see else []

    monkeypatch.setattr(llm, "stream_chat", stream_chat)
    monkeypatch.setattr(llm, "vision_models", vision_models)
    monkeypatch.setattr(tools_config, "is_enabled", lambda: True)
    monkeypatch.setattr(tools_config, "tool_enabled", lambda name: True)
    monkeypatch.setattr(tools_config, "get_max_iterations", lambda: 5)
    resp = build_stream_response(chat_id, _TARGET, "m", [{"role": "user", "content": "hi"}], use_tools=True)
    events = []
    async for chunk in resp.body_iterator:
        events += [json.loads(line) for line in chunk.splitlines() if line.strip()]
    return seen[1], [e for e in events if e["type"] == "tool_result"]


async def test_a_vision_model_gets_the_image_after_the_tool_results(monkeypatch, chat_id, image_tool):
    messages, results = await _second_call(monkeypatch, chat_id, can_see=True)
    assert results == [{"type": "tool_result", "name": "img_test_tool", "ok": True}]
    tool_msg, image_msg = messages[-2], messages[-1]
    assert tool_msg["role"] == "tool" and NO_VISION_NOTE not in tool_msg["content"]
    assert image_msg == {"role": "user", "content": TOOL_IMAGES_NOTICE, "images": [_URI]}


async def test_a_model_that_cannot_see_is_told_and_gets_no_image(monkeypatch, chat_id, image_tool):
    messages, results = await _second_call(monkeypatch, chat_id, can_see=False)
    assert results == [{"type": "tool_result", "name": "img_test_tool", "ok": True}]
    assert not any(m.get("images") for m in messages)
    assert messages[-1]["role"] == "tool"
    assert NO_VISION_NOTE.strip() in messages[-1]["content"]
