"""Config editor: whitelist plus YAML validation.

The critical behaviour: when malformed YAML is submitted the **file must not be corrupted** —
configs hot-reload, so a broken file would affect live chats immediately.
"""
import pytest

VALID = "default: you are a helpful assistant\n"
BROKEN = "default: [unclosed list\n  indent: broken\n"


async def test_unknown_config_is_404(admin):
    assert (await admin.get("/api/config/../../etc/passwd")).status_code == 404
    assert (await admin.get("/api/config/random")).status_code == 404
    assert (await admin.put("/api/config/random", json={"content": "x: 1"})).status_code == 404


async def test_write_read_round_trip(admin):
    assert (await admin.put("/api/config/system_prompts", json={"content": VALID})).status_code < 400
    assert (await admin.get("/api/config/system_prompts")).json()["content"] == VALID


async def test_broken_yaml_returns_400_and_leaves_the_file_intact(admin):
    await admin.put("/api/config/system_prompts", json={"content": VALID})

    resp = await admin.put("/api/config/system_prompts", json={"content": BROKEN})
    assert resp.status_code == 400

    # The important half: the previous content must still be there
    assert (await admin.get("/api/config/system_prompts")).json()["content"] == VALID


@pytest.mark.parametrize("name", ["system_prompts", "vision_models", "search", "tools"])
async def test_every_whitelisted_name_works(admin, name):
    assert (await admin.put(f"/api/config/{name}", json={"content": "a: 1\n"})).status_code < 400
    assert (await admin.get(f"/api/config/{name}")).json()["content"] == "a: 1\n"
