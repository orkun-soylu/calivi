import json
import time

import httpx

from app.config import OPENAI_PROBE_TIMEOUT, OLLAMA_CHAT_TIMEOUT


def _headers(api_key: str | None) -> dict:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


async def probe(base_url: str, api_key: str | None) -> tuple[str, list[str]]:
    """Returns status and the model list via the OpenAI-compatible `/models` endpoint."""
    if not base_url:
        return "down", []
    url = base_url.rstrip("/") + "/models"
    try:
        async with httpx.AsyncClient(timeout=OPENAI_PROBE_TIMEOUT) as client:
            resp = await client.get(url, headers=_headers(api_key))
            resp.raise_for_status()
            data = resp.json()
            # Sort: some providers (e.g. Moonshot) return models in a different order on
            # every request → stabilise it so the dropdown does not shuffle on each refresh.
            names = sorted(m["id"] for m in data.get("data", []))
            return "up", names
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return "down", []


def _to_openai_msg(m: dict) -> dict:
    """Converts content to a multimodal array when images are present (text + image_url data-URI)."""
    # Tool result message (agentic loop) → role:"tool" + tool_call_id
    if m.get("role") == "tool":
        return {"role": "tool", "tool_call_id": m.get("tool_call_id", ""), "content": m.get("content", "")}
    # The assistant's tool-call turn → send tool_calls back in OpenAI format (arguments as a JSON string)
    tool_calls = m.get("tool_calls")
    if tool_calls:
        return {
            "role": "assistant",
            "content": m.get("content") or None,
            "tool_calls": [
                {
                    "id": c["id"],
                    "type": "function",
                    "function": {"name": c["name"], "arguments": json.dumps(c.get("arguments") or {})},
                }
                for c in tool_calls
            ],
        }
    images = m.get("images")
    if images:
        parts = [{"type": "image_url", "image_url": {"url": u}} for u in images]
        if m.get("content"):
            parts.insert(0, {"type": "text", "text": m["content"]})
        return {"role": m["role"], "content": parts}
    return {"role": m["role"], "content": m.get("content", "")}


async def stream_chat(base_url: str, api_key: str | None, model: str, messages: list[dict], tools: list[dict] | None = None):
    """Converts the OpenAI-compatible `/chat/completions` SSE stream into {"type","text"} pieces.

    When `tools` is given, `tools` and `tool_choice:"auto"` are added to the payload. If the
    model requests a tool, `delta.tool_calls` fragments accumulate per `index` (id + name +
    concatenated arguments string); at the end of the stream a single
    {"type":"tool_calls","calls":[...]} piece is yielded (arguments parsed into a dict).
    """
    url = base_url.rstrip("/") + "/chat/completions"
    # include_usage → completion_tokens arrives in the final (choices-less) chunk; needed for t/s.
    payload = {
        "model": model,
        "messages": [_to_openai_msg(m) for m in messages],
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    # The engine reports no duration, so measure wall-clock: first content token to last.
    first_at = None
    last_at = None
    completion_tokens = None
    # Accumulate tool_calls fragments per index: {index: {id, name, args_str}}
    tc_acc: dict[int, dict] = {}

    async with httpx.AsyncClient(timeout=OLLAMA_CHAT_TIMEOUT) as client:
        async with client.stream("POST", url, json=payload, headers=_headers(api_key)) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue  # skip blank lines and ": keep-alive" comments
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                usage = chunk.get("usage")
                if usage and usage.get("completion_tokens"):
                    completion_tokens = usage["completion_tokens"]
                choices = chunk.get("choices") or []
                if not choices:
                    continue  # usage-only chunk (choices is empty)
                delta = choices[0].get("delta", {})
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    slot = tc_acc.setdefault(idx, {"id": "", "name": "", "args": ""})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] = fn["name"]
                    if fn.get("arguments"):
                        slot["args"] += fn["arguments"]
                # Reasoning models (DeepSeek etc.) return thinking via reasoning_content/reasoning
                reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                content = delta.get("content")
                if reasoning:
                    yield {"type": "thinking", "text": reasoning}
                if content:
                    if first_at is None:
                        first_at = time.perf_counter()
                    last_at = time.perf_counter()
                    yield {"type": "content", "text": content}

    if completion_tokens and first_at is not None and last_at and last_at > first_at:
        yield {"type": "stats", "tokens_per_sec": completion_tokens / (last_at - first_at)}

    if tc_acc:
        calls = []
        for i in sorted(tc_acc):
            slot = tc_acc[i]
            try:
                args = json.loads(slot["args"]) if slot["args"].strip() else {}
            except ValueError:
                args = {}
            calls.append({"id": slot["id"] or f"call_{i}", "name": slot["name"], "arguments": args})
        yield {"type": "tool_calls", "calls": calls}
