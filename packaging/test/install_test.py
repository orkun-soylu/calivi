#!/usr/bin/env python3
"""Install tests for the calivi .deb in a real VM (#95). Standard library only.

    install_test.py --ssh-config <dir>/ssh_config --deb calivi_X+tag_amd64.deb [--previous old.deb]

Expects the VM from vm.sh (SSH as `ci` with passwordless sudo, :80 forwarded to 127.0.0.1:8080)
and fake_model.py listening on the runner, which the guest reaches as 10.0.2.2. In order:

  install     the previous release when given, else this build; services up, :80 answers
  claim       a wrong setup code is refused and creates nothing; the right one creates the
              owner with sudo and closes registration
  upgrade     (with --previous) to this build: the owner, the session and the key survive
  host tool   the scripted model runs a bash command; it runs as the owner, on this machine
  deferred    reinstalling while a reply streams leaves the service alone until the reply is
              complete, then restarts it
  purge       the package goes; the owner's account and the chats stay

Every step prints what it checked; the first failure stops the run with the evidence.
"""
import argparse
import http.cookiejar
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8080"
MODEL_URL = "http://10.0.2.2:8099/v1"
OWNER = "owner"
PASSWORD = "ci-password-not-secret"

args = None
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


class Failed(Exception):
    pass


def check(cond, what, evidence=""):
    if not cond:
        raise Failed(f"{what}\n{evidence}".rstrip())
    print(f"  ok  {what}")


def step(name):
    print(f"\n== {name}", flush=True)


# --- the VM ------------------------------------------------------------------------------------


def ssh(cmd, user=None, ok=True):
    argv = ["ssh", "-F", args.ssh_config]
    if user:
        argv += ["-l", user]
    p = subprocess.run(argv + ["vm", cmd], capture_output=True, text=True, timeout=900)
    if ok and p.returncode != 0:
        raise Failed(f"on the VM: {cmd}\nexit {p.returncode}\n{p.stdout}{p.stderr}")
    return p


def apt_install(path, reinstall=False):
    flag = "--reinstall " if reinstall else ""
    p = ssh(f"sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=600 install -y -q {flag}{path}")
    return p.stdout + p.stderr


def main_pid():
    return ssh("systemctl show -p MainPID --value calivi.service").stdout.strip()


def wait(what, fn, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return
        time.sleep(1)
    raise Failed(f"timed out: {what}")


def deb_version(path):
    return subprocess.run(["dpkg-deb", "-f", path, "Version"], capture_output=True, text=True, check=True).stdout.strip()


# --- HTTP --------------------------------------------------------------------------------------


def request(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with opener.open(req, timeout=30) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
        return 0, str(e)


def up():
    return request("GET", "/api/auth/config")[0] == 200


def send(chat_id, content):
    """One message; returns the stream's events. The stream is read to its end."""
    body = {"content": content, "server_id": args.server_id, "model": "fake", "use_tools": True}
    req = urllib.request.Request(f"{BASE}/api/chats/{chat_id}/messages", data=json.dumps(body).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    with opener.open(req, timeout=300) as r:
        return [json.loads(line) for line in r if line.strip()]


def text_of(events):
    return "".join(e.get("text", "") for e in events if e["type"] == "content")


# --- the scenario ------------------------------------------------------------------------------


def install():
    step("install")
    ssh("sudo apt-get -o DPkg::Lock::Timeout=600 update -q")
    # Ubuntu has it by default and Debian users add it: it restarts services after apt, and
    # the deferred restart below must hold with it installed.
    ssh("sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=600 install -y -q needrestart")
    first = args.previous or args.deb
    subprocess.run(["scp", "-q", "-F", args.ssh_config, args.deb, "vm:/tmp/new.deb"], check=True)
    if args.previous:
        subprocess.run(["scp", "-q", "-F", args.ssh_config, args.previous, "vm:/tmp/previous.deb"], check=True)
    apt_install("/tmp/previous.deb" if args.previous else "/tmp/new.deb")
    print(f"  installed {os.path.basename(first)}")
    wait("calivi answers on :80", up)
    for unit in ("calivi.service", "nginx.service", "calivi-firstboot.path"):
        check(ssh(f"systemctl is-active {unit}", ok=False).stdout.strip() == "active", f"{unit} is active")
    status, cfg = request("GET", "/api/auth/config")
    check(cfg.get("host_setup") is True, "the first account will claim the machine", cfg)


def claim():
    step("claim")
    wait("the setup code exists", lambda: ssh("sudo test -s /etc/calivi/setup-code", ok=False).returncode == 0)
    code = ssh("sudo cat /etc/calivi/setup-code").stdout.strip()
    pub = open(os.path.join(os.path.dirname(args.ssh_config), "id_ed25519.pub")).read().strip()
    account = {"email": "owner@ci.invalid", "username": OWNER, "password": PASSWORD,
               "hostname": "calivi-ci-owned", "timezone": "Europe/Istanbul", "ssh_key": pub}

    status, body = request("POST", "/api/auth/register", account | {"setup_code": "AAAA-AAAA-AAAA-AAAA"})
    check(status == 403, "a wrong setup code is refused", f"{status} {body}")
    check(ssh(f"id {OWNER}", ok=False).returncode != 0, "... and creates no Linux account")

    status, body = request("POST", "/api/auth/register", account | {"setup_code": code.lower()})
    check(status == 200, "the right code claims the machine", f"{status} {body}")
    check(body.get("host_tools") is True, "the owner gets the host tools", body)
    groups = ssh(f"id -nG {OWNER}").stdout.split()
    check("sudo" in groups, f"{OWNER} exists and is in sudo", groups)
    check(ssh("sudo -n true", user=OWNER, ok=False).returncode == 0, f"{OWNER} logs in with the key and sudoes without a password")
    check(ssh("hostname").stdout.strip() == "calivi-ci-owned", "the hostname was set")
    check(ssh("sudo cat /etc/calivi/host-user").stdout.strip() == OWNER, "/etc/calivi/host-user names the owner")
    wait("the setup code is deleted", lambda: ssh("sudo test -e /etc/calivi/setup-code", ok=False).returncode != 0)
    print("  ok  the setup code is deleted")

    other = urllib.request.build_opener()  # no session: a stranger
    try:
        other.open(urllib.request.Request(BASE + "/api/auth/register", method="POST",
                                          data=json.dumps(account | {"username": "late", "email": "l@ci.invalid"}).encode(),
                                          headers={"Content-Type": "application/json"}), timeout=30)
        status = 200
    except urllib.error.HTTPError as e:
        status = e.code
    check(status == 403, "registration is closed after the claim", status)


def upgrade():
    step(f"upgrade {os.path.basename(args.previous)} → {os.path.basename(args.deb)}")
    key = ssh("sudo cat /etc/calivi/secret.env").stdout
    pid = main_pid()
    out = apt_install("/tmp/new.deb")
    want = deb_version(args.deb)
    check(ssh("dpkg-query -W -f='${Version}' calivi").stdout == want, f"calivi {want} is installed", out[-2000:])
    wait("the service restarted", lambda: main_pid() not in ("0", pid))
    wait("calivi answers on :80", up)
    check(ssh("sudo cat /etc/calivi/secret.env").stdout == key, "the session key survived")
    check(request("GET", "/api/auth/me")[0] == 200, "the owner's session is still valid")
    check(ssh("sudo cat /etc/calivi/host-user").stdout.strip() == OWNER, "the owner marker survived")


def host_tool():
    step("host tool")
    status, server = request("POST", "/api/servers", {"name": "fake", "type": "openai", "base_url": MODEL_URL})
    check(status == 200, "the fake model server is added", f"{status} {server}")
    args.server_id = server["id"]
    status, chat = request("POST", "/api/chats", {})
    check(chat.get("mode") == "agent", "a new chat on calivi-vm is an agent", chat)
    args.chat_id = chat["id"]

    events = send(args.chat_id, 'RUN: echo "proof:$(id -un):$(hostname)"; touch /tmp/calivi-ci-proof')
    types = [e["type"] for e in events]
    check("error" not in types, "the turn ran without an error", events)
    call = next((e for e in events if e["type"] == "tool_call"), None)
    check(call and call["name"] == "bash", "the model's bash call reached the tool", events)
    result = next((e for e in events if e["type"] == "tool_result"), {})
    check(result.get("ok") is True, "the command succeeded", result)
    check("approval_request" not in types, "a harmless command needs no approval")
    check(f"ran: proof:{OWNER}:calivi-ci-owned" in text_of(events), "it ran as the owner, on this machine", text_of(events))
    check(ssh("stat -c %U /tmp/calivi-ci-proof").stdout.strip() == OWNER, "the file it created belongs to the owner")


def deferred_restart():
    step("deferred restart")
    pid = main_pid()
    got = {}

    def reply():
        try:
            got["events"] = send(args.chat_id, "SLOW: 40")
        except Exception as e:  # noqa: BLE001 — reported by the checks below
            got["error"] = repr(e)

    t = threading.Thread(target=reply)
    t.start()
    wait("the busy marker appears", lambda: ssh("test -e /run/calivi/busy", ok=False).returncode == 0, timeout=30)
    out = apt_install("/tmp/new.deb", reinstall=True)
    check("a reply is running" in out, "the upgrade says it waits for the reply", out[-2000:])
    check(main_pid() == pid, "the service was not restarted under the reply", out[-2000:])
    check(ssh("systemctl is-active calivi-restart-when-idle.service", ok=False).stdout.strip() == "active",
          "the restart is handed to calivi-restart-when-idle")
    t.join(120)
    check("error" not in got and not t.is_alive(), "the reply's stream stayed open", got.get("error", ""))
    text = text_of(got.get("events", []))
    check(text.endswith("finished") and "w39" in text, "the reply arrived complete", text[-300:])
    wait("the service restarted after the reply", lambda: main_pid() not in ("0", pid))
    wait("calivi answers on :80", up)
    print("  ok  the service restarted after the reply")


def purge():
    step("purge")
    ssh("sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=600 purge -y -q calivi")
    check(ssh("systemctl cat calivi.service", ok=False).returncode != 0, "the unit is gone")
    check(ssh("test -e /opt/calivi || test -e /etc/calivi", ok=False).returncode != 0, "/opt/calivi and /etc/calivi are gone")
    check(ssh("sudo test -s /var/lib/calivi/calivi.db", ok=False).returncode == 0, "the chats are kept")
    check(ssh(f"id {OWNER}", ok=False).returncode == 0, "the owner's account is kept")


def main():
    global args
    p = argparse.ArgumentParser()
    p.add_argument("--ssh-config", required=True)
    p.add_argument("--deb", required=True)
    p.add_argument("--previous")
    args = p.parse_args()
    try:
        install()
        claim()
        if args.previous:
            upgrade()
        else:
            print("\n== upgrade: skipped, no earlier release for this distribution")
        host_tool()
        deferred_restart()
        purge()
    except Failed as e:
        print(f"\nFAILED: {e}", file=sys.stderr)
        for cmd in ("sudo journalctl -u calivi -u calivi-restart-when-idle --no-pager -n 80", "sudo tail -30 /var/log/nginx/error.log"):
            print(f"\n--- {cmd}", file=sys.stderr)
            print(ssh(cmd, ok=False).stdout, file=sys.stderr)
        sys.exit(1)
    print("\nall install tests passed")


if __name__ == "__main__":
    main()
