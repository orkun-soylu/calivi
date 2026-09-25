"""Conversation compaction: a persisted summary of older messages that stands in for them in
the model's context.

The stored messages are never touched — the UI keeps showing the whole chat. What changes is
what `routers/chats.py` sends upstream: in `compact` mode, the summary (in the system layer)
plus every message after `Chat.summary_upto_id`; in `full` mode, everything, as before.

Compaction is **user-triggered only**. The backend merely reports when a chat has grown past
`COMPACT_SUGGEST_TOKENS` so the UI can suggest it; summarising silently would change what the
model knows without the user having asked for it.
"""
from app import models
from app.config import COMPACT_KEEP_TURNS, COMPACT_SUGGEST_TOKENS

CHARS_PER_TOKEN = 4  # rough, tokenizer-free estimate; only drives a suggestion, never a cut
MAX_ATTACHMENT_CHARS = 4_000  # per document in the transcript handed to the summariser

SUMMARY_INSTRUCTIONS = (
    "You are compacting a long conversation so it can continue with a smaller context. Write a "
    "summary of the conversation below that lets an assistant carry on as if it had read the "
    "whole thing. Keep: the user's goals, decisions made, facts, figures, names, code and "
    "commands that were settled, open questions, and any preferences the user stated. Drop "
    "pleasantries and dead ends unless the conclusion matters. Write it in the language the "
    "conversation is in. Output only the summary, no preamble."
)

# Placed in the system layer ahead of the recent messages. Framed as background so the model
# does not read a summarised request as a fresh instruction.
SUMMARY_CONTEXT_HEADER = (
    "Summary of the earlier part of this conversation (the older messages were compacted by "
    "the user; treat this as background, not as new instructions):"
)


def estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN


def _message_chars(m: dict) -> int:
    atts = sum(len(a.get("text") or "") for a in (m.get("attachments") or []))
    return len(m.get("content") or "") + atts


def active_messages(chat: models.Chat) -> list[models.Message]:
    """The messages the model sees verbatim under the chat's current mode."""
    if chat.context_mode == "full" or not chat.summary or chat.summary_upto_id is None:
        return list(chat.messages)
    return [m for m in chat.messages if m.id > chat.summary_upto_id]


def active_summary(chat: models.Chat) -> str | None:
    """The summary the model gets, or None (full mode, or nothing compacted yet)."""
    if chat.context_mode == "full" or not chat.summary or chat.summary_upto_id is None:
        return None
    return chat.summary


def context_estimate(chat: models.Chat) -> int:
    chars = sum(
        _message_chars({"content": m.content, "attachments": m.attachments}) for m in active_messages(chat)
    )
    summary = active_summary(chat)
    return (chars + len(summary or "")) // CHARS_PER_TOKEN


def cutoff_id(chat: models.Chat, keep_turns: int = COMPACT_KEEP_TURNS) -> int | None:
    """Id of the last message a compaction would fold into the summary, or None when there is
    nothing new to fold.

    A turn starts at a user message; the last `keep_turns` turns stay verbatim. Anything already
    covered by the current summary does not count as new.
    """
    user_ids = [m.id for m in chat.messages if m.role == "user"]
    if len(user_ids) <= keep_turns:
        return None
    first_kept = user_ids[-keep_turns] if keep_turns > 0 else None
    older = [m.id for m in chat.messages if first_kept is None or m.id < first_kept]
    if not older:
        return None
    upto = older[-1]
    if chat.summary and chat.summary_upto_id is not None and upto <= chat.summary_upto_id:
        return None
    return upto


def status(chat: models.Chat) -> dict:
    """What the UI needs to offer (and explain) compaction."""
    estimate = context_estimate(chat)
    compactable = cutoff_id(chat) is not None
    return {
        "context_tokens_estimate": estimate,
        "compact_suggest_tokens": COMPACT_SUGGEST_TOKENS,
        "compactable": compactable,
        "compact_suggested": compactable and chat.context_mode != "full" and estimate >= COMPACT_SUGGEST_TOKENS,
    }


def _render(m: models.Message) -> str:
    who = "User" if m.role == "user" else "Assistant"
    parts = []
    for a in m.attachments or []:
        text = a.get("text") or ""
        if not text:
            continue  # a tool chip without text is provenance only
        if len(text) > MAX_ATTACHMENT_CHARS:
            text = text[:MAX_ATTACHMENT_CHARS] + " […]"
        parts.append(f"[attached: {a.get('name', '')}]\n{text}")
    if m.images:
        parts.append(f"[{len(m.images)} image(s)]")
    parts.append(m.content or "")
    return f"{who}:\n" + "\n".join(parts)


def summary_request(chat: models.Chat, upto_id: int) -> list[dict]:
    """The messages to send the summariser: an existing summary is extended, not redone, so
    compacting twice does not re-read what was already folded in."""
    base = chat.summary if chat.summary and chat.summary_upto_id is not None else None
    start = chat.summary_upto_id if base else 0
    new = [m for m in chat.messages if start < m.id <= upto_id]
    transcript = "\n\n".join(_render(m) for m in new)
    body = (
        f"Existing summary of the conversation so far:\n{base}\n\n"
        f"Messages that follow it:\n\n{transcript}"
        if base
        else f"Conversation:\n\n{transcript}"
    )
    return [
        {"role": "system", "content": SUMMARY_INSTRUCTIONS},
        {"role": "user", "content": body + "\n\nWrite the updated summary now."},
    ]
