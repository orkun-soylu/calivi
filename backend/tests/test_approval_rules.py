""""Always allow" rules (approval_rules.py, #113).

The rule language is checked as a pure function first — above all that nothing composed rides
on a simple rule — then in the loop, and through the card's endpoint.

SAFETY: the loop tests replace `bash` with a recording fake. Dangerous strings only ever reach
the pure matcher; a broken guard must fail a test, never run `rm` (see the guard-test note in
ARCHITECTURE.md).
"""
import getpass
import json

import pytest

from app import approval_rules, approvals, audit, config, llm, models, tools_config
from app.approval_rules import RuleError, matches, suggest, validate
from app.database import SessionLocal
from app.routers.chats import build_stream_response
from app.tools import host
from app.tools.registry import Tool, registry
from tests.conftest import register

TARGET = {"name": "s", "type": "ollama", "host": "h", "port": 1, "base_url": None, "api_key": None}
HOME = "/home/owner"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(host, "_account", lambda: (getpass.getuser(), HOME))


def bash(cmd):
    return {"command": cmd}


# --- bash: exact and prefix -----------------------------------------------------------------


def test_exact_matches_the_same_command_however_it_is_spelled():
    assert matches("bash", "exact", "systemctl restart ollama", bash("systemctl  restart 'ollama'"))
    assert not matches("bash", "exact", "systemctl restart ollama", bash("systemctl restart nginx"))
    assert not matches("bash", "exact", "systemctl restart ollama", bash("systemctl restart ollama --now"))


def test_prefix_matches_what_follows_but_not_less():
    assert matches("bash", "prefix", "sudo systemctl restart", bash("sudo systemctl restart ollama"))
    assert not matches("bash", "prefix", "sudo systemctl restart", bash("sudo systemctl"))
    assert not matches("bash", "prefix", "sudo systemctl restart", bash("systemctl restart ollama"))


COMPOSED = [
    "systemctl restart ollama; rm -rf ~",
    "systemctl restart ollama && rm -rf ~",
    "systemctl restart ollama || rm -rf ~",
    "systemctl restart ollama | sh",
    "systemctl restart ollama & rm -rf ~",
    "systemctl restart ollama $(rm -rf ~)",
    "systemctl restart ollama `rm -rf ~`",
    "systemctl restart ollama > /etc/passwd",
    "systemctl restart ollama < /dev/zero",
    "systemctl restart ollama\nrm -rf ~",
    "systemctl restart ollama $HOME",
    "systemctl restart ollama {a,b}",
    "systemctl restart ollama \\; rm",
    "systemctl restart 'ollama",  # unbalanced quote: not parseable, not covered
]


@pytest.mark.parametrize("cmd", COMPOSED)
def test_nothing_composed_rides_on_a_rule(cmd):
    assert not matches("bash", "prefix", "systemctl restart ollama", bash(cmd))
    assert suggest("bash", bash(cmd)) is None


def test_the_deny_list_and_the_notes_are_never_covered():
    # Pure classifier only: these strings never reach a shell.
    for cmd in ("rm -rf --no-preserve-root /", "cat ~/.calivi/AGENTS.md", "rm ~/.calivi/AGENTS.md"):
        assert not matches("bash", "exact", cmd, bash(cmd))
        with pytest.raises(RuleError):
            validate("bash", "exact", cmd)
    assert not matches("bash", "prefix", "rm -f old", bash("rm -f old ~/.calivi/AGENTS.md"))


@pytest.mark.parametrize("pattern", ["rm", "rm -rf", "sudo rm", "sudo", "sudo -n rm -r"])
def test_a_prefix_that_would_allow_too_much_is_refused(pattern):
    with pytest.raises(RuleError):
        validate("bash", "prefix", pattern)


def test_a_reasonable_prefix_is_accepted():
    assert validate("bash", "prefix", " sudo systemctl restart ") == "sudo systemctl restart"


def test_kinds_belong_to_their_tool():
    with pytest.raises(RuleError):
        validate("bash", "dir", "/etc")
    with pytest.raises(RuleError):
        validate("write_file", "prefix", "/etc")
    with pytest.raises(RuleError):
        validate("read_file", "dir", "/etc")


# --- file tools: dir ------------------------------------------------------------------------


def test_dir_covers_what_is_inside_it_and_nothing_else():
    rule = ("write_file", "dir", "/etc/nginx")
    assert matches(*rule, {"path": "/etc/nginx/sites-available/calivi"})
    assert not matches(*rule, {"path": "/etc/nginx-evil/x"})
    assert not matches(*rule, {"path": "/etc/nginx/../passwd"})  # normalised first
    assert not matches(*rule, {"path": "/etc/nginx"})


def test_the_notes_stay_out_of_any_dir_rule():
    assert not matches("write_file", "dir", "/home", {"path": f"{HOME}/.calivi/AGENTS.md"})
    for pattern in ("~", "~/.calivi", "/home", "/"):
        with pytest.raises(RuleError):
            validate("write_file", "dir", pattern)
    with pytest.raises(RuleError):
        validate("write_file", "dir", "relative/dir")
    assert suggest("write_file", {"path": "~/.calivi/AGENTS.md"}) is None


def test_suggestions_are_the_narrowest_rule():
    assert suggest("bash", bash("rm ~/models/tmp/cache")) == {"kind": "exact", "pattern": "rm ~/models/tmp/cache"}
    assert suggest("write_file", {"path": "/etc/nginx/conf.d/a.conf"}) == {"kind": "dir", "pattern": "/etc/nginx/conf.d"}
    assert suggest("read_file", {"path": "/etc/hosts"}) is None


# --- the loop -------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def tools_on(monkeypatch):
    monkeypatch.setattr(tools_config, "is_enabled", lambda: True)
    monkeypatch.setattr(tools_config, "tool_enabled", lambda name: True)


@pytest.fixture
def fake_bash():
    """`bash` with the real classifier and a handler that only records."""
    ran = []

    async def handler(args):
        ran.append(args["command"])
        return "exit code: 0"

    previous = registry._tools.get("bash")
    registry.register(Tool(
        name="bash", description="d", parameters={"type": "object", "properties": {}},
        handler=handler, source=host.SOURCE, privileged=True, needs_approval=host.bash_needs_approval,
    ))
    yield ran
    if previous:
        registry.register(previous)
    else:
        registry._tools.pop("bash", None)


@pytest.fixture
def owner_chat():
    db = SessionLocal()
    try:
        u = models.User(email="o@test.local", username="o", password_hash="x", role="admin")
        db.add(u)
        db.commit()
        c = models.Chat(user_id=u.id, title="t")
        db.add(c)
        db.commit()
        return u.id, c.id
    finally:
        db.close()


def _add_rule(kind, pattern, tool="bash", user_id=1):
    db = SessionLocal()
    try:
        return approval_rules.add(db, user_id, tool, kind, pattern).id
    finally:
        db.close()


async def _drive(monkeypatch, user_id, chat_id, cmd, decide=False, ask_every_tool=False):
    turns_ = [
        [{"type": "tool_calls", "calls": [{"id": "c1", "name": "bash", "arguments": bash(cmd)}]}],
        [{"type": "content", "text": "done"}],
    ]

    async def stream_chat(target, model, messages, tools=None):
        for piece in turns_.pop(0) if turns_ else []:
            yield piece

    monkeypatch.setattr(llm, "stream_chat", stream_chat)
    resp = build_stream_response(chat_id, TARGET, "m", [{"role": "user", "content": "hi"}],
                                 use_tools=True, user_id=user_id, ask_every_tool=ask_every_tool)
    events = []
    async for chunk in resp.body_iterator:
        for line in chunk.splitlines():
            if line.strip():
                event = json.loads(line)
                events.append(event)
                if event["type"] == "approval_request":
                    assert approvals.resolve(event["id"], chat_id, user_id, decide)
    return events


async def test_a_rule_answers_in_the_owners_place(monkeypatch, tmp_path, owner_chat, fake_bash):
    monkeypatch.setattr(config, "AUDIT_LOG_FILE", str(tmp_path / "audit.jsonl"))
    rule_id = _add_rule("exact", "rm ~/models/tmp/cache")
    events = await _drive(monkeypatch, *owner_chat, "rm ~/models/tmp/cache")
    assert not [e for e in events if e["type"] == "approval_request"]
    result = next(e for e in events if e["type"] == "approval_result")
    assert result["approved"] is True and result["rule"]["id"] == rule_id
    assert fake_bash == ["rm ~/models/tmp/cache"]
    call = json.loads((tmp_path / "audit.jsonl").read_text().splitlines()[0])
    assert call["approval"] == "rule" and call["rule"]["pattern"] == "rm ~/models/tmp/cache"
    db = SessionLocal()
    try:
        assert db.get(models.ApprovalRule, rule_id).uses == 1
    finally:
        db.close()


async def test_a_composed_command_still_asks(monkeypatch, owner_chat, fake_bash):
    _add_rule("prefix", "rm -f ~/models/tmp")
    events = await _drive(monkeypatch, *owner_chat, "rm -f ~/models/tmp/x; rm -rf ~", decide=False)
    request = next(e for e in events if e["type"] == "approval_request")
    assert "rule_suggestion" not in request  # nothing composed can be made a rule either
    assert fake_bash == []


async def test_strict_mode_overrides_the_rules(monkeypatch, owner_chat, fake_bash):
    _add_rule("exact", "rm ~/models/tmp/cache")
    events = await _drive(monkeypatch, *owner_chat, "rm ~/models/tmp/cache", ask_every_tool=True)
    request = next(e for e in events if e["type"] == "approval_request")
    assert "rule_suggestion" not in request
    assert fake_bash == []  # denied on the card, the rule notwithstanding


async def test_the_card_offers_a_rule(monkeypatch, owner_chat, fake_bash):
    events = await _drive(monkeypatch, *owner_chat, "rm ~/models/tmp/cache")
    request = next(e for e in events if e["type"] == "approval_request")
    assert request["rule_suggestion"] == {"kind": "exact", "pattern": "rm ~/models/tmp/cache"}


async def test_another_users_rule_does_not_count(monkeypatch, owner_chat, fake_bash):
    db = SessionLocal()
    try:
        db.add(models.User(email="b@test.local", username="b", password_hash="x", role="user"))
        db.commit()
    finally:
        db.close()
    _add_rule("exact", "rm ~/models/tmp/cache", user_id=2)
    events = await _drive(monkeypatch, *owner_chat, "rm ~/models/tmp/cache")
    assert any(e["type"] == "approval_request" for e in events)
    assert fake_bash == []


# --- the endpoints --------------------------------------------------------------------------


@pytest.fixture
def pending(fake_bash):
    """A card waiting for the owner (user 1) in chat 1."""
    db = SessionLocal()
    try:
        db.add(models.Chat(user_id=1, title="t"))
        db.commit()
    finally:
        db.close()
    return approvals.create(1, 1, "bash", bash("sudo systemctl stop ollama"))


async def test_always_allow_saves_the_rule_and_approves(admin, monkeypatch, tmp_path, pending):
    monkeypatch.setattr(config, "HOST_TOOLS_ENABLED", True)
    monkeypatch.setattr(config, "AUDIT_LOG_FILE", str(tmp_path / "audit.jsonl"))
    resp = await admin.post(f"/api/chats/1/approvals/{pending}", json={
        "approved": True, "rule": {"kind": "prefix", "pattern": "sudo systemctl stop"}})
    assert resp.status_code == 204, resp.text
    assert approvals.get(pending).approved is True
    rules = (await admin.get("/api/approval-rules")).json()
    assert [(r["kind"], r["pattern"]) for r in rules] == [("prefix", "sudo systemctl stop")]
    added = json.loads((tmp_path / "audit.jsonl").read_text())
    assert added["event"] == "rule_added" and added["rule"]["pattern"] == "sudo systemctl stop"

    assert (await admin.delete(f"/api/approval-rules/{rules[0]['id']}")).status_code == 204
    assert (await admin.get("/api/approval-rules")).json() == []
    assert json.loads((tmp_path / "audit.jsonl").read_text().splitlines()[-1])["event"] == "rule_deleted"


@pytest.mark.parametrize("decision", [
    {"approved": True, "rule": {"kind": "exact", "pattern": "sudo systemctl stop nginx"}},  # not this call
    {"approved": True, "rule": {"kind": "prefix", "pattern": "sudo"}},  # too broad
    {"approved": True, "rule": {"kind": "dir", "pattern": "/etc"}},  # wrong kind for bash
    {"approved": False, "rule": {"kind": "exact", "pattern": "sudo systemctl stop ollama"}},
])
async def test_a_rule_that_does_not_fit_is_refused_and_nothing_is_approved(admin, monkeypatch, pending, decision):
    monkeypatch.setattr(config, "HOST_TOOLS_ENABLED", True)
    resp = await admin.post(f"/api/chats/1/approvals/{pending}", json=decision)
    assert resp.status_code == 400
    assert not approvals.get(pending).event.is_set()  # the card is still waiting
    assert (await admin.get("/api/approval-rules")).json() == []


async def test_rules_are_the_owners_alone(admin, user_client, monkeypatch, fake_bash):
    await register(user_client, "bob")
    rule_id = _add_rule("exact", "rm ~/x")
    monkeypatch.setattr(config, "HOST_TOOLS_ENABLED", True)
    assert (await user_client.get("/api/approval-rules")).status_code == 404
    assert (await user_client.delete(f"/api/approval-rules/{rule_id}")).status_code == 404
    monkeypatch.setattr(config, "HOST_TOOLS_ENABLED", False)
    assert (await admin.get("/api/approval-rules")).status_code == 404
    monkeypatch.setattr(config, "HOST_TOOLS_ENABLED", True)
    assert len((await admin.get("/api/approval-rules")).json()) == 1
