"""Account deletion — message content must NOT be orphaned in the DB (2026-07-04 privacy fix).

Historically `PRAGMA foreign_keys` was off (the SQLite default) and a bulk delete does not
trigger the ORM cascade, so deleting an account removed the chats but left the message rows
behind. If a new bulk delete forgets the child table, this file must break.
"""
from sqlalchemy import func, select

from app import models
from app.database import SessionLocal
from conftest import register


def _counts():
    with SessionLocal() as db:
        return (
            db.scalar(select(func.count()).select_from(models.Chat)),
            db.scalar(select(func.count()).select_from(models.Message)),
        )


def _add_message(chat_id: int, content: str):
    """Writes the message straight to the DB (a real send would need a live LLM server)."""
    with SessionLocal() as db:
        db.add(models.Message(chat_id=chat_id, role="user", content=content))
        db.commit()


async def test_admin_deleting_a_user_also_removes_messages(admin, user_client):
    await register(user_client, "victim")
    chat = (await user_client.post("/api/chats", json={"title": "Private"})).json()
    _add_message(chat["id"], "sensitive content")
    assert _counts() == (1, 1)

    assert (await admin.delete("/api/users/2")).status_code == 204
    assert _counts() == (0, 0)


async def test_self_service_deletion_clears_messages(admin, user_client):
    await register(user_client, "themselves")
    chat = (await user_client.post("/api/chats", json={"title": "Private"})).json()
    _add_message(chat["id"], "sensitive content")

    assert (await user_client.delete("/api/users/me")).status_code == 204
    assert _counts() == (0, 0)
    assert (await user_client.get("/api/chats")).status_code == 401  # session ended


async def test_deleting_a_chat_removes_its_messages(client):
    """The FK cascade must work for a single chat delete too (no orphan messages)."""
    await register(client, "someone")
    chat = (await client.post("/api/chats", json={"title": "Temporary"})).json()
    _add_message(chat["id"], "content")

    assert (await client.delete(f"/api/chats/{chat['id']}")).status_code == 204
    assert _counts() == (0, 0)


async def test_another_users_data_is_untouched(admin, user_client):
    """Deletion must cover only the targeted user."""
    admin_chat = (await admin.post("/api/chats", json={"title": "Admin chat"})).json()
    _add_message(admin_chat["id"], "admin data")

    await register(user_client, "victim")
    victim_chat = (await user_client.post("/api/chats", json={"title": "Victim"})).json()
    _add_message(victim_chat["id"], "victim data")

    await admin.delete("/api/users/2")

    assert _counts() == (1, 1)
    assert len((await admin.get("/api/chats")).json()) == 1
