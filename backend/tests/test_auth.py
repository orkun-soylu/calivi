"""Registration, sessions, super-admin rules and blocking behaviour."""
from conftest import login, register

from app import auth as auth_core
from app.routers import auth as auth_router


async def test_first_signup_becomes_super_admin(client):
    me = await register(client, "first")
    assert me["id"] == 1 and me["role"] == "admin"


async def test_second_signup_is_a_regular_user(client, user_client):
    await register(client, "admin")
    me = await register(user_client, "second")
    assert me["id"] == 2 and me["role"] == "user"


async def test_request_without_session_is_401(client):
    assert (await client.get("/api/chats")).status_code == 401


async def test_wrong_password_is_rejected(client):
    await register(client, "someone")
    assert (await login(client, "someone", "wrong")).status_code >= 400


async def test_login_with_email_or_username(client):
    await register(client, "someone")
    await client.post("/api/auth/logout")
    assert (await login(client, "someone")).status_code == 200
    assert (await client.post(
        "/api/auth/login", json={"identifier": "someone@test.local", "password": "password123"}
    )).status_code == 200


async def test_unknown_user_login_still_runs_bcrypt(client, monkeypatch):
    """Timing-oracle regression: the unknown-account path must pay the same bcrypt cost
    as the real one (against _DUMMY_HASH), or response time reveals valid usernames."""
    calls = []
    original = auth_core.verify_password

    def spy(password, password_hash):
        calls.append(password_hash)
        return original(password, password_hash)

    monkeypatch.setattr(auth_core, "verify_password", spy)
    await register(client, "someone")

    await login(client, "someone", "wrong")          # real user, wrong password
    await login(client, "no-such-user", "wrong")     # unknown user
    assert len(calls) == 2                            # bcrypt ran BOTH times
    assert calls[0] != calls[1]                       # real hash vs the dummy
    assert calls[1] == auth_router._DUMMY_HASH


async def test_logout_ends_the_session(client):
    await register(client, "someone")
    await client.post("/api/auth/logout")
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_blocked_user_gets_401(admin, user_client):
    """Blocking must take effect immediately: even with a valid cookie the next request is 401."""
    await register(user_client, "victim")
    assert (await user_client.get("/api/chats")).status_code == 200

    await admin.patch("/api/users/2", json={"blocked": True})

    assert (await user_client.get("/api/chats")).status_code == 401  # → frontend auto-logout
    assert (await login(user_client, "victim")).status_code == 403  # logging back in is closed too


async def test_super_admin_cannot_be_demoted_blocked_or_deleted(admin, user_client):
    await register(user_client, "otheradmin")
    await admin.patch("/api/users/2", json={"role": "admin"})  # make them a real admin

    # Not even a second admin may touch id 1 (business rule, not a role check)
    assert (await user_client.patch("/api/users/1", json={"role": "user"})).status_code >= 400
    assert (await user_client.patch("/api/users/1", json={"blocked": True})).status_code >= 400
    assert (await user_client.delete("/api/users/1")).status_code >= 400
    assert (await admin.get("/api/auth/me")).json()["role"] == "admin"


async def test_closing_registration_rejects_new_signups(admin, user_client):
    await admin.patch("/api/settings", json={"registration_enabled": False})
    assert (await user_client.get("/api/auth/config")).json()["registration_enabled"] is False

    resp = await user_client.post(
        "/api/auth/register",
        json={"email": "new@test.local", "username": "new", "password": "password123"},
    )
    assert resp.status_code >= 400


async def test_deleted_id_is_never_reused(admin, user_client):
    """The users table is sqlite_autoincrement → a deleted id is not handed to a new user."""
    await register(user_client, "temporary")
    await admin.delete("/api/users/2")
    newer = await register(user_client, "next")
    assert newer["id"] == 3
