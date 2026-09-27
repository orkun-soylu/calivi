"""calivi-vm machine notes (#110): ~/.calivi/AGENTS.md, read into the system layer of every turn
that offers the host tools, and changed only with the owner's approval.

Everything runs as the test user in a temporary home (the `home` fixture); the real `~` is never
read or written.
"""
import getpass
import json

import pytest

from app import llm, models, tools_config
from app.database import SessionLocal
from app.routers.chats import build_stream_response
from app.tools import host
from app.tools.registry import registry

TARGET = {"name": "s", "type": "ollama", "host": "h", "port": 1, "base_url": None, "api_key": None}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(host, "_account", lambda: (getpass.getuser(), str(tmp_path)))
    return tmp_path


def _write_notes(home, text):
    (home / ".calivi").mkdir(exist_ok=True)
    (home / ".calivi" / "AGENTS.md").write_text(text)


# --- Reading -----------------------------------------------------------------------------------


async def test_present_notes_go_into_the_block(home):
    _write_notes(home, "# box\n- ollama on :11434, models in /srv/models\n")
    part = await host.notes_system_part()
    assert part.startswith(host.NOTES_INTRO)
    assert "- ollama on :11434, models in /srv/models" in part
    assert part.rstrip().endswith("----- end of notes -----")


async def test_missing_notes_invite_the_model_to_start_them(home):
    part = await host.notes_system_part()
    assert part.startswith(host.NOTES_INTRO) and "does not exist yet" in part
    assert not (home / ".calivi").exists()  # reading creates nothing


async def test_oversize_notes_are_cut_with_a_note(home):
    _write_notes(home, "x" * (host.NOTES_MAX_CHARS + 500) + "TAIL")
    part = await host.notes_system_part()
    assert "TAIL" not in part and "condense it" in part
    assert len(part) < len(host.NOTES_INTRO) + host.NOTES_MAX_CHARS + 300


async def test_an_unreadable_file_or_no_owner_never_breaks_the_turn(home, monkeypatch):
    (home / ".calivi").mkdir()
    (home / ".calivi" / "AGENTS.md").mkdir()  # a directory: head fails
    assert await host.notes_system_part() is None

    def no_owner():
        raise LookupError("no host account is configured yet")

    monkeypatch.setattr(host, "_account", no_owner)
    assert await host.notes_system_part() is None


async def test_the_read_runs_in_the_owner_home(home, monkeypatch):
    """Through _run — as the owner, via sudo on the VM — with the path relative to that home."""
    seen = {}

    async def fake_run(script, *argv, **kw):
        seen["argv"] = argv
        return 0, "notes"

    monkeypatch.setattr(host, "_run", fake_run)
    assert (await host.read_notes()) == ("ok", "notes")
    assert seen["argv"][0] == ".calivi/AGENTS.md"


# --- Approval ----------------------------------------------------------------------------------


def _tool(name):
    return next(t for t in host.TOOLS if t.name == name)


@pytest.mark.parametrize("path", [
    "~/.calivi/AGENTS.md",
    ".calivi/AGENTS.md",
    "~/x/../.calivi/AGENTS.md",
    "~/.calivi/other.md",       # anything under ~/.calivi
    "~/.calivi",
])
def test_writing_the_notes_asks(home, path):
    for name in ("write_file", "edit_file"):
        assert _tool(name).requires_approval({"path": path, "content": "", "old_string": "a", "new_string": "b"})
    assert _tool("write_file").requires_approval({"path": str(home / ".calivi/AGENTS.md"), "content": ""})


@pytest.mark.parametrize("path", ["~/notes.md", "~/.calivirc", "~/.calivi-backup/AGENTS.md", "project/AGENTS.md"])
def test_other_files_in_home_still_do_not_ask(home, path):
    assert not _tool("write_file").requires_approval({"path": path, "content": ""})


@pytest.mark.parametrize("cmd", [
    "echo '- nginx on :80' >> ~/.calivi/AGENTS.md",
    "sed -i 's/a/b/' .calivi/AGENTS.md",
    "cd ~/.calivi && rm AGENTS.md",
    "cat ~/.calivi/AGENTS.md",
])
def test_bash_touching_the_notes_asks(cmd):
    assert _tool("bash").requires_approval({"command": cmd})


@pytest.mark.parametrize("cmd", ["ls ~/.calivirc", "pip install calivi", "cat AGENTS.md", "systemctl status calivi"])
def test_bash_look_alikes_do_not_ask(cmd):
    assert not _tool("bash").requires_approval({"command": cmd})


# --- The system layer --------------------------------------------------------------------------


@pytest.fixture
def host_tools(monkeypatch):
    monkeypatch.setattr(tools_config, "is_enabled", lambda: True)
    monkeypatch.setattr(tools_config, "tool_enabled", lambda name: True)
    for t in host.TOOLS:
        registry.register(t)
    yield
    for t in host.TOOLS:
        registry._tools.pop(t.name, None)


@pytest.fixture
def seen(monkeypatch):
    calls = []

    async def stream_chat(target, model, messages, tools=None):
        calls.append([dict(m) for m in messages])
        yield {"type": "content", "text": "ok"}

    monkeypatch.setattr(llm, "stream_chat", stream_chat)
    return calls


def _chat():
    db = SessionLocal()
    try:
        u = db.query(models.User).first() or models.User(
            email="n@test.local", username="n", password_hash="x", role="admin")
        db.add(u)
        db.commit()
        c = models.Chat(user_id=u.id, title="t", mode="agent")
        db.add(c)
        db.commit()
        return c.id
    finally:
        db.close()


async def _turn(user_id, use_tools=True):
    resp = build_stream_response(_chat(), TARGET, "m", [{"role": "user", "content": "hi"}],
                                 use_tools=use_tools, user_id=user_id, agent=True)
    [json.loads(line) async for chunk in resp.body_iterator for line in chunk.splitlines() if line.strip()]


async def test_the_owner_turn_carries_the_notes(home, host_tools, seen):
    _write_notes(home, "- the owner's rule: no reboots before 18:00\n")
    await _turn(user_id=1)
    system = seen[0][0]
    assert system["role"] == "system"
    assert "no reboots before 18:00" in system["content"]
    assert host.NOTES_INTRO in system["content"]


async def test_no_notes_without_the_host_tools(home, host_tools, seen):
    _write_notes(home, "SECRET-ISH MACHINE DETAIL\n")
    await _turn(user_id=2)                   # another user: never offered the host tools
    await _turn(user_id=1, use_tools=False)  # the owner, tools off
    for messages in seen:
        assert not any("SECRET-ISH MACHINE DETAIL" in (m.get("content") or "") for m in messages)
