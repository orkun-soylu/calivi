"""The appliance's root helper (appliance/bootstrap/calivi_bootstrap_user.py).

Only the pure half is tested: `build_plan` validates and returns steps, and nothing here ever
calls `execute` — this suite must be safe to run with every guard in it broken. The helper
runs as root on the VM and trusts nothing the backend sends, so each field is checked here
for what it lets through, not only for what it accepts.
"""
import datetime
import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "appliance/bootstrap/calivi_bootstrap_user.py"
_spec = importlib.util.spec_from_file_location("calivi_bootstrap_user", _PATH)
helper = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(helper)

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEXAMPLEEXAMPLEEXAMPLEEXAMPLEEXAMPLEEXAMPLE me@laptop"


def plan(**req):
    base = {"username": "owner", "password": "pw:with:colons"}
    return helper.build_plan(
        {**base, **req},
        user_exists=lambda name: name == "taken",
        zone_exists=lambda zone: zone in {"Europe/Istanbul", "UTC"},
        today=datetime.date(2026, 9, 27),
    )


def runs(p):
    return [s[1] for s in p if s[0] == "run"]


def writes(p):
    return {s[1]: s for s in p if s[0] == "write"}


def test_minimal_plan():
    p = plan()
    assert runs(p)[0] == ["useradd", "--create-home", "--shell", "/bin/bash", "--groups", "sudo",
                          "--", "owner"]
    assert p[1] == ("run", ["chpasswd"], "owner:pw:with:colons\n")
    w = writes(p)
    assert w["/etc/sudoers.d/90-calivi-owner"][2].endswith("owner ALL=(ALL:ALL) NOPASSWD: ALL\n")
    assert w["/etc/sudoers.d/80-calivi-host"][2].endswith("calivi ALL=(owner) NOPASSWD: ALL\n")
    assert w["/etc/sudoers.d/90-calivi-owner"][3] == 0o440
    # The marker the backend reads comes last, so a half-finished run never looks finished.
    assert p[-1] == ("write", helper.HOST_USER_FILE, "owner\n", 0o644, None)
    assert not any(a[0] in ("hostnamectl", "timedatectl") for a in runs(p))
    assert not any(a[-1].endswith("/.ssh") for a in runs(p))
    assert helper.CLOUD_HOSTNAME_CFG not in w


def test_the_password_never_reaches_argv():
    for argv in runs(plan(password="s3cret-pass")):
        assert not any("s3cret-pass" in a for a in argv)


def test_optional_steps_only_when_given():
    p = plan(hostname="calivi-vm", timezone="Europe/Istanbul", ssh_key=KEY + "\n")
    assert ["hostnamectl", "set-hostname", "calivi-vm"] in runs(p)
    assert ["timedatectl", "set-timezone", "Europe/Istanbul"] in runs(p)
    assert writes(p)[helper.CLOUD_HOSTNAME_CFG][2] == "preserve_hostname: true\n"
    key = writes(p)["/home/owner/.ssh/authorized_keys"]
    assert key[2] == KEY + "\n" and key[3] == 0o600 and key[4] == "owner"
    assert p[-1][1] == helper.HOST_USER_FILE


@pytest.mark.parametrize("username", [
    "Owner",           # Linux names are lowercase
    "1owner",
    "-oops",           # would read as an option
    "own er",
    "own;er",
    "a" * 33,
    "",
    None,
    "root",
    "calivi",          # the service account itself
    "taken",           # already exists
])
def test_bad_usernames_are_refused(username):
    with pytest.raises(helper.Invalid):
        plan(username=username)


@pytest.mark.parametrize("password", ["", None, "two\nlines", "cr\rhere", "nul\0byte"])
def test_bad_passwords_are_refused(password):
    """A newline would let a password smuggle a second `user:password` line into chpasswd."""
    with pytest.raises(helper.Invalid):
        plan(password=password)


@pytest.mark.parametrize("field,value", [
    ("hostname", "Calivi"),
    ("hostname", "-edge"),
    ("hostname", "a.b"),
    ("hostname", "x" * 64),
    ("hostname", "$(reboot)"),
    ("timezone", "Mars/Olympus"),
    ("timezone", "../../etc/passwd"),
    ("timezone", "Europe/Istanbul; reboot"),
    ("ssh_key", "not a key"),
    ("ssh_key", "-----BEGIN OPENSSH PRIVATE KEY-----"),
    ("ssh_key", KEY + "\n" + KEY),          # one line only
    ("ssh_key", "ssh-ed25519 AAAA\ncommand=\"reboot\""),
])
def test_bad_optional_fields_are_refused(field, value):
    with pytest.raises(helper.Invalid):
        plan(**{field: value})


def test_empty_optionals_are_skipped():
    assert plan(hostname="", timezone="", ssh_key="") == plan()


def test_the_machine_notes_are_seeded():
    """#110: the owner's ~/.calivi/AGENTS.md, owner-only, written before the claim marker."""
    p = plan(hostname="calivi-vm")
    assert ["install", "-d", "-m", "700", "-o", "owner", "-g", "owner", "/home/owner/.calivi"] in runs(p)
    notes = writes(p)["/home/owner/.calivi/AGENTS.md"]
    assert notes[3] == 0o600 and notes[4] == "owner"
    assert notes[2].startswith("# calivi-vm\n")
    assert "- Owner: owner (passwordless sudo)" in notes[2] and "2026-09-27" in notes[2]
    assert "## Owner's rules" in notes[2]
    order = [s[1] for s in p]
    assert order.index("/home/owner/.calivi/AGENTS.md") < order.index(helper.HOST_USER_FILE)
    assert "# This machine\n" in writes(plan())["/home/owner/.calivi/AGENTS.md"][2]
