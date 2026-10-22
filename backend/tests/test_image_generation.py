"""Image-generation models: detection, the `/images/generations` client and the image turn.

An image model (Qwen-Image, FLUX, gpt-image...) is picked like a chat model; its turn sends the
last user message as the prompt and saves the picture on the reply. Before this, picking one sent
a chat request to a server that only makes pictures.
"""
import base64
import json

import httpx
import pytest

from app import llm, models, openai_client, vision
from app.database import SessionLocal
from app.routers import chats
from app.routers.chats import build_stream_response

OPENAI = {"name": "gpu-box", "type": "openai", "host": "", "port": 0,
          "base_url": "http://img.test/v1", "api_key": "k"}
OLLAMA = {"name": "o", "type": "ollama", "host": "h", "port": 1, "base_url": None, "api_key": None}


def _png(w: int, h: int) -> bytes:
    """Only the header matters: signature, IHDR length/type, width, height."""
    return (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + w.to_bytes(4, "big") + h.to_bytes(4, "big")
            + b"\x08\x02\x00\x00\x00" + b"\x00" * 16)


def _uri(raw: bytes, mime="image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


# ── detection ────────────────────────────────────────────────────────────────

def _overrides(text: str):
    with open(vision.VISION_OVERRIDES_PATH, "w") as f:
        f.write(text)


@pytest.fixture(autouse=True)
def no_overrides():
    _overrides("")
    yield
    _overrides("")


@pytest.mark.parametrize("name", ["qwen-image-2.1", "FLUX.1-dev", "sdxl-turbo", "dall-e-3", "gpt-image-1",
                                  "stabilityai/stable-diffusion-3.5-large"])
def test_image_model_names_are_recognised(name):
    assert vision.is_image_generator(name)


@pytest.mark.parametrize("name", ["iq3_s-2gpu", "qwen3.8:27b-q8_0", "gpt-4o", "qwen2.5-vl-7b", "kimi-k2"])
def test_chat_model_names_are_not(name):
    assert not vision.is_image_generator(name)


def test_force_chat_beats_the_name_and_force_image_adds_one():
    _overrides("force_chat: [flux]\nforce_image: [my-painter]\n")
    assert not vision.is_image_generator("flux.1-dev")
    assert vision.is_image_generator("My-Painter-v2")


def test_a_broken_override_file_falls_back_to_the_name():
    _overrides("- just\n- a list\n")
    assert vision.is_image_generator("qwen-image-2.1")
    assert vision.apply_overrides("x", True) is True


def test_only_openai_servers_have_image_models():
    names = ["qwen-image-2.1", "qwen3.8:27b"]
    assert llm.image_models(OPENAI, names) == ["qwen-image-2.1"]
    assert llm.image_models(OLLAMA, names) == []


async def test_server_list_reports_image_models(client, admin, monkeypatch):
    async def probe(server):
        return "up", ["iq3_s-2gpu", "qwen-image-2.1"]

    monkeypatch.setattr(llm, "probe", probe)
    db = SessionLocal()
    db.add(models.Server(name="gpu-box", type="openai", host="", port=0, base_url="http://img.test/v1"))
    db.commit()
    db.close()
    r = await client.get("/api/servers")
    srv = r.json()[0]
    assert srv["models"] == ["iq3_s-2gpu", "qwen-image-2.1"]
    assert srv["image_models"] == ["qwen-image-2.1"]


# ── client ───────────────────────────────────────────────────────────────────

@pytest.fixture
def upstream(monkeypatch):
    """Routes httpx.AsyncClient to a handler; records the requests."""
    state = {"handler": None, "requests": []}
    real = httpx.AsyncClient

    def handler(request):
        state["requests"].append(request)
        return state["handler"](request)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return state


async def test_b64_answer_becomes_a_data_uri(upstream):
    raw = _png(1024, 768)
    upstream["handler"] = lambda r: httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(raw).decode()}]})
    out = await openai_client.generate_image("http://img.test/v1/", "k", "qwen-image-2.1", "a fox")
    assert out["images"] == [_uri(raw)]
    req = upstream["requests"][0]
    assert str(req.url) == "http://img.test/v1/images/generations"
    assert req.headers["authorization"] == "Bearer k"
    body = json.loads(req.content)
    # gpt-image models reject response_format; the server's own default sizes and steps apply
    assert body == {"model": "qwen-image-2.1", "prompt": "a fox", "n": 1}


async def test_a_url_answer_is_fetched_so_the_chat_keeps_the_picture(upstream):
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 20

    def handler(r):
        if r.url.path.endswith("/images/generations"):
            return httpx.Response(200, json={"data": [{"url": "http://cdn.test/p.jpg", "revised_prompt": "A red fox"}]})
        return httpx.Response(200, content=jpeg)

    upstream["handler"] = handler
    out = await openai_client.generate_image("http://img.test/v1", None, "dall-e-3", "fox")
    assert out == {"images": [_uri(jpeg, "image/jpeg")], "revised_prompt": "A red fox"}


def test_image_size_reads_png_and_jpeg_headers():
    assert openai_client.image_size(_uri(_png(1328, 1328))) == (1328, 1328)
    sof = b"\xff\xd8" + b"\xff\xe0\x00\x04\x00\x00" + b"\xff\xc0\x00\x11\x08" + (600).to_bytes(2, "big") + (800).to_bytes(2, "big") + b"\x00" * 12
    assert openai_client.image_size(_uri(sof, "image/jpeg")) == (800, 600)
    assert openai_client.image_size("data:image/png;base64,AAAA") is None


# ── the turn ─────────────────────────────────────────────────────────────────

@pytest.fixture
def chat_id():
    db = SessionLocal()
    try:
        user = models.User(email="i@test.local", username="img", password_hash="x", role="admin")
        db.add(user)
        db.commit()
        chat = models.Chat(user_id=user.id, title="t")
        db.add(chat)
        db.commit()
        return chat.id
    finally:
        db.close()


async def _run(chat_id, history, model="qwen-image-2.1", target=OPENAI):
    resp = build_stream_response(chat_id, target, model, history, use_tools=True)
    events = []
    async for chunk in resp.body_iterator:
        events += [json.loads(l) for l in chunk.splitlines() if l.strip()]
    return events


def _replies(chat_id):
    db = SessionLocal()
    try:
        return db.query(models.Message).filter_by(chat_id=chat_id, role="assistant").all()
    finally:
        db.close()


async def test_the_last_user_message_is_the_prompt_and_the_picture_is_saved(chat_id, monkeypatch):
    seen = {}

    async def gen(server, model, prompt):
        seen.update(model=model, prompt=prompt)
        return {"images": [_uri(_png(1024, 1024))], "revised_prompt": None}

    async def no_chat(*a, **kw):
        raise AssertionError("an image model must not get a chat request")
        yield

    monkeypatch.setattr(llm, "generate_image", gen)
    monkeypatch.setattr(llm, "stream_chat", no_chat)
    history = [{"role": "user", "content": "a cat"}, {"role": "assistant", "content": "..."},
               {"role": "user", "content": "  a fox in the snow  "}]
    events = await _run(chat_id, history)
    assert seen == {"model": "qwen-image-2.1", "prompt": "a fox in the snow"}
    assert events[0] == {"type": "search", "status": "image_generating"}
    assert events[-1]["type"] == "content" and events[-1]["text"].startswith("1024×1024 · ")
    [reply] = _replies(chat_id)
    assert reply.images == [_uri(_png(1024, 1024))]
    assert reply.content.startswith("1024×1024")
    assert (reply.model_used, reply.server_used) == ("qwen-image-2.1", "gpu-box")


async def test_a_slow_picture_keeps_the_stream_alive(chat_id, monkeypatch):
    import asyncio

    async def slow(server, model, prompt):
        await asyncio.sleep(0.05)
        return {"images": [_uri(_png(64, 64))], "revised_prompt": None}

    monkeypatch.setattr(llm, "generate_image", slow)
    monkeypatch.setattr(chats, "IMAGE_HEARTBEAT", 0.01)
    events = await _run(chat_id, [{"role": "user", "content": "x"}])
    assert {"type": "ping"} in events
    assert len(_replies(chat_id)) == 1


async def test_no_text_means_no_request(chat_id, monkeypatch):
    async def gen(*a):
        raise AssertionError("nothing to draw")

    monkeypatch.setattr(llm, "generate_image", gen)
    events = await _run(chat_id, [{"role": "user", "content": " ", "images": ["data:image/png;base64,AAAA"]}])
    assert events == [{"type": "error", "message": chats.NO_PROMPT_MESSAGE}]
    [reply] = _replies(chat_id)
    assert reply.content == f"⚠️ {chats.NO_PROMPT_MESSAGE}" and not reply.images


async def test_the_servers_own_error_text_reaches_the_user(chat_id, monkeypatch):
    async def gen(*a):
        req = httpx.Request("POST", "http://img.test/v1/images/generations")
        resp = httpx.Response(400, json={"error": {"message": "2048x4096 is larger than this model allows"}}, request=req)
        raise httpx.HTTPStatusError("400", request=req, response=resp)

    monkeypatch.setattr(llm, "generate_image", gen)
    events = await _run(chat_id, [{"role": "user", "content": "x"}])
    assert events[-1]["type"] == "error"
    assert "HTTP 400" in events[-1]["message"] and "larger than this model allows" in events[-1]["message"]
    [reply] = _replies(chat_id)
    assert reply.content.startswith("⚠️") and not reply.images


async def test_chat_models_on_the_same_server_still_chat(chat_id, monkeypatch):
    async def chat(target, model, messages, tools=None):
        yield {"type": "content", "text": "hello"}

    async def no_image(*a):
        raise AssertionError("a chat model must not get an image request")

    monkeypatch.setattr(llm, "stream_chat", chat)
    monkeypatch.setattr(llm, "generate_image", no_image)
    await _run(chat_id, [{"role": "user", "content": "hi"}], model="iq3_s-2gpu")
    assert [m.content for m in _replies(chat_id)] == ["hello"]


def test_a_generated_picture_is_not_sent_back_as_history(chat_id):
    db = SessionLocal()
    try:
        db.add_all([
            models.Message(chat_id=chat_id, role="user", content="look", images=["data:image/png;base64,U"]),
            models.Message(chat_id=chat_id, role="assistant", content="1024×1024 · 30 s", images=["data:image/png;base64,A"]),
        ])
        db.commit()
        history, _ = chats._context_of(db, chat_id)
    finally:
        db.close()
    assert [m["images"] for m in history] == [["data:image/png;base64,U"], []]
