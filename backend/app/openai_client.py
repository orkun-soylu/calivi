import base64
import json
import time

import httpx

from app.config import IMAGE_GEN_TIMEOUT, OPENAI_PROBE_TIMEOUT, OLLAMA_CHAT_TIMEOUT


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


async def generate_image(base_url: str, api_key: str | None, model: str, prompt: str,
                         options: dict | None = None) -> dict:
    """One picture from the OpenAI-compatible `/images/generations`.

    Returns {"images": [data URI, ...], "revised_prompt", "seed", "steps"} — the last three None
    unless the server reports them (a diffusers server does; OpenAI does not). `response_format`
    is not sent: gpt-image models reject the parameter, and a server that answers with a `url`
    instead of `b64_json` (dall-e's default) is followed and the picture fetched, so the chat
    keeps the image itself rather than a link that expires.

    `options` ({size, steps, seed}): only the keys that are set go out. `steps` and `seed` are not
    in OpenAI's API and OpenAI rejects unknown parameters, so leaving them unset keeps such a
    server working; size, steps and seed left out are the server's defaults.
    """
    url = base_url.rstrip("/") + "/images/generations"
    payload = {"model": model, "prompt": prompt, "n": 1}
    payload.update({k: v for k, v in (options or {}).items() if k in ("size", "steps", "seed") and v is not None})
    images, revised, seed, steps = [], None, None, None
    async with httpx.AsyncClient(timeout=httpx.Timeout(IMAGE_GEN_TIMEOUT, connect=10)) as client:
        resp = await client.post(url, json=payload, headers=_headers(api_key))
        resp.raise_for_status()
        for item in resp.json().get("data") or []:
            revised = revised or item.get("revised_prompt")
            if seed is None and isinstance(item.get("seed"), int):
                seed = item["seed"]
            if steps is None and isinstance(item.get("steps"), int):
                steps = item["steps"]
            if item.get("b64_json"):
                raw = base64.b64decode(item["b64_json"])
            elif item.get("url"):
                got = await client.get(item["url"])
                got.raise_for_status()
                raw = got.content
            else:
                continue
            images.append(f"data:{_image_mime(raw)};base64,{base64.b64encode(raw).decode()}")
    return {"images": images, "revised_prompt": revised, "seed": seed, "steps": steps}


def _image_mime(raw: bytes) -> str:
    if raw.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def image_size(data_uri: str) -> tuple[int, int] | None:
    """(width, height) of a PNG/JPEG/WebP data URI, read from its header; None if unknown."""
    try:
        raw = base64.b64decode(data_uri.split(",", 1)[1][:4096] + "==")
    except (IndexError, ValueError):
        return None
    if raw[:8] == b"\x89PNG\r\n\x1a\n" and len(raw) >= 24:
        return int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")
    if raw[:4] == b"RIFF" and raw[12:16] == b"VP8 " and len(raw) >= 30:
        return int.from_bytes(raw[26:28], "little") & 0x3FFF, int.from_bytes(raw[28:30], "little") & 0x3FFF
    if raw[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(raw):
            if raw[i] != 0xFF:
                return None
            marker, length = raw[i + 1], int.from_bytes(raw[i + 2:i + 4], "big")
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                return int.from_bytes(raw[i + 7:i + 9], "big"), int.from_bytes(raw[i + 5:i + 7], "big")
            i += 2 + length
    return None
