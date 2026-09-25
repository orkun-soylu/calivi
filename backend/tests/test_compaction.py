"""Conversation compaction (#62): a user-triggered summary that stands in for older messages
in the model's context, while the stored messages — and the UI — keep the whole chat.

Every test drives the real endpoints and records what reached the model, because the point of
the feature is exactly that: what the model is sent, not what the database holds.
"""
import json

import pytest

from app import compaction, llm, models
from app.database import SessionLocal, _migrate, engine

TURNS = 6  # with COMPACT_KEEP_TURNS=4, turns 1-2 are folded and 3-6 stay verbatim


class FakeModel:
    """Records every request and answers with a fixed text."""

    def __init__(self, reply="SUMMARY-1"):
        self.reply = reply
        self.calls: list[list[dict]] = []

    async def stream_chat(self, target, model, messages, tools=None):
        self.calls.append(messages)
        if self.reply:
            yield {"type": "content", "text": self.reply}


@pytest.fixture
def fake(monkeypatch):
    f = FakeModel()
    monkeypatch.setattr(llm, "stream_chat", f.stream_chat)
    return f


@pytest.fixture
async def chat(admin):
    """A chat of TURNS user/assistant turns owned by the admin, plus a server to target."""
    await admin.post("/api/servers", json={"name": "s", "host": "127.0.0.1", "port": 1})
    chat_id = (await admin.post("/api/chats", json={"title": "long"})).json()["id"]
    with SessionLocal() as db:
        for i in range(1, TURNS + 1):
            db.add(models.Message(chat_id=chat_id, role="user", content=f"question {i}"))
            db.add(models.Message(chat_id=chat_id, role="assistant", content=f"answer {i}"))
        db.commit()
    return admin, chat_id


def _ids(chat_id):
    with SessionLocal() as db:
        rows = db.query(models.Message).filter(models.Message.chat_id == chat_id).order_by(models.Message.id)
        return [m.id for m in rows]


async def _events(resp):
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


async def _compact(client, chat_id):
    resp = await client.post(f"/api/chats/{chat_id}/compact", json={"server_id": 1, "model": "m"})
    return resp, await _events(resp) if resp.status_code == 200 else []


def _sent_text(messages):
    return "\n".join(m.get("content") or "" for m in messages)


# ── Compacting ────────────────────────────────────────────────────────────────


async def test_compaction_folds_all_but_the_last_turns(chat, fake):
    client, chat_id = chat
    resp, events = await _compact(client, chat_id)
    assert resp.status_code == 200
    assert events[-1]["type"] == "compacted"

    request = _sent_text(fake.calls[0])
    assert "question 1" in request and "answer 2" in request
    assert "question 3" not in request  # kept verbatim, not summarised

    detail = (await client.get(f"/api/chats/{chat_id}")).json()
    assert detail["summary"] == "SUMMARY-1"
    assert detail["summary_upto_id"] == _ids(chat_id)[3]  # "answer 2"
    assert len(detail["messages"]) == TURNS * 2  # nothing is deleted


async def test_after_compaction_the_model_gets_summary_plus_recent_turns(chat, fake):
    client, chat_id = chat
    await _compact(client, chat_id)
    fake.reply = "ok"
    await client.post(f"/api/chats/{chat_id}/messages", json={"content": "next", "server_id": 1, "model": "m"})

    sent = fake.calls[-1]
    assert sent[0]["role"] == "system" and "SUMMARY-1" in sent[0]["content"]
    text = _sent_text(sent[1:])
    assert "question 1" not in text and "answer 2" not in text
    assert "question 3" in text and "next" in text


async def test_full_mode_sends_the_whole_history_and_no_summary(chat, fake):
    client, chat_id = chat
    await _compact(client, chat_id)
    assert (await client.patch(f"/api/chats/{chat_id}", json={"context_mode": "full"})).status_code == 200
    fake.reply = "ok"
    await client.post(f"/api/chats/{chat_id}/messages", json={"content": "next", "server_id": 1, "model": "m"})

    text = _sent_text(fake.calls[-1])
    assert "SUMMARY-1" not in text
    assert "question 1" in text and "question 6" in text

    # The summary is kept, so switching back is free.
    await client.patch(f"/api/chats/{chat_id}", json={"context_mode": "compact"})
    assert (await client.get(f"/api/chats/{chat_id}")).json()["summary"] == "SUMMARY-1"


async def test_compacting_again_extends_the_summary_instead_of_rereading(chat, fake):
    client, chat_id = chat
    await _compact(client, chat_id)
    with SessionLocal() as db:
        for i in (7, 8):
            db.add(models.Message(chat_id=chat_id, role="user", content=f"question {i}"))
            db.add(models.Message(chat_id=chat_id, role="assistant", content=f"answer {i}"))
        db.commit()
    fake.reply = "SUMMARY-2"
    resp, _ = await _compact(client, chat_id)
    assert resp.status_code == 200

    request = _sent_text(fake.calls[-1])
    assert "SUMMARY-1" in request  # the old summary is the starting point
    assert "question 1" not in request  # already folded in, not re-read
    assert "question 3" in request and "answer 4" in request
    assert "question 5" not in request


async def test_nothing_to_compact_is_a_400(admin, fake):
    await admin.post("/api/servers", json={"name": "s", "host": "127.0.0.1", "port": 1})
    chat_id = (await admin.post("/api/chats", json={"title": "short"})).json()["id"]
    with SessionLocal() as db:
        db.add(models.Message(chat_id=chat_id, role="user", content="hi"))
        db.commit()
    resp, _ = await _compact(admin, chat_id)
    assert resp.status_code == 400
    assert not fake.calls


async def test_an_empty_summary_is_not_saved(chat, fake):
    client, chat_id = chat
    fake.reply = ""
    _, events = await _compact(client, chat_id)
    assert events[-1]["type"] == "error"
    assert (await client.get(f"/api/chats/{chat_id}")).json()["summary"] is None


async def test_upstream_failure_saves_nothing(chat, monkeypatch):
    client, chat_id = chat

    async def broken(target, model, messages, tools=None):
        raise RuntimeError("down")
        yield  # pragma: no cover

    monkeypatch.setattr(llm, "stream_chat", broken)
    _, events = await _compact(client, chat_id)
    assert events[-1]["type"] == "error"
    assert (await client.get(f"/api/chats/{chat_id}")).json()["summary"] is None


async def test_a_chat_rewritten_mid_summary_is_not_overwritten(chat, monkeypatch):
    """Two tabs: one compacts while the other edits an early message (which drops the summary
    base) or finishes its own compaction. The slower summary describes a chat that no longer
    exists and must not land."""
    client, chat_id = chat

    async def racing(target, model, messages, tools=None):
        with SessionLocal() as db:
            c = db.get(models.Chat, chat_id)
            c.summary, c.summary_upto_id = "OTHER TAB", _ids(chat_id)[1]
            db.commit()
        yield {"type": "content", "text": "STALE"}

    monkeypatch.setattr(llm, "stream_chat", racing)
    _, events = await _compact(client, chat_id)
    assert events[-1]["type"] == "error"
    assert (await client.get(f"/api/chats/{chat_id}")).json()["summary"] == "OTHER TAB"


# ── Suggestion ────────────────────────────────────────────────────────────────


async def test_detail_suggests_compaction_past_the_threshold(chat, monkeypatch):
    client, chat_id = chat
    detail = (await client.get(f"/api/chats/{chat_id}")).json()
    assert detail["compactable"] is True
    assert detail["compact_suggested"] is False  # a dozen short messages

    monkeypatch.setattr(compaction, "COMPACT_SUGGEST_TOKENS", 1)
    detail = (await client.get(f"/api/chats/{chat_id}")).json()
    assert detail["compact_suggested"] is True
    assert detail["context_tokens_estimate"] > 0


async def test_estimate_shrinks_after_compaction(chat, fake):
    client, chat_id = chat
    with SessionLocal() as db:
        first = db.get(models.Message, _ids(chat_id)[0])
        first.content = "x" * 40_000
        db.commit()
    before = (await client.get(f"/api/chats/{chat_id}")).json()["context_tokens_estimate"]
    await _compact(client, chat_id)
    after = (await client.get(f"/api/chats/{chat_id}")).json()
    assert after["context_tokens_estimate"] < before
    assert after["compactable"] is False  # nothing new since


# ── Edits, deletes, forks ─────────────────────────────────────────────────────


async def test_editing_a_summarised_message_drops_the_summary(chat, fake):
    client, chat_id = chat
    await _compact(client, chat_id)
    first = _ids(chat_id)[0]
    fake.reply = "ok"
    await client.put(
        f"/api/chats/{chat_id}/messages/{first}", json={"content": "changed", "server_id": 1, "model": "m"}
    )
    assert (await client.get(f"/api/chats/{chat_id}")).json()["summary"] is None
    assert "SUMMARY-1" not in _sent_text(fake.calls[-1])


async def test_editing_a_recent_message_keeps_the_summary(chat, fake):
    client, chat_id = chat
    await _compact(client, chat_id)
    last_user = _ids(chat_id)[-2]
    fake.reply = "ok"
    await client.put(
        f"/api/chats/{chat_id}/messages/{last_user}", json={"content": "changed", "server_id": 1, "model": "m"}
    )
    assert (await client.get(f"/api/chats/{chat_id}")).json()["summary"] == "SUMMARY-1"
    assert "SUMMARY-1" in _sent_text(fake.calls[-1])


async def test_deleting_a_summarised_message_drops_the_summary(chat, fake):
    client, chat_id = chat
    await _compact(client, chat_id)
    await client.delete(f"/api/chats/{chat_id}/messages/{_ids(chat_id)[1]}")
    assert (await client.get(f"/api/chats/{chat_id}")).json()["summary"] is None


async def test_fork_after_the_summary_carries_it_over(chat, fake):
    client, chat_id = chat
    await _compact(client, chat_id)
    fake.reply = "ok"
    resp = await client.post(
        f"/api/chats/{chat_id}/fork",
        json={"message_id": _ids(chat_id)[-2], "content": "forked", "server_id": 1, "model": "m"},
    )
    new_id = int(resp.headers["X-Calivi-Chat-Id"])
    forked = (await client.get(f"/api/chats/{new_id}")).json()
    assert forked["summary"] == "SUMMARY-1"
    assert forked["summary_upto_id"] == _ids(new_id)[3]  # remapped onto the copy
    assert "SUMMARY-1" in _sent_text(fake.calls[-1])


async def test_fork_from_inside_the_summary_does_not_inherit_it(chat, fake):
    client, chat_id = chat
    await _compact(client, chat_id)
    fake.reply = "ok"
    resp = await client.post(
        f"/api/chats/{chat_id}/fork",
        json={"message_id": _ids(chat_id)[2], "content": "forked", "server_id": 1, "model": "m"},
    )
    new_id = int(resp.headers["X-Calivi-Chat-Id"])
    assert (await client.get(f"/api/chats/{new_id}")).json()["summary"] is None
    assert "SUMMARY-1" not in _sent_text(fake.calls[-1])


# ── Migration ─────────────────────────────────────────────────────────────────


def test_migrate_adds_the_compaction_columns_to_an_old_chats_table():
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.exec_driver_sql("DROP TABLE chats")
        conn.exec_driver_sql(
            "CREATE TABLE chats (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL DEFAULT 1, "
            "title VARCHAR(255) NOT NULL, pinned BOOLEAN NOT NULL DEFAULT 0, "
            "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
        )
        conn.exec_driver_sql(
            "INSERT INTO chats (id, title, created_at, updated_at) VALUES (1, 'old', '2026-01-01', '2026-01-01')"
        )
        conn.commit()

    _migrate()

    with engine.connect() as conn:
        cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(chats)").fetchall()]
        mode = conn.exec_driver_sql("SELECT context_mode FROM chats WHERE id = 1").scalar()
    assert {"summary", "summary_upto_id", "context_mode"} <= set(cols)
    assert mode == "compact"
