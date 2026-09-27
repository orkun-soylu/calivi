"""First registration on the calivi-vm appliance: the super admin becomes the machine's owner.

Only active with `CALIVI_HOST_TOOLS=1`, and only while there are no users. Then the first
registration must carry the **setup code** shown on the VM's console: without it, whoever
reached port 80 first would get a root shell on the machine. On success the root helper
(`appliance/bootstrap/calivi_bootstrap_user.py`) creates the Linux account, and only then is
the Calivi user written — a failed helper leaves no half-registered owner behind.

The checks here are for a good error message; the helper re-validates every field as root.
"""
import hmac
import json
import re
import subprocess

from app import config

USERNAME = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
HOSTNAME = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
HELPER_TIMEOUT = 60


class BootstrapError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def required(user_count: int) -> bool:
    return config.HOST_TOOLS_ENABLED and user_count == 0


def _expected_code() -> str | None:
    try:
        with open(config.HOST_SETUP_CODE_FILE, encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def check_setup_code(code: str | None) -> None:
    expected = _expected_code()
    if expected is None:
        # Fail closed: no code file means the appliance was not set up as intended.
        raise BootstrapError(503, "This machine has no setup code yet; check its console.")
    given = (code or "").strip().upper()
    if not hmac.compare_digest(given.encode(), expected.upper().encode()):
        raise BootstrapError(403, "Wrong setup code. It is shown on this machine's console.")


def validate(username: str, hostname: str | None) -> None:
    if not USERNAME.match(username):
        raise BootstrapError(400, (
            "On this machine the username also becomes a Linux account: use lowercase letters, "
            "digits, '-' or '_', starting with a letter, at most 32 characters."
        ))
    if hostname and not HOSTNAME.match(hostname):
        raise BootstrapError(400, "Hostname: lowercase letters, digits and '-', at most 63 characters.")


def run_helper(request: dict) -> None:
    """Runs the root helper. The request goes on stdin — a password in argv shows up in `ps`."""
    try:
        proc = subprocess.run(
            config.HOST_BOOTSTRAP_CMD, input=json.dumps(request), text=True,
            capture_output=True, timeout=HELPER_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise BootstrapError(500, f"Could not run the machine setup: {e}")
    if proc.returncode == 1:
        raise BootstrapError(400, proc.stderr.strip() or "Invalid setup details.")
    if proc.returncode == 3:
        raise BootstrapError(409, "This machine already has an owner.")
    if proc.returncode != 0:
        raise BootstrapError(500, proc.stderr.strip() or "The machine setup failed.")
