"""Retired-model filtering (self-healing picker).

Ollama Cloud retires models (on 2026-07-15 it retired gemini-3-flash-preview and
qwen3-coder:480b). The stub stays in `/api/tags` but `/api/show` and `/api/chat` answer
HTTP 410 → the model looked selectable in the picker and the chat blew up on use.
These tests check the model is dropped and that the filtering is NOT overly aggressive.
"""
import httpx
import pytest

from app import llm, ollama_client
from app.routers import servers as S

RETIRED = {"error": "gemini-3-flash-preview was retired at 2026-07-15 00:00:00 -0700 PDT"}


class FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)

    def json(self):
        return self._payload


@pytest.fixture
def show(monkeypatch):
    """Fakes `/api/show` responses per model name; `.calls` records the calls.

    `routes` is read through the fixture object (NOT a local variable) so that rebinding it
    inside a test with `show.routes = {...}` also takes effect.
    """

    class Show:
        def __init__(self):
            self.routes: dict[str, object] = {}
            self.calls: list[str] = []

    state = Show()

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json):
            name = json["model"]
            state.calls.append(name)
            r = state.routes[name]
            if isinstance(r, Exception):
                raise r
            return r

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())
    return state


def _live(*caps):
    return FakeResp(200, {"capabilities": list(caps)})


async def test_retired_model_is_marked_dead(show):
    show.routes = {"retired": FakeResp(410, RETIRED), "alive": _live("completion")}
    caps = await ollama_client.model_capabilities("h", 1, ["retired", "alive"])
    assert caps["retired"].alive is False
    assert caps["alive"].alive is True


async def test_a_transient_error_does_not_hide_the_model(show):
    """A timeout must not empty the picker — uncertainty does not mean "dead"."""
    show.routes = {"m": httpx.ConnectTimeout("timeout")}
    caps = await ollama_client.model_capabilities("h", 1, ["m"])
    assert caps["m"].alive is True
    assert caps["m"].vision is False


async def test_a_transient_error_is_not_cached_permanently(show):
    """The except branch used to persist False forever: a single timeout branded the model
    "not vision" until a restart. Once the failure passes the right answer must return."""
    show.routes = {"m": httpx.ConnectTimeout("timeout")}
    await ollama_client.model_capabilities("h", 1, ["m"])

    show.routes = {"m": _live("vision")}
    caps = await ollama_client.model_capabilities("h", 1, ["m"])
    assert caps["m"].vision is True


async def test_the_dead_verdict_is_not_cached_permanently(show):
    """If a model returns from retirement (or the 410 was transient) it must recover."""
    show.routes = {"m": FakeResp(410, RETIRED)}
    await ollama_client.model_capabilities("h", 1, ["m"])

    show.routes = {"m": _live("completion")}
    caps = await ollama_client.model_capabilities("h", 1, ["m"])
    assert caps["m"].alive is True


async def test_the_vision_verdict_is_cached(show):
    """A successful result is cached forever — the 3s refresh must not repeat /api/show."""
    show.routes = {"m": _live("vision")}
    await ollama_client.model_capabilities("h", 1, ["m"])
    await ollama_client.model_capabilities("h", 1, ["m"])
    assert show.calls == ["m"]


async def test_llm_drops_the_retired_model_from_the_list(show):
    show.routes = {"retired": FakeResp(410, RETIRED), "seeing": _live("vision")}
    live, vis = await llm.model_capabilities(
        {"type": "ollama", "host": "h", "port": 1}, ["retired", "seeing"]
    )
    assert live == ["seeing"]
    assert vis == ["seeing"]


async def test_no_filtering_on_openai_servers(show):
    """OpenAI-compatible servers give no liveness signal — /v1/models is the only truth."""
    live, _ = await llm.model_capabilities(
        {"type": "openai", "base_url": "http://x/v1"}, ["a", "moonshot-v1-8k-vision-preview"]
    )
    assert live == ["a", "moonshot-v1-8k-vision-preview"]


async def test_endpoint_does_not_expose_a_retired_model(admin, monkeypatch, show):
    """End to end: GET /api/servers must not return the retired model in `models`."""

    async def fake_probe(spec):
        return "up", ["retired", "alive"]

    monkeypatch.setattr(llm, "probe", fake_probe)
    show.routes = {"retired": FakeResp(410, RETIRED), "alive": _live("completion")}

    await admin.post("/api/servers", json={"name": "s", "host": "127.0.0.1", "port": 1})
    S._cache.clear()

    srv = (await admin.get("/api/servers")).json()[0]
    assert srv["models"] == ["alive"]


async def test_filtering_is_not_too_aggressive(show):
    """The static counterpart of deliberately breaking the guard: a non-410 error code must
    NOT drop the model (only 410 is a definitive signal)."""
    show.routes = {"m": FakeResp(500, {"error": "server error"})}
    caps = await ollama_client.model_capabilities("h", 1, ["m"])
    assert caps["m"].alive is True
