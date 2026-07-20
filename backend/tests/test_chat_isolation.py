"""Chat ownership isolation — a user must not reach someone else's chat by any route.

The point of this file is to guarantee that the `chats.py::_owned_chat` scope is applied on
**every** endpoint: if a new chat endpoint is added and the scope is forgotten, this breaks.
"""
import pytest

from app import models
from app.database import SessionLocal
from conftest import register


def _add_message(chat_id: int) -> int:
    """Puts a real message in the owner's chat, so ownership is the ONLY source of the 404 in
    message-based tests (otherwise it is indistinguishable from a "no such message" 404)."""
    with SessionLocal() as db:
        m = models.Message(chat_id=chat_id, role="user", content="secret message")
        db.add(m)
        db.commit()
        return m.id


@pytest.fixture
async def two_users(client, user_client):
    """admin (id1) creates a chat; user_client (id2) is the outsider.

    A REAL server is registered too: without it the message/fork/edit tests would mistake
    `resolve_target`'s "Server not found" 404 for the ownership 404 and pass FOR THE WRONG
    REASON (caught by mutation testing). With the server present, `_owned_chat` is the only
    possible source of a 404.
    """
    await register(client, "owner")
    await register(user_client, "outsider")
    await client.post("/api/servers", json={"name": "s", "host": "127.0.0.1", "port": 1})
    chat = (await client.post("/api/chats", json={"title": "Secret"})).json()
    _add_message(chat["id"])
    return client, user_client, chat["id"]


async def test_outsider_does_not_see_the_chat_in_the_list(two_users):
    _, outsider, _ = two_users
    assert (await outsider.get("/api/chats")).json() == []


async def test_outsider_cannot_read_the_chat(two_users):
    _, outsider, chat_id = two_users
    assert (await outsider.get(f"/api/chats/{chat_id}")).status_code == 404


async def test_outsider_cannot_modify_the_chat(two_users):
    owner, outsider, chat_id = two_users
    assert (await outsider.patch(f"/api/chats/{chat_id}", json={"title": "hijacked"})).status_code == 404
    assert (await owner.get(f"/api/chats/{chat_id}")).json()["title"] == "Secret"


async def test_outsider_cannot_delete_the_chat(two_users):
    owner, outsider, chat_id = two_users
    assert (await outsider.delete(f"/api/chats/{chat_id}")).status_code == 404
    assert (await owner.get(f"/api/chats/{chat_id}")).status_code == 200


async def test_outsider_cannot_post_a_message(two_users):
    """The highest-risk leak path: sending a message feeds the history to the model."""
    _, outsider, chat_id = two_users
    resp = await outsider.post(
        f"/api/chats/{chat_id}/messages",
        json={"content": "hello", "server_id": 1, "model": "m"},
    )
    assert resp.status_code == 404


async def test_outsider_cannot_fork_the_chat(two_users):
    """Fork copies history into a NEW chat — if the scope escapes, it leaks data directly."""
    _, outsider, chat_id = two_users
    resp = await outsider.post(
        f"/api/chats/{chat_id}/fork",
        json={"message_id": 1, "content": "x", "server_id": 1, "model": "m"},
    )
    assert resp.status_code == 404


async def test_outsider_cannot_delete_or_edit_messages(two_users):
    _, outsider, chat_id = two_users
    assert (await outsider.delete(f"/api/chats/{chat_id}/messages/1")).status_code == 404
    resp = await outsider.put(
        f"/api/chats/{chat_id}/messages/1",
        json={"content": "x", "server_id": 1, "model": "m"},
    )
    assert resp.status_code == 404


async def test_not_even_an_admin_can_reach_another_users_chat(client, user_client):
    """A role upgrade does NOT pierce chat isolation — admins manage servers/users, not chats."""
    await register(client, "admin")
    await register(user_client, "user")
    chat = (await user_client.post("/api/chats", json={"title": "Personal"})).json()

    assert (await client.get(f"/api/chats/{chat['id']}")).status_code == 404
    assert (await client.get("/api/chats")).json() == []


async def test_missing_chat_is_404(client):
    await register(client, "someone")
    assert (await client.get("/api/chats/9999")).status_code == 404
