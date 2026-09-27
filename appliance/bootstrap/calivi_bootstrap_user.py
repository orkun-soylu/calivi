#!/usr/bin/python3
"""calivi-bootstrap-user — turns Calivi's first registration into the machine's owner account.

Installed as `/usr/sbin/calivi-bootstrap-user` on the calivi-vm appliance. The backend
runs as an unprivileged service account; this script is the **only** thing it may run as root
(one sudoers line). It reads one JSON object on stdin — never argv, where a password would show
up in `ps` — and:

  1. creates the Linux account (same name and password as the Calivi super admin), in `sudo`,
     with passwordless sudo;
  2. lets the service account run commands as that account (`sudo -u <owner>`), which is how
     the host tools reach the machine;
  3. optionally sets the hostname and timezone and installs an SSH public key;
  4. writes the owner's name to /etc/calivi/host-user — last, so a half-finished run never
     looks finished.

**One shot.** A lock file is created with O_EXCL before anything changes; a second run — a
second concurrent registration, or a replay — is refused. If a run fails half-way, recovery is
by hand on the console (the lock stays, deliberately): see *First registration on the
appliance* in ARCHITECTURE.md.

**Nothing from the caller is trusted.** The backend validates the same fields, but this script
runs as root and re-validates all of them. Planning is a pure function (`build_plan`) so the
validation can be tested without executing anything; `execute` is only ever run on the VM.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile

SERVICE_USER = os.environ.get("CALIVI_SERVICE_USER", "calivi")
STATE_DIR = "/etc/calivi"
LOCK = f"{STATE_DIR}/bootstrap.lock"
HOST_USER_FILE = f"{STATE_DIR}/host-user"
ZONEINFO = "/usr/share/zoneinfo"
CLOUD_HOSTNAME_CFG = "/etc/cloud/cloud.cfg.d/99-calivi-hostname.cfg"

USERNAME = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
# Names that exist on a stock Debian or mean something to sudo/ssh; getent catches the rest.
RESERVED = {"root", "admin", "sudo", "calivi", "nobody", "daemon", "ubuntu", "debian", "all"}
HOSTNAME = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
TIMEZONE = re.compile(r"^[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+){0,2}$")
SSH_KEY = re.compile(
    r"^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)|sk-ssh-ed25519@openssh\.com|"
    r"sk-ecdsa-sha2-nistp256@openssh\.com) [A-Za-z0-9+/]+={0,3}( [^\r\n]{0,200})?$"
)


class Invalid(ValueError):
    """A field the caller must fix. The message is safe to show to the person registering."""


def _probe_user_exists(name: str) -> bool:
    return subprocess.run(["getent", "passwd", name], capture_output=True).returncode == 0


def _probe_zone_exists(zone: str) -> bool:
    path = os.path.realpath(os.path.join(ZONEINFO, zone))
    return path.startswith(ZONEINFO + "/") and os.path.isfile(path)


def notes_template(username: str, hostname: str | None, today: datetime.date) -> str:
    """The first ~/.calivi/AGENTS.md (#110): a skeleton the model fills in as it learns."""
    return (
        f"# {hostname or 'This machine'}\n"
        "\n"
        "Notes that Calivi's model reads at the start of every chat on this machine and keeps up\n"
        "to date (it asks you before each change). Edit them freely; keep them short.\n"
        "\n"
        "## Machine\n"
        f"- Owner: {username} (passwordless sudo)\n"
        f"- Claimed: {today.isoformat()}, from the calivi-vm setup\n"
        "\n"
        "## Services\n"
        "\n"
        "## Owner's rules\n"
        "\n"
        "## Learned\n"
    )


def build_plan(req: dict, user_exists=_probe_user_exists, zone_exists=_probe_zone_exists,
               today: datetime.date | None = None) -> list:
    """Validates the request and returns the steps to apply, without applying any.

    A step is ("run", argv, stdin | None) or ("write", path, content, mode, owner | None).
    """
    if not isinstance(req, dict):
        raise Invalid("expected a JSON object")
    username = req.get("username")
    password = req.get("password")
    hostname = req.get("hostname") or None
    timezone = req.get("timezone") or None
    ssh_key = req.get("ssh_key") or None

    if not isinstance(username, str) or not USERNAME.match(username):
        raise Invalid(
            "The username becomes a Linux account: use lowercase letters, digits, '-' or '_', "
            "starting with a letter, at most 32 characters."
        )
    if username in RESERVED or user_exists(username):
        raise Invalid(f"'{username}' is already an account on this machine; pick another name.")
    if not isinstance(password, str) or not password:
        raise Invalid("A password is required.")
    if any(c in password for c in "\n\r\0"):
        raise Invalid("The password cannot contain line breaks.")
    if hostname is not None and (not isinstance(hostname, str) or not HOSTNAME.match(hostname)):
        raise Invalid("Hostname: lowercase letters, digits and '-', at most 63 characters.")
    if timezone is not None and (
        not isinstance(timezone, str) or not TIMEZONE.match(timezone) or not zone_exists(timezone)
    ):
        raise Invalid("Unknown timezone (expected a name like Europe/Istanbul).")
    if ssh_key is not None:
        if not isinstance(ssh_key, str) or not SSH_KEY.match(ssh_key.strip()):
            raise Invalid("The SSH key must be one public key line (ssh-ed25519 AAAA… comment).")
        ssh_key = ssh_key.strip()

    home = f"/home/{username}"
    plan = [
        ("run", ["useradd", "--create-home", "--shell", "/bin/bash", "--groups", "sudo",
                 "--", username], None),
        # chpasswd splits on the first ':', so a ':' inside the password is fine.
        ("run", ["chpasswd"], f"{username}:{password}\n"),
        ("write", "/etc/sudoers.d/90-calivi-owner",
         f"# The machine's owner (created by Calivi's first registration).\n"
         f"{username} ALL=(ALL:ALL) NOPASSWD: ALL\n", 0o440, None),
        ("write", "/etc/sudoers.d/80-calivi-host",
         f"# Calivi's host tools run as the owner - and as nobody else.\n"
         f"{SERVICE_USER} ALL=({username}) NOPASSWD: ALL\n", 0o440, None),
    ]
    if ssh_key:
        plan += [
            ("run", ["install", "-d", "-m", "700", "-o", username, "-g", username,
                     f"{home}/.ssh"], None),
            ("write", f"{home}/.ssh/authorized_keys", ssh_key + "\n", 0o600, username),
        ]
    if hostname:
        plan += [
            ("run", ["hostnamectl", "set-hostname", hostname], None),
            # Debian resolves its own name through 127.0.1.1; without this sudo warns on
            # every call that it cannot resolve the host.
            ("run", ["sed", "-i", "-E", rf"s/^127\.0\.1\.1\s.*/127.0.1.1\t{hostname}/",
                     "/etc/hosts"], None),
            # cloud-init's update_hostname runs on every boot and would put the Proxmox VM
            # name back; the owner's choice has to win.
            ("write", CLOUD_HOSTNAME_CFG, "preserve_hostname: true\n", 0o644, None),
        ]
    if timezone:
        plan.append(("run", ["timedatectl", "set-timezone", timezone], None))
    # The machine notes (#110), owner-only like the rest of the home.
    plan += [
        ("run", ["install", "-d", "-m", "700", "-o", username, "-g", username,
                 f"{home}/.calivi"], None),
        ("write", f"{home}/.calivi/AGENTS.md",
         notes_template(username, hostname, today or datetime.date.today()), 0o600, username),
    ]
    # Last: this file is what marks the machine as claimed.
    plan.append(("write", HOST_USER_FILE, username + "\n", 0o644, None))
    return plan


def _write(path: str, content: str, mode: int, owner: str | None) -> None:
    """Atomic write; sudoers files are checked by visudo before they go live, because a
    broken one locks sudo out for everyone."""
    directory = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".calivi-")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.chmod(tmp, mode)
        if owner:
            subprocess.run(["chown", f"{owner}:{owner}", tmp], check=True)
        if path.startswith("/etc/sudoers.d/"):
            subprocess.run(["visudo", "-cf", tmp], check=True, capture_output=True)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def execute(plan: list) -> None:
    for step in plan:
        if step[0] == "run":
            _, argv, stdin = step
            subprocess.run(argv, input=stdin, text=True, check=True, capture_output=True)
        else:
            _, path, content, mode, owner = step
            _write(path, content, mode, owner)


def main() -> int:
    if os.geteuid() != 0:
        print("must run as root", file=sys.stderr)
        return 2
    try:
        plan = build_plan(json.load(sys.stdin))
    except (Invalid, json.JSONDecodeError) as e:
        print(str(e), file=sys.stderr)
        return 1
    os.makedirs(STATE_DIR, mode=0o755, exist_ok=True)
    try:
        os.close(os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    except FileExistsError:
        print("This machine already has an owner.", file=sys.stderr)
        return 3
    try:
        execute(plan)
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or "").strip() if isinstance(e.stderr, str) else ""
        print(f"setup failed at `{e.cmd[0]}`: {detail}", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
