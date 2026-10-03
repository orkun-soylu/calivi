"""Plan mode (plan_mode.py, tools/readonly.py, #114).

The read-only list in both directions, the registry's refusal, the planning turn ending on
`propose_plan`, the run turn (calls in the plan pass, anything else is flagged), and the
decision endpoints.

SAFETY: host tools are registered as copies whose handler only records. Every risky string
here reaches a classifier or a fake, never a shell.
"""
import dataclasses
import getpass
import json

import pytest

from app import approvals, audit, config, llm, models, tools_config
from app import plan_mode as planning
from app.database import SessionLocal
from app.routers import chats as chats_router
from app.routers.chats import build_stream_response
from app.tools import host
from app.tools.readonly import read_only
from app.tools.registry import ERROR_PREFIX, Tool, registry

TARGET = {"name": "s", "type": "ollama", "host": "h", "port": 1, "base_url": None, "api_key": None}
HOME = "/home/owner"

# --- the read-only list ---------------------------------------------------------------------

READ_ONLY = [
    "ls -la /etc", "cat /etc/os-release", "sudo cat /etc/shadow", "sudo -n ls /root", "df -h",
    "free -m", "systemctl", "systemctl status ollama", "systemctl --no-pager list-units --failed",
    "systemctl is-active nginx", "journalctl -u ollama -n 50 --no-pager", "ip addr", "ip -br a",
    "ip route show", "ip route get 1.1.1.1", "docker ps -a", "docker compose ps", "docker logs calivi",
    "docker image ls", "apt list --installed", "apt-cache policy nginx", "dpkg -l", "dpkg -L nginx",
    "git status", "git log --oneline -5", "git branch -a", "git remote -v", "ollama list",
    "ollama ps", "nvidia-smi", "nvidia-smi --query-gpu=name,memory.used --format=csv",
    "date", "date +%F", "find /var/log -name '*.gz'", "sysctl net.ipv4.ip_forward",
    "iptables -L -n", "sudo iptables -S", "ufw status verbose", "nft list ruleset", "crontab -l",
    "hostnamectl", "timedatectl status", "resolvectl status", "ss -tlnp", "lsblk", "du -sh ~/models",
    "grep -r listen /etc/nginx", "smartctl -a /dev/sda", "hostname", "env", "mount",
]

CHANGES = [
    "rm x", "sudo rm -rf ~/old", "mv a b", "touch f", "mkdir d", "systemctl restart ollama",
    "systemctl stop nginx", "sudo systemctl daemon-reload", "journalctl --vacuum-size=1G",
    "journalctl --rotate", "ip addr add 10.0.0.2/24 dev eth0", "ip link set eth0 down",
    "ip route del default", "docker rm calivi", "docker compose up -d", "docker compose down",
    "docker run --rm hello-world", "docker image prune", "apt install nginx", "apt-get update",
    "sudo apt upgrade", "dpkg -i x.deb", "dpkg -r nginx", "dpkg --configure -a", "git push",
    "git checkout .", "git branch -D x", "git remote add o u", "git pull", "ollama pull qwen",
    "ollama rm qwen", "ollama run qwen", "date -s 2020-01-01", "date 010100002020",
    "hostname newname", "find / -delete", "find . -exec rm x", "sysctl -w a.b=1", "sysctl a.b=1",
    "sudo sysctl -p", "iptables -F", "iptables -A INPUT -j DROP", "iptables -L -F", "ufw disable",
    "ufw allow 22", "nft flush ruleset", "crontab -r", "crontab f", "env X=1 rm f",
    "mount /dev/sdb1 /mnt", "nvidia-smi -pm 1", "smartctl -t long /dev/sda", "smartctl",
    "hostnamectl set-hostname x", "timedatectl set-time 10:00", "resolvectl dns eth0 1.1.1.1",
    "sed -i s/a/b/ f", "tee f", "curl -X POST https://example.com", "wget https://x", "sh -c ls",
    "python3 -c 'print(1)'", "chmod 600 f", "kill 1", "reboot", "useradd x",
    # shell syntax: never a simple command, whatever the program
    "cat x > y", "ls; rm x", "ls && rm x", "ls | sh", "echo $(rm x)", "echo `rm x`", "cat < /dev/zero",
    "ls\nrm x", "echo {a,b}", "ls \\; rm",
    # paths and sudo forms
    "/bin/ls", "./ls", "sudo -u root rm x", "sudo", "sudo -n", "",
]


@pytest.mark.parametrize("cmd", READ_ONLY)
def test_read_only_commands_run_in_plan_mode(cmd):
    assert read_only(cmd), cmd


@pytest.mark.parametrize("cmd", CHANGES)
def test_anything_else_is_refused(cmd):
    assert not read_only(cmd), cmd


def test_not_a_string_is_refused():
    assert not read_only(None) and not read_only(["ls"])


# --- registry --------------------------------------------------------------------------------


@pytest.fixture
def fake_host(monkeypatch):
    """The real host tools' metadata (classifiers, plan_safe) with recording handlers."""
    monkeypatch.setattr(host, "_account", lambda: (getpass.getuser(), HOME))
    ran = []
    previous = {t.name: registry._tools.get(t.name) for t in host.TOOLS}

    def recorder(name):
        async def handler(args):
            ran.append((name, args))
            return "exit code: 0" if name == "bash" else "ok"
        return handler

    for t in host.TOOLS:
        registry.register(dataclasses.replace(t, handler=recorder(t.name)))
    yield ran
    for name, tool in previous.items():
        if tool is None:
            registry._tools.pop(name, None)
        else:
            registry.register(tool)


async def test_the_registry_refuses_change_in_plan_mode(fake_host):
    out = await registry.execute("bash", {"command": "systemctl restart ollama"}, approved=True,
                                 privileged=True, plan=True)
    assert out.startswith(ERROR_PREFIX) and "plan mode" in out
    out = await registry.execute("write_file", {"path": "/etc/x", "content": "y"}, approved=True,
                                 privileged=True, plan=True)
    assert out.startswith(ERROR_PREFIX)
    assert fake_host == []
    await registry.execute("bash", {"command": "df -h"}, privileged=True, plan=True)
    await registry.execute("read_file", {"path": "/etc/hosts"}, privileged=True, plan=True)
    assert [n for n, _ in fake_host] == ["bash", "read_file"]


def test_plan_specs_leave_out_what_cannot_run(fake_host):
    async def h(args):
        return "x"

    registry.register(Tool(name="plain_t", description="d", parameters={}, handler=h))
    registry.register(Tool(name="mutating_t", description="d", parameters={}, handler=h, mutating=True))
    try:
        names = {s["function"]["name"] for s in registry.specs(privileged=True, plan=True)}
        assert {"bash", "read_file", "view_image", "plain_t"} <= names
        assert not names & {"write_file", "edit_file", "mutating_t"}
    finally:
        registry._tools.pop("plain_t", None)
        registry._tools.pop("mutating_t", None)


# --- plan validation -------------------------------------------------------------------------

PLAN = {
    "summary": "Restart Ollama with a larger context.",
    "steps": [
        {"title": "Write the override", "files": ["/etc/systemd/system/ollama.service.d/ctx.conf"]},
        {"title": "Restart", "commands": ["sudo systemctl daemon-reload", "sudo  systemctl restart ollama"]},
    ],
    "risks": "Ollama is down for a few seconds.",
    "rollback": "Delete the override and restart.",
}


def test_a_plan_is_validated_and_stored_as_proposed():
    plan = planning.validate(PLAN)
    assert plan["status"] == "proposed" and len(plan["steps"]) == 2
    assert plan["steps"][0]["commands"] == [] and plan["steps"][1]["files"] == []


@pytest.mark.parametrize("bad", [
    {**PLAN, "steps": []},
    {**PLAN, "steps": "do it"},
    {**PLAN, "summary": ""},
    {**PLAN, "steps": [{"title": "x", "commands": "rm -rf ~"}]},
    {**PLAN, "steps": [{"commands": ["ls"]}]},
    {**PLAN, "steps": [{"title": "x"}] * (planning.MAX_STEPS + 1)},
])
def test_a_malformed_plan_is_refused(bad):
    with pytest.raises(planning.PlanError):
        planning.validate(bad)


def test_the_matcher(monkeypatch):
    monkeypatch.setattr(host, "_account", lambda: (getpass.getuser(), HOME))
    m = planning.Matcher(planning.validate({**PLAN, "steps": [*PLAN["steps"], {
        "title": "Notes", "commands": ["rm ~/.calivi/AGENTS.md", "rm -rf --no-preserve-root /"],
        "files": ["~/.calivi/AGENTS.md"]}]}))
    assert m.in_plan("bash", {"command": "sudo systemctl restart  ollama"})  # spacing is not a deviation
    assert m.in_plan("write_file", {"path": "/etc/systemd/system/ollama.service.d/ctx.conf"})
    assert not m.in_plan("bash", {"command": "sudo systemctl restart nginx"})
    assert not m.in_plan("edit_file", {"path": "/etc/systemd/system/other.conf"})
    # Never covered, even when written into the plan: the notes and the deny list.
    assert not m.in_plan("bash", {"command": "rm ~/.calivi/AGENTS.md"})
    assert not m.in_plan("write_file", {"path": "~/.calivi/AGENTS.md"})
    assert not m.in_plan("bash", {"command": "rm -rf --no-preserve-root /"})
    # Inspection is never a deviation; change outside the plan is.
    assert not m.off_plan("bash", {"command": "systemctl status ollama"})
    assert not m.off_plan("read_file", {"path": "/etc/passwd"})
    assert m.off_plan("bash", {"command": "sudo systemctl restart nginx"})


# --- the loop --------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def tools_on(monkeypatch):
    monkeypatch.setattr(tools_config, "is_enabled", lambda: True)
    monkeypatch.setattr(tools_config, "tool_enabled", lambda name: True)


@pytest.fixture
def owner_chat():
    db = SessionLocal()
    try:
        u = models.User(email="o@test.local", username="o", password_hash="x", role="admin")
        db.add(u)
        db.commit()
        c = models.Chat(user_id=u.id, title="t", mode="agent")
        db.add(c)
        db.commit()
        return u.id, c.id
    finally:
        db.close()


async def _drive(monkeypatch, user_id, chat_id, turns_, decide=False, **kw):
    seen_tools = []

    async def stream_chat(target, model, messages, tools=None):
        seen_tools.append({"tools": [t["function"]["name"] for t in tools or []], "messages": messages})
        for piece in turns_.pop(0) if turns_ else [{"type": "content", "text": "done"}]:
            yield piece

    monkeypatch.setattr(llm, "stream_chat", stream_chat)
    resp = build_stream_response(chat_id, TARGET, "m", [{"role": "user", "content": "hi"}],
                                 use_tools=True, user_id=user_id, agent=True, **kw)
    events = []
    async for chunk in resp.body_iterator:
        for line in chunk.splitlines():
            if line.strip():
                event = json.loads(line)
                events.append(event)
                if event["type"] == "approval_request":
                    assert approvals.resolve(event["id"], chat_id, user_id, decide)
    return events, seen_tools


def _calls(*calls):
    return [{"type": "tool_calls", "calls": [
        {"id": f"c{i}", "name": n, "arguments": a} for i, (n, a) in enumerate(calls)]}]


def _last_reply(chat_id):
    db = SessionLocal()
    try:
        return (db.query(models.Message).filter_by(chat_id=chat_id, role="assistant")
                .order_by(models.Message.id.desc()).first())
    finally:
        db.close()


async def test_planning_turn_inspects_then_ends_on_the_plan(monkeypatch, owner_chat, fake_host):
    events, seen = await _drive(monkeypatch, *owner_chat, [
        _calls(("bash", {"command": "systemctl status ollama"}),
               ("bash", {"command": "sudo systemctl stop ollama"})),  # would ask, outside plan mode
        _calls((planning.TOOL_NAME, PLAN), ("bash", {"command": "df -h"})),
        [{"type": "content", "text": "should never be asked for"}],
    ], plan_mode=True)
    tools = seen[0]["tools"]
    assert planning.TOOL_NAME in tools and "bash" in tools
    assert "write_file" not in tools and "edit_file" not in tools
    assert planning.PLANNING_NOTE in seen[0]["messages"][0]["content"]
    # Inspection ran; the stop was refused without a card; nothing after the plan ran.
    assert fake_host == [("bash", {"command": "systemctl status ollama"})]
    assert not [e for e in events if e["type"] == "approval_request"]
    assert len(seen) == 2  # the plan ended the turn: no third model call
    plan_event = next(e for e in events if e["type"] == "plan")
    assert plan_event["plan"]["status"] == "proposed"
    reply = _last_reply(owner_chat[1])
    assert reply.plan["summary"] == PLAN["summary"] and reply.plan["status"] == "proposed"
    # Every call got an answer, the one after the plan included, so the replay stays well-formed.
    assert len([s for s in reply.steps if s["role"] == "tool"]) == 4


async def test_a_malformed_plan_goes_back_to_the_model(monkeypatch, owner_chat, fake_host):
    events, seen = await _drive(monkeypatch, *owner_chat, [
        _calls((planning.TOOL_NAME, {"summary": "x", "steps": []})),
        [{"type": "content", "text": "I will fix it."}],
    ], plan_mode=True)
    assert not [e for e in events if e["type"] == "plan"]
    assert any("was not accepted" in m.get("content", "") for m in seen[1]["messages"] if m["role"] == "tool")
    assert _last_reply(owner_chat[1]).plan is None


async def test_plan_mode_is_only_the_owners(monkeypatch, owner_chat, fake_host):
    """Not privileged → no host tools, so no plan mode either: the toggle cannot strip tools."""
    db = SessionLocal()
    try:
        db.add(models.User(email="b@test.local", username="b", password_hash="x", role="user"))
        db.commit()
    finally:
        db.close()
    _, seen = await _drive(monkeypatch, 2, owner_chat[1], [[{"type": "content", "text": "hi"}]], plan_mode=True)
    assert planning.TOOL_NAME not in seen[0]["tools"]


async def test_run_turn_passes_the_plan_and_flags_the_rest(monkeypatch, tmp_path, owner_chat, fake_host):
    monkeypatch.setattr(config, "AUDIT_LOG_FILE", str(tmp_path / "audit.jsonl"))
    plan = {**planning.validate(PLAN), "status": "approved"}
    events, seen = await _drive(monkeypatch, *owner_chat, [
        _calls(("write_file", {"path": "/etc/systemd/system/ollama.service.d/ctx.conf", "content": "x"}),
               ("bash", {"command": "sudo systemctl restart ollama"}),
               ("bash", {"command": "systemctl status ollama"}),
               ("bash", {"command": "sudo systemctl stop nginx"})),
    ], decide=False, run_plan=plan)
    assert planning.RUN_NOTE.split("\n")[0] in seen[0]["messages"][0]["content"]
    # The two planned calls ran with no card; the inspection ran; the off-plan stop asked (denied).
    requests = [e for e in events if e["type"] == "approval_request"]
    assert [r["args"]["command"] for r in requests] == ["sudo systemctl stop nginx"]
    assert [a.get("command") or a.get("path") for _, a in fake_host] == [
        "/etc/systemd/system/ollama.service.d/ctx.conf", "sudo systemctl restart ollama", "systemctl status ollama"]
    flagged = [e["args"].get("command") for e in events if e["type"] == "tool_call" and e.get("off_plan")]
    assert flagged == ["sudo systemctl stop nginx"]
    steps = [s for s in _last_reply(owner_chat[1]).steps if s["role"] == "tool"]
    # A restart asks no one to begin with, plan or not; the plan only answers where a card would be.
    assert [s.get("approval") for s in steps] == ["plan", None, None, "denied"]
    assert [bool(s.get("off_plan")) for s in steps] == [False, False, False, True]
    lines = [json.loads(x) for x in (tmp_path / "audit.jsonl").read_text().splitlines()]
    calls = [x for x in lines if x["event"] == "call"]
    assert [c["approval"] for c in calls] == ["plan", "auto", "auto", "denied"]
    assert [bool(c.get("off_plan")) for c in calls] == [False, False, False, True]


async def test_strict_mode_still_asks_during_a_run(monkeypatch, owner_chat, fake_host):
    plan = {**planning.validate(PLAN), "status": "approved"}
    events, _ = await _drive(monkeypatch, *owner_chat, [
        _calls(("bash", {"command": "sudo systemctl restart ollama"}))], decide=False,
        run_plan=plan, ask_every_tool=True)
    assert [e["type"] for e in events].count("approval_request") == 1
    assert fake_host == []


# --- endpoints -------------------------------------------------------------------------------


@pytest.fixture
def captured(monkeypatch):
    seen = []

    def fake_build(*args, **kwargs):
        seen.append(kwargs)
        from fastapi.responses import StreamingResponse

        async def empty():
            yield ""

        return StreamingResponse(empty())

    monkeypatch.setattr(chats_router, "build_stream_response", fake_build)
    return seen


@pytest.fixture
async def proposed(admin, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "HOST_TOOLS_ENABLED", True)
    monkeypatch.setattr(config, "AUDIT_LOG_FILE", str(tmp_path / "audit.jsonl"))
    await admin.post("/api/servers", json={"name": "s", "host": "127.0.0.1", "port": 1})
    chat_id = (await admin.post("/api/chats", json={})).json()["id"]
    db = SessionLocal()
    try:
        db.add(models.Message(chat_id=chat_id, role="user", content="restart ollama"))
        m = models.Message(chat_id=chat_id, role="assistant", content="", plan=planning.validate(PLAN))
        db.add(m)
        db.commit()
        return admin, chat_id, m.id, tmp_path / "audit.jsonl"
    finally:
        db.close()


def _plan_status(message_id):
    db = SessionLocal()
    try:
        return db.get(models.Message, message_id).plan["status"]
    finally:
        db.close()


async def test_run_it_approves_and_hands_the_plan_to_the_turn(proposed, captured):
    client, chat_id, mid, log = proposed
    resp = await client.post(f"/api/chats/{chat_id}/messages", json={
        "content": "Run it.", "server_id": 1, "model": "m", "use_tools": True,
        "plan_mode": True, "run_plan": mid})
    assert resp.status_code == 200, resp.text
    assert _plan_status(mid) == "approved"
    kw = captured[0]
    assert kw["run_plan"]["status"] == "approved" and kw["plan_mode"] is False  # the run leaves plan mode
    event = json.loads(log.read_text())
    assert event["event"] == "plan_approved" and event["plan"]["summary"] == PLAN["summary"]
    # Decided once: a second Run is refused.
    again = await client.post(f"/api/chats/{chat_id}/messages", json={
        "content": "Run it.", "server_id": 1, "model": "m", "run_plan": mid})
    assert again.status_code in (404, 409)


async def test_cancel(proposed, captured):
    client, chat_id, mid, log = proposed
    assert (await client.post(f"/api/chats/{chat_id}/messages/{mid}/plan/cancel")).status_code == 204
    assert _plan_status(mid) == "cancelled"
    assert json.loads(log.read_text())["event"] == "plan_cancelled"
    resp = await client.post(f"/api/chats/{chat_id}/messages", json={
        "content": "Run it.", "server_id": 1, "model": "m", "run_plan": mid})
    assert resp.status_code == 409
    assert captured == []


async def test_a_plan_the_chat_moved_past_cannot_be_run(proposed, captured):
    client, chat_id, mid, _ = proposed
    db = SessionLocal()
    try:
        db.add(models.Message(chat_id=chat_id, role="user", content="change step 2"))
        db.commit()
    finally:
        db.close()
    resp = await client.post(f"/api/chats/{chat_id}/messages", json={
        "content": "Run it.", "server_id": 1, "model": "m", "run_plan": mid})
    assert resp.status_code == 409
    assert _plan_status(mid) == "proposed" and captured == []


async def test_only_the_owner_on_calivi_vm_decides(proposed, captured, user_client, monkeypatch):
    client, chat_id, mid, _ = proposed
    monkeypatch.setattr(config, "HOST_TOOLS_ENABLED", False)
    assert (await client.post(f"/api/chats/{chat_id}/messages/{mid}/plan/cancel")).status_code == 404
    monkeypatch.setattr(config, "HOST_TOOLS_ENABLED", True)
    from tests.conftest import register
    await register(user_client, "bob")
    assert (await user_client.post(f"/api/chats/{chat_id}/messages/{mid}/plan/cancel")).status_code == 404
    assert _plan_status(mid) == "proposed"


async def test_chat_mode_history_carries_the_plan(proposed):
    _, chat_id, _, _ = proposed
    db = SessionLocal()
    try:
        history, _ = chats_router._context_of(db, chat_id)
    finally:
        db.close()
    assert "[Plan, proposed] Restart Ollama" in history[-1]["content"]
    assert "$ sudo daemon-reload" not in history[-1]["content"]
    assert "$ sudo systemctl daemon-reload" in history[-1]["content"]
