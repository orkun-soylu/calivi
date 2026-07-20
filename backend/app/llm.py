"""Thin dispatch layer that routes to the right client based on server type (ollama | openai).

`server` is a dict: {type, host, port, base_url, api_key}. Callers (servers.py, chats.py)
use this layer and stay unaware of the type distinction.
"""
from collections.abc import AsyncGenerator

from app import ollama_client, openai_client, vision


def _is_openai(server: dict) -> bool:
    return (server.get("type") or "ollama") == "openai"


async def probe(server: dict) -> tuple[str, list[str]]:
    if _is_openai(server):
        return await openai_client.probe(server.get("base_url") or "", server.get("api_key"))
    return await ollama_client.probe_server(server.get("host") or "", server.get("port") or 11434)


async def model_capabilities(server: dict, model_names: list[str]) -> tuple[list[str], list[str]]:
    """Returns (live models, vision-capable models).

    Liveness: on Ollama, `/api/show` returning HTTP 410 means upstream retired the model,
    so it is dropped from the list (leaving it selectable makes the chat blow up with 410).
    OpenAI-compatible servers offer no such signal — `/v1/models` is the only source of
    truth there, so everything it lists counts as live.
    Vision: Ollama → capabilities; OpenAI → name heuristic. Config overrides apply to both.
    """
    if _is_openai(server):
        live = list(model_names)
        base = {m: vision.name_looks_vision(m) for m in model_names}
    else:
        caps = await ollama_client.model_capabilities(
            server.get("host") or "", server.get("port") or 11434, model_names
        )
        live = [m for m in model_names if caps[m].alive]
        base = {m: c.vision for m, c in caps.items()}
    return live, [m for m in live if vision.apply_overrides(m, base.get(m, False))]


async def vision_models(server: dict, model_names: list[str]) -> list[str]:
    """Returns the vision-capable subset of model_names."""
    _, vis = await model_capabilities(server, model_names)
    return vis


async def _strip_images_if_not_vision(server: dict, model: str, messages: list[dict]) -> list[dict]:
    """Drops images from history when the target model has no vision support.

    In a multi-turn chat an earlier turn may have sent an image to a vision model. Once you
    switch to a NON-vision model those images are still in the history. Ollama /api/chat
    (and the Ollama Cloud proxy) answers 400 Bad Request when `images` reach a non-vision
    model, which surfaces as an empty reply. So if the target model is not vision-capable we
    drop the images before sending (text is kept — the model cannot see the image, but it
    does produce an answer).
    """
    if not any(m.get("images") for m in messages):
        return messages
    capable = await vision_models(server, [model])
    if model in capable:
        return messages
    return [_without_images(m) for m in messages]


# Substituted when stripping images empties a message completely. It also tells the model
# why there is a gap, so it does not invent a reason for being unable to answer.
IMAGE_STRIPPED_PLACEHOLDER = "[image removed: the selected model does not support images]"


def _without_images(m: dict) -> dict:
    """Drops `images` from a message; substitutes a placeholder if that empties it.

    Users can paste an image WITHOUT typing any text (content=""). Stripping the image from
    such a message leaves a completely empty user message, which upstream rejects with
    HTTP 400 (moonshot: "the message at position 0 with role 'user' must not be empty").
    In other words, image stripping was trading the 400 it prevented for a different one
    (2026-07-20). A placeholder is used rather than dropping the message outright: dropping
    it would leave the following assistant reply ("The image shows ...") without its prompt
    and break user/assistant alternation.
    """
    if not m.get("images"):
        return m
    stripped = {k: v for k, v in m.items() if k != "images"}
    if not (stripped.get("content") or "").strip():
        stripped["content"] = IMAGE_STRIPPED_PLACEHOLDER
    return stripped


async def stream_chat(
    server: dict, model: str, messages: list[dict], tools: list[dict] | None = None
) -> AsyncGenerator[dict, None]:
    """Streams a single model turn. When `tools` is given (native tool-calling) the model may
    request a tool; the clients then yield a `{"type":"tool_calls","calls":[...]}` piece
    (provider-agnostic internal contract). The agentic loop (chats.py) consumes it and runs
    the tool."""
    messages = await _strip_images_if_not_vision(server, model, messages)
    if _is_openai(server):
        gen = openai_client.stream_chat(
            server.get("base_url") or "", server.get("api_key"), model, messages, tools=tools
        )
    else:
        gen = ollama_client.stream_chat(
            server.get("host") or "", server.get("port") or 11434, model, messages, tools=tools
        )
    async for piece in gen:
        yield piece
