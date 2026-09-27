"""Host tools — the chat model operates the machine Calivi runs on (the calivi-vm appliance).

`bash`, `read_file`, `write_file`, `edit_file`, the same shape as a terminal coding agent. They
register only when `CALIVI_HOST_TOOLS=1`, and every one is `privileged`: the super admin alone
sees or runs them (see *Per-call approval and privileged tools* in ARCHITECTURE.md).

**Who runs the command.** The backend is an unprivileged service account. Everything here —
the file tools included — executes as the owner's Linux account through `sudo -n -u <user>`,
the one thing the service account may sudo to. When the configured account *is* the backend's
own user (development, tests) the sudo hop is skipped.

**The approval policy is a seatbelt, not a boundary.** It pattern-matches command text to catch
a model's *mistakes* — an `rm` it did not think through, a `systemctl stop` that cuts the
session. A command can always be written so no pattern sees it, and the account has sudo by
design. The boundary is the VM itself.
"""
import asyncio
import getpass
import os
import pwd
import re
import tempfile
import time

from app import config
from app.tools.registry import ERROR_PREFIX, Tool, registry

SOURCE = "host"
MAX_OUTPUT_CHARS = 30_000
READ_DEFAULT_LIMIT = 2000  # lines
_KILL_GRACE = 5  # seconds between timeout's TERM and KILL
_WAIT_MARGIN = 15  # extra seconds before the backend gives up on a command timeout missed


def _word(w: str) -> str:
    """A command word: not part of a longer word, a path or an option (`--rm`, `perm`, `x.rm`)."""
    return rf"(?<![\w.-]){w}(?![\w-])"


# Ask first: commands that destroy data, cut access to the machine, or stop things running.
_ASK = [re.compile(p) for p in (
    _word(r"(rm|rmdir|shred|unlink|truncate|mv)"),
    _word(r"(dd|wipefs|fdisk|sfdisk|parted|sgdisk|gdisk)"),
    _word(r"mkfs(\.\w+)?"),
    _word(r"(shutdown|reboot|poweroff|halt)"),
    _word(r"systemctl") + r"\s+(\S+\s+)*(stop|disable|mask|kill|isolate|rescue|poweroff|reboot|halt)\b",
    _word(r"(kill|killall|pkill)"),
    _word(r"(chmod|chown|chgrp)") + r"\s+(\S+\s+)*-\w*R",
    _word(r"(userdel|deluser|usermod|passwd|chpasswd|visudo)"),
    _word(r"apt(-get)?") + r"\s+(\S+\s+)*(remove|purge|autoremove)\b",
    _word(r"dpkg") + r"\s+(\S+\s+)*(-r|-P|--remove|--purge)\b",
    _word(r"(iptables|ip6tables|nft|ufw|ifdown|ifup|nmcli)"),
    _word(r"ip") + r"\s+(link|addr|address|route)\s+(set|del|delete|flush|add|change|replace)\b",
    _word(r"crontab") + r"\s+(\S+\s+)*-r\b",
    _word(r"git") + r"\s+(push|clean|reset\s+(\S+\s+)*--hard)\b",
    _word(r"find") + r"\s.*\s-delete\b",
    r"\|\s*(sudo\s+(-\S+\s+)*)?(ba|z|da)?sh\b",  # piping into a shell: curl … | sh
    # Writing into system paths, by redirect or by tee (the usual `| sudo tee` form).
    r">\s*/(etc|boot|usr|bin|sbin|lib|lib64|var|opt)/",
    _word(r"tee") + r"\s+(-\S+\s+)*/(etc|boot|usr|bin|sbin|lib|lib64|var|opt)/",
)]

# Never, approved or not: nothing useful needs these, and a slipped click is unrecoverable.
_DENY = [re.compile(p) for p in (
    r"--no-preserve-root\b",
    _word(r"rm") + r"\s+(-\S+\s+)*(/|/\*)(?=\s|[;&|)]|$)",
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}",  # fork bomb
)]


def _command(args: dict) -> str:
    cmd = args.get("command")
    if not isinstance(cmd, str):
        raise ValueError("command must be a string")
    return cmd


def _denied(cmd: str) -> bool:
    return any(p.search(cmd) for p in _DENY)


def bash_needs_approval(args: dict) -> bool:
    cmd = _command(args)  # raising → the registry treats it as "ask"
    if _denied(cmd):
        return False  # refused by the handler anyway; a card would promise that "yes" works
    return any(p.search(cmd) for p in _ASK)


# --- The account ----------------------------------------------------------------------------


def _account() -> tuple[str, str]:
    """(user, home) that commands run as. Read per call: the appliance writes the file at first
    registration, while the backend is already running."""
    user = config.HOST_USER
    if not user:
        try:
            with open(config.HOST_USER_FILE, encoding="utf-8") as f:
                user = f.read().strip()
        except FileNotFoundError:
            user = ""
    if not user:
        raise LookupError("no host account is configured yet")
    return user, pwd.getpwnam(user).pw_dir


def _resolve(path: str, home: str) -> str:
    """Absolute, normalised path. `~` is expanded here, because the path reaches bash as a
    quoted argument where the shell would not expand it; relative paths are relative to home,
    where every command starts."""
    if path == "~" or path.startswith("~/"):
        path = home + path[1:]
    elif not path.startswith("/"):
        path = os.path.join(home, path)
    return os.path.normpath(path)


def path_needs_approval(args: dict) -> bool:
    """Writes outside the account's home ask first. Lexical only — a symlink inside home can
    point out of it; the write still happens with the account's own (non-sudo) permissions."""
    path = args.get("path")
    if not isinstance(path, str) or not path:
        return True
    _, home = _account()
    resolved = _resolve(path, home)
    home = home.rstrip("/")
    return not (resolved == home or resolved.startswith(home + "/"))


# --- Running --------------------------------------------------------------------------------


def _clip(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    head = MAX_OUTPUT_CHARS // 3
    tail = MAX_OUTPUT_CHARS - head
    omitted = len(text) - head - tail
    return f"{text[:head]}\n\n… [{omitted} characters omitted] …\n\n{text[-tail:]}"


async def _run(script: str, *argv: str, stdin: str | None = None, timeout: int | None = None
               ) -> tuple[int | None, str]:
    """Runs `script` in bash as the host account, starting in its home. Returns (exit code,
    combined output); the exit code is None when the command was killed for running too long.

    Output goes to a temporary file, not a pipe. With a pipe, a process the command leaves
    running in the background (`nohup server &`) keeps the write end open, the read never sees
    EOF, and the call hangs until the timeout — which then kills that background process too.
    With a file the call returns when the command itself exits.
    """
    user, home = _account()
    timeout = timeout or config.HOST_COMMAND_TIMEOUT
    # GNU timeout signals its whole process group, so a runaway pipeline dies with it.
    inner = ["timeout", "-k", str(_KILL_GRACE), str(timeout),
             "bash", "-lc", f"cd ~ 2>/dev/null || cd /\n{script}", "calivi-host", *argv]
    direct = user == getpass.getuser()
    cmd = inner if direct else ["sudo", "-n", "-u", user, "-H", "--", *inner]
    env = {**os.environ, "HOME": home} if direct else None
    with tempfile.TemporaryFile() as out:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=out, stderr=out, cwd="/", env=env,
        )
        started = time.monotonic()
        try:
            if stdin is not None:
                proc.stdin.write(stdin.encode())
                await proc.stdin.drain()
                proc.stdin.close()
            await asyncio.wait_for(proc.wait(), timeout + _KILL_GRACE + _WAIT_MARGIN)
            code = proc.returncode
        except TimeoutError:
            # `timeout` should have fired first; this is the backstop. sudo relays TERM to the
            # command it runs.
            proc.terminate()
            code = None
        except asyncio.CancelledError:
            proc.terminate()  # a closed tab: do not leave the command running unattended
            raise
        out.seek(0)
        text = out.read().decode(errors="replace")
    # 124/137 is how `timeout` reports a kill — but only trust it if the time was really up,
    # or a command that itself exits 124 would be reported as killed.
    if code in (124, 137) and time.monotonic() - started >= timeout:
        code = None
    return code, text


# --- Handlers -------------------------------------------------------------------------------


async def _bash(args: dict) -> str:
    try:
        cmd = _command(args)
    except ValueError as e:
        return f"{ERROR_PREFIX} {e}."
    if not cmd.strip():
        return f"{ERROR_PREFIX} empty command."
    if _denied(cmd):
        return f"{ERROR_PREFIX} this command is refused by policy and was not run."
    try:
        code, output = await _run(cmd)
    except LookupError as e:
        return f"{ERROR_PREFIX} {e}."
    if code is None:
        return (f"{ERROR_PREFIX} the command did not finish within {config.HOST_COMMAND_TIMEOUT}s "
                f"and was killed. Run long jobs detached (see the tool description).\n\n"
                f"{_clip(output)}")
    return f"exit code: {code}\n\n{_clip(output)}" if output else f"exit code: {code}"


async def _read(path: str) -> tuple[str | None, str]:
    """(content, error). Reads as the host account."""
    code, output = await _run('cat -- "$1"', path)
    if code != 0:
        return None, output.strip() or f"could not read {path}"
    return output, ""


async def _write(path: str, content: str) -> str:
    code, output = await _run(
        'mkdir -p -- "$(dirname -- "$1")" && cat > "$1"', path, stdin=content
    )
    return "" if code == 0 else (output.strip() or f"could not write {path}")


def _path_arg(args: dict) -> tuple[str | None, str]:
    path = args.get("path")
    if not isinstance(path, str) or not path.strip():
        return None, "path is required."
    try:
        _, home = _account()
    except LookupError as e:
        return None, f"{e}."
    return _resolve(path, home), ""


async def _read_file(args: dict) -> str:
    path, err = _path_arg(args)
    if err:
        return f"{ERROR_PREFIX} {err}"
    content, err = await _read(path)
    if err:
        return f"{ERROR_PREFIX} {err}"
    if "\x00" in content:
        return f"{ERROR_PREFIX} {path} looks like a binary file; inspect it with bash instead."
    lines = content.splitlines(keepends=True)
    offset = args.get("offset") if isinstance(args.get("offset"), int) else 1
    limit = args.get("limit") if isinstance(args.get("limit"), int) else READ_DEFAULT_LIMIT
    start = max(offset, 1) - 1
    chunk = lines[start:start + max(limit, 1)]
    text = _clip("".join(chunk))
    if start == 0 and len(chunk) == len(lines):
        return text
    return f"[{path}: lines {start + 1}-{start + len(chunk)} of {len(lines)}]\n{text}"


async def _write_file(args: dict) -> str:
    path, err = _path_arg(args)
    if err:
        return f"{ERROR_PREFIX} {err}"
    content = args.get("content")
    if not isinstance(content, str):
        return f"{ERROR_PREFIX} content must be a string."
    err = await _write(path, content)
    return f"{ERROR_PREFIX} {err}" if err else f"wrote {len(content)} characters to {path}"


async def _edit_file(args: dict) -> str:
    path, err = _path_arg(args)
    if err:
        return f"{ERROR_PREFIX} {err}"
    old, new = args.get("old_string"), args.get("new_string")
    if not isinstance(old, str) or not old or not isinstance(new, str):
        return f"{ERROR_PREFIX} old_string (non-empty) and new_string are required."
    content, err = await _read(path)
    if err:
        return f"{ERROR_PREFIX} {err}"
    count = content.count(old)
    if count == 0:
        return f"{ERROR_PREFIX} old_string was not found in {path}; read the file and copy it exactly."
    if count > 1 and not args.get("replace_all"):
        return (f"{ERROR_PREFIX} old_string occurs {count} times in {path}; add surrounding text "
                "to make it unique, or set replace_all.")
    err = await _write(path, content.replace(old, new))
    return f"{ERROR_PREFIX} {err}" if err else f"replaced {count} occurrence(s) in {path}"


# --- Registration ---------------------------------------------------------------------------

_ACCOUNT_NOTE = "Runs as this machine's owner's Linux account, which has passwordless sudo. "
_FILE_NOTE = "Runs as this machine's owner's Linux account, without sudo"

TOOLS = [
    Tool(
        name="bash",
        description=(
            "Runs a bash command on this machine (a Debian VM) and returns its exit code and "
            "combined stdout/stderr. " + _ACCOUNT_NOTE +
            "Each call is a fresh login shell starting in the home directory: `cd` and "
            "variables do not carry over, so chain related steps with `&&`. Commands are killed "
            f"after {config.HOST_COMMAND_TIMEOUT}s — start long jobs detached with their output "
            "in a file (`nohup cmd >~/job.log 2>&1 &`, or `sudo systemd-run --unit=<name> cmd`) "
            "and check on them in later calls. Nothing is interactive: pass `-y` / "
            "`DEBIAN_FRONTEND=noninteractive` and never start an editor or pager. Destructive "
            "commands wait for the user's approval."
        ),
        parameters={
            "type": "object",
            "properties": {"command": {"type": "string", "description": "The bash command."}},
            "required": ["command"],
        },
        handler=_bash,
        source=SOURCE,
        needs_approval=bash_needs_approval,
        privileged=True,
    ),
    Tool(
        name="read_file",
        description=(
            "Reads a text file on this machine. " + _FILE_NOTE + ". Relative "
            f"paths and `~` are relative to the home directory. Returns up to {READ_DEFAULT_LIMIT} "
            "lines; use offset/limit for more."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "offset": {"type": "integer", "description": "1-based first line (default 1)."},
                "limit": {"type": "integer", "description": "Number of lines."},
            },
            "required": ["path"],
        },
        handler=_read_file,
        source=SOURCE,
        privileged=True,
    ),
    Tool(
        name="write_file",
        description=(
            "Creates or overwrites a text file with the given content, creating parent "
            "directories. " + _FILE_NOTE + " — for a system file write to a temp file and "
            "`sudo install` it with bash. Relative paths and `~` are relative to the home "
            "directory; writes outside it wait for the user's approval."
        ),
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
        handler=_write_file,
        source=SOURCE,
        needs_approval=path_needs_approval,
        privileged=True,
    ),
    Tool(
        name="edit_file",
        description=(
            "Replaces an exact string in a text file. old_string must match the file exactly "
            "(read it first) and be unique unless replace_all is set. " + _FILE_NOTE + ". Edits "
            "outside the home directory wait for the user's approval."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
                "replace_all": {"type": "boolean"},
            },
            "required": ["path", "old_string", "new_string"],
        },
        handler=_edit_file,
        source=SOURCE,
        needs_approval=path_needs_approval,
        privileged=True,
    ),
]


def register() -> None:
    for tool in TOOLS:
        registry.register(tool)


if config.HOST_TOOLS_ENABLED:
    register()
