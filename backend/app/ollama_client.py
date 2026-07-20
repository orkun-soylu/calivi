import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import httpx

from app.config import OLLAMA_PROBE_TIMEOUT, OLLAMA_CHAT_TIMEOUT


async def probe_server(host: str, port: int) -> tuple[str, list[str]]:
    """Returns (status, model_names). status is 'up' or 'down'."""
    url = f"http://{host}:{port}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=OLLAMA_PROBE_TIMEOUT) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            names = sorted(m["name"] for m in data.get("models", []))
            return "up", names
    except (httpx.HTTPError, ValueError):
        return "down", []


@dataclass(frozen=True)
class ModelCaps:
    """A model's state as seen through `/api/show`.

    `alive=False` is set ONLY on a definitive signal (HTTP 410 — upstream retired the
    model). On ambiguous failures such as a timeout or connection error the model counts
    as live: a momentary glitch must not empty the picker.
    """

    alive: bool = True
    vision: bool = False


# (host, port, model) → is it vision-capable. ONLY successful (200) answers are stored;
# capabilities do not change, so the entry never expires (this is what stops the 3s refresh
# from repeating /api/show).
# "Dead" verdicts and transient errors are NOT written here — that decision is left to the
# TTL'd probe cache in servers.py, so a model returning from retirement (or a transient
# failure) recovers on its own. (The except branch used to persist False here: a single
# timeout would brand a model "not vision" until the next restart.)
_vision_cache: dict[tuple[str, int, str], bool] = {}

RETIRED_STATUS = 410  # how Ollama Cloud reports a retired model ("<model> was retired at ...")


async def model_capabilities(host: str, port: int, model_names: list[str]) -> dict[str, ModelCaps]:
    """Liveness + vision status per model (the vision part is cached)."""
    result: dict[str, ModelCaps] = {}
    async with httpx.AsyncClient(timeout=OLLAMA_PROBE_TIMEOUT) as client:
        for name in model_names:
            key = (host, port, name)
            if key in _vision_cache:
                result[name] = ModelCaps(vision=_vision_cache[key])
                continue
            try:
                resp = await client.post(f"http://{host}:{port}/api/show", json={"model": name})
                if resp.status_code == RETIRED_STATUS:
                    result[name] = ModelCaps(alive=False)  # not cached: it may come back
                    continue
                resp.raise_for_status()
                is_vision = "vision" in (resp.json().get("capabilities") or [])
            except (httpx.HTTPError, ValueError):
                result[name] = ModelCaps()  # uncertain → treat as live, do not cache
                continue
            _vision_cache[key] = is_vision
            result[name] = ModelCaps(vision=is_vision)
    return result


def _strip_data_uri(uri: str) -> str:
    """`data:image/png;base64,XXXX` → `XXXX` (Ollama expects raw base64)."""
    return uri.split(",", 1)[1] if uri.startswith("data:") else uri


def _to_ollama_msg(m: dict) -> dict:
    """Converts the internal message format to Ollama /api/chat format (images as raw base64)."""
    # Tool result message (agentic loop) → role:"tool"
    if m.get("role") == "tool":
        return {"role": "tool", "content": m.get("content", ""), "tool_name": m.get("name", "")}
    # The assistant's tool-call turn → send tool_calls back in Ollama's format
    tool_calls = m.get("tool_calls")
    if tool_calls:
        return {
            "role": "assistant",
            "content": m.get("content", ""),
            "tool_calls": [{"function": {"name": c["name"], "arguments": c.get("arguments") or {}}} for c in tool_calls],
        }
    images = m.get("images")
    if images:
        return {"role": m["role"], "content": m.get("content", ""), "images": [_strip_data_uri(u) for u in images]}
    return {"role": m["role"], "content": m.get("content", "")}


async def stream_chat(
    host: str, port: int, model: str, messages: list[dict], tools: list[dict] | None = None
) -> AsyncGenerator[dict, None]:
    """Streams {"type": "thinking"|"content", "text": str} pieces from Ollama's /api/chat endpoint.

    Reasoning models (e.g. Qwen3.6) emit a "thinking" phase with empty content before any
    content arrives — that phase can take tens of seconds. We must forward it too, otherwise
    the response stream goes silent long enough for an intermediate proxy to drop the connection.

    When `tools` is given it is added to the payload; if the model asks for a tool,
    `message.tool_calls` arrives and a single {"type":"tool_calls","calls":[...]} piece is
    yielded at the end of the stream (Ollama does not assign ids to tool calls, so f"call_{i}"
    is synthesised). `arguments` already arrives as a dict/object.
    """
    url = f"http://{host}:{port}/api/chat"
    payload = {"model": model, "messages": [_to_ollama_msg(m) for m in messages], "stream": True}
    if tools:
        payload["tools"] = tools

    tool_calls: list[dict] = []
    async with httpx.AsyncClient(timeout=OLLAMA_CHAT_TIMEOUT) as client:
        async with client.stream("POST", url, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                message = chunk.get("message", {})
                thinking = message.get("thinking", "")
                content = message.get("content", "")
                for tc in message.get("tool_calls") or []:
                    fn = tc.get("function") or {}
                    tool_calls.append({
                        "id": f"call_{len(tool_calls)}",
                        "name": fn.get("name", ""),
                        "arguments": fn.get("arguments") or {},
                    })
                if thinking:
                    yield {"type": "thinking", "text": thinking}
                if content:
                    yield {"type": "content", "text": content}
                if chunk.get("done"):
                    # Generation speed as measured by Ollama itself: eval_count tokens /
                    # eval_duration (ns). Pure generation, excluding model load and prompt
                    # processing. Cloud models (remote proxy) do not report eval_duration,
                    # only total_duration → fall back to it (the rate then looks slightly
                    # lower because prompt processing and network time are included).
                    eval_count = chunk.get("eval_count")
                    duration = chunk.get("eval_duration") or chunk.get("total_duration")
                    if eval_count and duration:
                        yield {"type": "stats", "tokens_per_sec": eval_count / (duration / 1e9)}
                    break

    if tool_calls:
        yield {"type": "tool_calls", "calls": tool_calls}
