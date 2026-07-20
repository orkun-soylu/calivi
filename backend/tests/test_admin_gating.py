"""Admin-only endpoints are closed to regular users; read-open endpoints stay open to all."""
from conftest import register


async def test_regular_user_cannot_add_a_server(admin, user_client):
    await register(user_client, "regular")
    resp = await user_client.post("/api/servers", json={"name": "fake", "host": "1.2.3.4"})
    assert resp.status_code == 403


async def test_regular_user_cannot_edit_or_delete_a_server(admin, user_client):
    await register(user_client, "regular")
    srv = (await admin.post("/api/servers", json={"name": "s", "host": "127.0.0.1", "port": 1})).json()

    assert (await user_client.patch(f"/api/servers/{srv['id']}", json={"name": "x"})).status_code == 403
    assert (await user_client.delete(f"/api/servers/{srv['id']}")).status_code == 403


async def test_regular_user_can_list_servers(admin, user_client):
    """GET must stay open — the chat picker depends on it."""
    await register(user_client, "regular")
    await admin.post("/api/servers", json={"name": "s", "host": "127.0.0.1", "port": 1})
    resp = await user_client.get("/api/servers")
    assert resp.status_code == 200 and len(resp.json()) == 1


async def test_api_key_is_never_returned(admin):
    """ServerOut must not leak api_key, only has_api_key."""
    await admin.post(
        "/api/servers",
        json={"name": "o", "type": "openai", "base_url": "http://x", "api_key": "sk-secret"},
    )
    body = (await admin.get("/api/servers")).text
    assert "sk-secret" not in body
    assert (await admin.get("/api/servers")).json()[0]["has_api_key"] is True


async def test_regular_user_cannot_manage_users(admin, user_client):
    await register(user_client, "regular")
    assert (await user_client.get("/api/users")).status_code == 403
    assert (await user_client.patch("/api/users/1", json={"role": "user"})).status_code == 403


async def test_regular_user_cannot_change_settings(admin, user_client):
    await register(user_client, "regular")
    assert (await user_client.patch("/api/settings", json={"registration_enabled": False})).status_code == 403


async def test_regular_user_can_read_config_but_not_write(admin, user_client):
    """system_prompts enter every chat as a system layer → writing is admin-only."""
    await register(user_client, "regular")
    await admin.put("/api/config/system_prompts", json={"content": "default: hello\n"})

    assert (await user_client.get("/api/config/system_prompts")).status_code == 200
    resp = await user_client.put("/api/config/system_prompts", json={"content": "default: hijacked\n"})
    assert resp.status_code == 403
    assert "hijacked" not in (await admin.get("/api/config/system_prompts")).json()["content"]
