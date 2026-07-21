"""Secrets stored in the database (MCP tokens, provider API keys) are encrypted at rest.

The threat model is an attacker holding `calivi.db` without the environment the app runs in —
a nightly backup, a copied volume. So the assertions are made against the **raw column**, not
through the ORM: reading it back through the ORM would pass just as well with no encryption
at all, which is exactly the test that would have missed this.
"""
import pytest
from sqlalchemy import text

from app import config, crypto
from app.database import engine, _migrate


def _raw(table: str, col: str, row_id: int):
    """The bytes as the database file holds them — no ORM, no decryption."""
    with engine.connect() as conn:
        return conn.execute(
            text(f"SELECT {col} FROM {table} WHERE id = :i"), {"i": row_id}
        ).scalar()


def _write_raw(table: str, col: str, row_id: int, value: str):
    with engine.connect() as conn:
        conn.execute(text(f"UPDATE {table} SET {col} = :v WHERE id = :i"), {"v": value, "i": row_id})
        conn.commit()


@pytest.fixture(autouse=True)
def _restore_cipher():
    """Key changes are global — put it back, or every later test decrypts with the wrong key."""
    yield
    crypto.reset_cipher()


async def _add_mcp(admin, secret="ghp_supersecret_token_value"):
    resp = await admin.post("/api/mcp", json={
        "name": "ctx7", "url": "https://mcp.example.com/mcp", "secret": secret,
    })
    assert resp.status_code < 400, resp.text
    return resp.json()["id"], secret


async def test_mcp_secret_is_ciphertext_at_rest(admin):
    server_id, secret = await _add_mcp(admin)

    stored = _raw("mcp_servers", "secret", server_id)
    assert secret not in stored
    assert crypto.looks_encrypted(stored)


async def test_api_key_is_ciphertext_at_rest(admin):
    resp = await admin.post("/api/servers", json={
        "name": "openai", "type": "openai",
        "base_url": "https://api.openai.com/v1", "api_key": "sk-live-abcdef123456",
    })
    assert resp.status_code < 400, resp.text

    stored = _raw("servers", "api_key", resp.json()["id"])
    assert "sk-live-abcdef123456" not in stored
    assert crypto.looks_encrypted(stored)


async def test_the_secret_still_reaches_the_mcp_server(admin):
    """Encryption is transparent where it matters: the outgoing Authorization header."""
    from app import models
    from app.database import SessionLocal
    from app.tools import mcp_client

    server_id, secret = await _add_mcp(admin)
    with SessionLocal() as db:
        server = db.get(models.McpServer, server_id)
        assert server.secret == secret  # decrypted on the attribute
        assert mcp_client.build_headers(server)["Authorization"] == f"Bearer {secret}"


async def test_a_plaintext_row_from_an_older_release_is_still_readable(admin):
    """An upgrade must not look like data loss while the migration has not run yet."""
    from app import models
    from app.database import SessionLocal

    server_id, _ = await _add_mcp(admin)
    _write_raw("mcp_servers", "secret", server_id, "legacy-plaintext-token")

    with SessionLocal() as db:
        assert db.get(models.McpServer, server_id).secret == "legacy-plaintext-token"


async def test_the_migration_encrypts_what_older_releases_left_behind(admin):
    from app import models
    from app.database import SessionLocal

    server_id, _ = await _add_mcp(admin)
    _write_raw("mcp_servers", "secret", server_id, "legacy-plaintext-token")

    _migrate()

    stored = _raw("mcp_servers", "secret", server_id)
    assert crypto.looks_encrypted(stored) and "legacy-plaintext-token" not in stored
    with SessionLocal() as db:
        assert db.get(models.McpServer, server_id).secret == "legacy-plaintext-token"


async def test_a_secret_from_another_key_is_dropped_not_fatal(admin, monkeypatch):
    """One unreadable secret must not take the settings page down with it."""
    from app import models
    from app.database import SessionLocal

    server_id, _ = await _add_mcp(admin)
    monkeypatch.setattr(config, "SECRET_KEY", "a-completely-different-key")
    crypto.reset_cipher()

    with SessionLocal() as db:
        assert db.get(models.McpServer, server_id).secret is None

    resp = await admin.get("/api/mcp")
    assert resp.status_code == 200
    assert resp.json()[0]["has_secret"] is False


async def test_rotation_re_encrypts_under_the_new_key(admin, monkeypatch):
    """CALIVI_SECRET_KEY_OLD is the supported way through a key change."""
    from app import models
    from app.database import SessionLocal

    server_id, secret = await _add_mcp(admin)
    written_under_old = _raw("mcp_servers", "secret", server_id)

    # The rotation: the old key moves to _OLD, a new one takes its place.
    monkeypatch.setattr(config, "SECRET_KEY_OLD", config.SECRET_KEY)
    monkeypatch.setattr(config, "SECRET_KEY", "the-new-key-after-rotation")
    crypto.reset_cipher()

    _migrate()

    rotated = _raw("mcp_servers", "secret", server_id)
    assert rotated != written_under_old, "the stored token was not re-encrypted"
    with SessionLocal() as db:
        assert db.get(models.McpServer, server_id).secret == secret

    # And once the old key is taken away again, the value is still readable.
    monkeypatch.setattr(config, "SECRET_KEY_OLD", "")
    crypto.reset_cipher()
    with SessionLocal() as db:
        assert db.get(models.McpServer, server_id).secret == secret
