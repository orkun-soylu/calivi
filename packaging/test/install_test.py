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
  apt source  the package's calivi.sources and keyring: the right suite, the pinned key, and
              apt update against the real https://apt.calivi.ai verifies with it
  apt repo    (with --apt-url) a signed repository built by packaging/apt/publish.sh: added
              the way apt.calivi.ai documents it, `apt install calivi` brings this build

With --image the VM is a calivi-vm image instead: its first boot is checked (the package it was
built with, services, kernel, unclaimed, per-machine secrets), then claim, the APT source, the
host tool and the deferred restart.

Every step prints what it checked; the first failure stops the run with the evidence.
"""
import argparse
import hashlib
import http.cookiejar
import json
import os
import re
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


def image_boot():
    step("the calivi-vm image, first boot")
    subprocess.run(["scp", "-q", "-F", args.ssh_config, args.deb, "vm:/tmp/new.deb"], check=True)
    wait("calivi answers on :80", up, timeout=180)
    want = deb_version(args.deb)
    # With PACKAGE_UPGRADE, cloud-init upgraded packages first, as Proxmox's does: the image's
    # Calivi must still be the one it was built with (the trap build.sh guards against).
    check(ssh("dpkg-query -W -f='${Version}' calivi").stdout == want, f"calivi {want} is the package the image carries")
    for unit in ("calivi.service", "nginx.service", "calivi-firstboot.path"):
        check(ssh(f"systemctl is-active {unit}", ok=False).stdout.strip() == "active", f"{unit} is active")
    kernel = ssh("uname -r").stdout.strip()
    check(not kernel.endswith("-cloud-amd64"), f"the standard kernel runs ({kernel}), not the cloud one")
    check(ssh("command -v curl", ok=False).returncode == 0, "curl is there")
    fresh = ssh("sudo sh -c 'test -e /etc/calivi/host-user || test -e /etc/calivi/bootstrap.lock' && echo claimed || echo fresh").stdout.strip()
    check(fresh == "fresh", "no owner baked in: the image is unclaimed")
    ids = ssh("cat /etc/machine-id; sudo cat /etc/calivi/secret.env").stdout
    check(ids.strip() and "CALIVI_SECRET_KEY=" in ids, "machine-id and the session key were made on this boot")
    status, cfg = request("GET", "/api/auth/config")
    check(cfg.get("host_setup") is True, "the first account will claim the machine", cfg)


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
    # Set up by hand exactly as apt.calivi.ai documents it (calivi-vm 0.6.1 was): the source is
    # taken from the index page's own instructions, so the page and the package cannot drift
    # apart unnoticed. The package ships the same two files and must take them over without a
    # conffile question — dpkg would stop at one ("end of file on stdin at conffile prompt").
    here = os.path.dirname(os.path.abspath(__file__))
    subprocess.run(["scp", "-q", "-F", args.ssh_config, os.path.join(here, "..", "apt", "calivi.gpg"), "vm:/tmp/calivi.gpg"], check=True)
    suite = ssh(". /etc/os-release; echo $VERSION_CODENAME").stdout.strip()
    with open(os.path.join(here, "..", "apt", "index.html.in"), encoding="utf-8") as f:
        page = f.read()
    documented = page.split("calivi.sources &gt;/dev/null &lt;&lt;EOF\n", 1)[1].split("\nEOF\n", 1)[0] + "\n"
    documented = documented.replace("$VERSION_CODENAME", suite)
    subprocess.run(["ssh", "-F", args.ssh_config, "vm", "sudo tee /etc/apt/sources.list.d/calivi.sources >/dev/null"],
                   input=documented, text=True, check=True)
    ssh("sudo install -m 0644 /tmp/calivi.gpg /usr/share/keyrings/calivi.gpg")
    out = apt_install("/tmp/new.deb")
    leftovers = ssh("ls /etc/apt/sources.list.d/ | grep -E 'dpkg-(dist|new|old)' || true").stdout.strip()
    check(not leftovers, "a hand-added source is taken over without a conffile question", leftovers)
    want = deb_version(args.deb)
    check(ssh("dpkg-query -W -f='${Version}' calivi").stdout == want, f"calivi {want} is installed", out[-2000:])
    wait("the service restarted", lambda: main_pid() not in ("0", pid))
    wait("calivi answers on :80", up)
    check(ssh("sudo cat /etc/calivi/secret.env").stdout == key, "the session key survived")
    check(request("GET", "/api/auth/me")[0] == 200, "the owner's session is still valid")
    check(ssh("sudo cat /etc/calivi/host-user").stdout.strip() == OWNER, "the owner marker survived")


def _policy_source(policy, url, suite):
    """True if `apt-cache policy` lists the package from exactly this repository and suite — a
    whole line of its version table, not a substring somewhere in the output."""
    line = re.compile(rf"^\s+\d+ {re.escape(url)} {re.escape(suite)}/main amd64 Packages$", re.M)
    return bool(line.search(policy))


def shipped_source():
    step("the package's own APT source")
    suite = ssh(". /etc/os-release; echo $VERSION_CODENAME").stdout.strip()
    sources = ssh("cat /etc/apt/sources.list.d/calivi.sources").stdout
    want_lines = ["Types: deb", "URIs: https://apt.calivi.ai", f"Suites: {suite}", "Components: main",
                  "Signed-By: /usr/share/keyrings/calivi.gpg"]
    check(sources.splitlines() == want_lines, f"calivi.sources points at apt.calivi.ai, suite {suite}", sources)
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "..", "apt", "calivi.gpg"), "rb") as f:
        want = hashlib.sha256(f.read()).hexdigest()
    got = ssh("sha256sum /usr/share/keyrings/calivi.gpg").stdout.split()[0]
    check(got == want, "the keyring is the pinned key (packaging/apt/calivi.gpg)")
    # The real repository: its signature must verify with the key the package ships.
    p = ssh("sudo apt-get -o DPkg::Lock::Timeout=600 update 2>&1", ok=False)
    bad = [ln for ln in p.stdout.splitlines() if ln.startswith(("W:", "E:")) and "calivi" in ln]
    check(p.returncode == 0 and not bad, "apt update against https://apt.calivi.ai verifies", "\n".join(bad) or p.stdout[-1500:])
    policy = ssh("apt-cache policy calivi").stdout
    check(_policy_source(policy, "https://apt.calivi.ai", suite), "apt sees calivi in apt.calivi.ai", policy)


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
    check(ssh("test -e /etc/apt/sources.list.d/calivi.sources || test -e /usr/share/keyrings/calivi.gpg", ok=False).returncode != 0,
          "the APT source and its key are gone")
    check(ssh("sudo test -s /var/lib/calivi/calivi.db", ok=False).returncode == 0, "the chats are kept")
    check(ssh(f"id {OWNER}", ok=False).returncode == 0, "the owner's account is kept")


def apt_repo():
    step("apt repository")
    subprocess.run(["scp", "-q", "-F", args.ssh_config, args.apt_key, "vm:/tmp/calivi-test.gpg"], check=True)
    # As https://apt.calivi.ai says, with the test repository's URL and key — under their own
    # names, because the package installs calivi.sources and calivi.gpg itself.
    ssh("sudo install -m 0644 /tmp/calivi-test.gpg /usr/share/keyrings/calivi-test.gpg")
    suite = ssh(". /etc/os-release; echo $VERSION_CODENAME").stdout.strip()
    sources = (f"Types: deb\nURIs: {args.apt_url}\nSuites: {suite}\nComponents: main\n"
               "Signed-By: /usr/share/keyrings/calivi-test.gpg\n")
    ssh(f"printf '{sources}' | sudo tee /etc/apt/sources.list.d/calivi-test.sources >/dev/null")
    p = ssh("sudo apt-get -o DPkg::Lock::Timeout=600 update 2>&1", ok=False)
    check(p.returncode == 0 and "calivi" not in "".join(l for l in p.stdout.splitlines(True) if l.startswith(("W:", "E:"))),
          f"apt update accepts the signed '{suite}' suite", p.stdout[-2000:])
    policy = ssh("apt-cache policy calivi").stdout
    want = deb_version(args.deb)
    check(f"Candidate: {want}" in policy.splitlines()[2] and _policy_source(policy, args.apt_url, suite),
          f"the candidate is {want}, from the test repository", policy)
    ssh("sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=600 install -y -q calivi")
    check(ssh("test -f /etc/apt/sources.list.d/calivi.sources", ok=False).returncode == 0,
          "the reinstall put the package's own source back")
    check(ssh("dpkg-query -W -f='${Version}' calivi").stdout == want, "apt install calivi installed it")
    wait("calivi answers on :80", up)
    print("  ok  calivi answers on :80")


def main():
    global args
    p = argparse.ArgumentParser()
    p.add_argument("--ssh-config", required=True)
    p.add_argument("--deb", required=True)
    p.add_argument("--previous")
    p.add_argument("--apt-url", help="a test APT repository, as the guest reaches it")
    p.add_argument("--apt-key", help="its public key (binary, for Signed-By)")
    p.add_argument("--image", action="store_true",
                   help="the VM was booted from the calivi-vm image built with --deb: no install, "
                        "no upgrade, no purge")
    args = p.parse_args()
    try:
        if args.image:
            image_boot()
            claim()
            shipped_source()
            host_tool()
            deferred_restart()
            print("\nall image tests passed")
            return
        install()
        claim()
        if args.previous:
            upgrade()
        else:
            print("\n== upgrade: skipped, no earlier release for this distribution")
        shipped_source()
        host_tool()
        deferred_restart()
        purge()
        if args.apt_url:
            apt_repo()
    except Failed as e:
        print(f"\nFAILED: {e}", file=sys.stderr)
        for cmd in ("sudo journalctl -u calivi -u calivi-restart-when-idle --no-pager -n 80", "sudo tail -30 /var/log/nginx/error.log"):
            print(f"\n--- {cmd}", file=sys.stderr)
            print(ssh(cmd, ok=False).stdout, file=sys.stderr)
        sys.exit(1)
    print("\nall install tests passed")


if __name__ == "__main__":
    main()
