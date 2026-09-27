"""First registration on the appliance (host_bootstrap.py + /api/auth/register).

The root helper is replaced in every endpoint test — nothing here creates an account. The one
test that runs a real process (`run_helper`'s exit-code mapping) runs a harmless Python
one-liner in place of the helper.
"""
import sys

import pytest

from app import config, host_bootstrap
from tests.conftest import register

CODE = "ABCD-EFGH-JKLM-NPQR"
BODY = {"email": "o@test.local", "username": "owner", "password": "password123"}


@pytest.fixture
def appliance(monkeypatch, tmp_path):
    """Host tools on, a setup code on disk, and a recording stand-in for the root helper."""
    code_file = tmp_path / "setup-code"
    code_file.write_text(CODE + "\n")
    monkeypatch.setattr(config, "HOST_TOOLS_ENABLED", True)
    monkeypatch.setattr(config, "HOST_SETUP_CODE_FILE", str(code_file))
    calls = []
    monkeypatch.setattr(host_bootstrap, "run_helper", lambda req: calls.append(req))
    return calls


async def _config(client):
    return (await client.get("/api/auth/config")).json()


async def test_a_normal_install_is_untouched(client, monkeypatch):
    calls = []
    monkeypatch.setattr(host_bootstrap, "run_helper", lambda req: calls.append(req))
    assert (await _config(client))["host_setup"] is False
    me = await register(client, "anyone")  # no code, uppercase-free or not — nothing asked
    assert me["id"] == 1 and calls == []
    assert (await _config(client))["registration_enabled"] is True


async def test_config_announces_the_setup_only_before_the_owner(client, appliance):
    assert (await _config(client))["host_setup"] is True
    await client.post("/api/auth/register", json={**BODY, "setup_code": CODE})
    assert (await _config(client))["host_setup"] is False


@pytest.mark.parametrize("code,status", [(None, 403), ("", 403), ("WRONG-CODE", 403)])
async def test_no_owner_without_the_code(client, appliance, code, status):
    resp = await client.post("/api/auth/register", json={**BODY, "setup_code": code})
    assert resp.status_code == status
    assert appliance == []  # the helper was never reached
    assert (await _config(client))["host_setup"] is True  # and nobody was registered


async def test_a_missing_code_file_fails_closed(client, appliance, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "HOST_SETUP_CODE_FILE", str(tmp_path / "missing"))
    resp = await client.post("/api/auth/register", json={**BODY, "setup_code": "anything"})
    assert resp.status_code == 503
    assert appliance == []


async def test_a_username_linux_would_refuse_is_caught_before_the_helper(client, appliance):
    resp = await client.post(
        "/api/auth/register", json={**BODY, "username": "Owner", "setup_code": CODE}
    )
    assert resp.status_code == 400 and "Linux" in resp.json()["detail"]
    assert appliance == []


async def test_the_owner_is_created_with_the_machine(client, appliance):
    resp = await client.post("/api/auth/register", json={
        **BODY, "setup_code": CODE.lower(),  # typed from a console: case does not matter
        "hostname": " calivi-vm ", "timezone": "Europe/Istanbul", "ssh_key": "",
    })
    assert resp.status_code == 200, resp.text
    me = resp.json()
    assert me["id"] == 1 and me["role"] == "admin" and me["host_tools"] is True
    assert appliance == [{
        "username": "owner", "password": "password123",
        "hostname": "calivi-vm", "timezone": "Europe/Istanbul", "ssh_key": None,
    }]
    # Registration closes behind the owner.
    assert (await _config(client))["registration_enabled"] is False


async def test_a_failed_helper_leaves_no_calivi_user(client, appliance, monkeypatch):
    def fail(req):
        raise host_bootstrap.BootstrapError(400, "Unknown timezone.")

    monkeypatch.setattr(host_bootstrap, "run_helper", fail)
    resp = await client.post("/api/auth/register", json={**BODY, "setup_code": CODE})
    assert resp.status_code == 400 and resp.json()["detail"] == "Unknown timezone."
    assert (await _config(client))["host_setup"] is True  # still unclaimed, can retry


async def test_later_users_never_reach_the_helper(client, appliance, user_client):
    await client.post("/api/auth/register", json={**BODY, "setup_code": CODE})
    await client.patch("/api/settings", json={"registration_enabled": True})  # owner reopens
    second = await register(user_client, "second")
    assert second["id"] == 2 and second["host_tools"] is False
    assert len(appliance) == 1


@pytest.mark.parametrize("exit_code,status", [(1, 400), (3, 409), (4, 500), (2, 500)])
def test_helper_exit_codes(monkeypatch, exit_code, status):
    script = f"import sys; sys.stdin.read(); sys.stderr.write('msg'); sys.exit({exit_code})"
    monkeypatch.setattr(config, "HOST_BOOTSTRAP_CMD", [sys.executable, "-c", script])
    with pytest.raises(host_bootstrap.BootstrapError) as e:
        host_bootstrap.run_helper({"username": "owner", "password": "x"})
    assert e.value.status == status


def test_helper_gets_the_password_on_stdin_not_argv(monkeypatch):
    script = "import sys, json; r = json.load(sys.stdin); sys.exit(0 if r['password'] == 'pw' else 4)"
    cmd = [sys.executable, "-c", script]
    monkeypatch.setattr(config, "HOST_BOOTSTRAP_CMD", cmd)
    host_bootstrap.run_helper({"username": "owner", "password": "pw"})  # no raise
    assert not any("pw" == a for a in cmd)
