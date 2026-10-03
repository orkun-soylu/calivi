""""Always allow" rules for host-tool approvals (#113).

On calivi-vm a routine the owner trusts — `systemctl restart ollama`, a config file under
`/etc/nginx/` — otherwise asks every time, and approval decays into clicking. A rule lets one
narrow, owner-written pattern answer "yes" in the owner's place.

**The rule language is deliberately small** (decided in #113):

- `bash` — `exact` (the command, token for token) or `prefix` (the command starts with these
  tokens; anything may follow). Tokens are compared after shell-style splitting, so quoting
  does not matter and spacing does not either.
- `write_file` / `edit_file` — `dir`: the path is inside this directory.

**What a rule can never cover**, checked at match time as well as when a rule is saved — a rule
saved by an older version must not outlive a tightened policy:

- A command with shell syntax in it: `;` `&` `|` backticks, `$`, redirections, parentheses,
  braces, a backslash or a newline. Otherwise `systemctl restart ollama; rm -rf ~` would ride on
  the rule for `systemctl restart ollama`. A rule matches simple commands, nothing composed.
- The deny list (`tools/host.py`): refused outright, never asked, so never "allowed".
- The machine notes, `~/.calivi` (#110): every change there stays an explicit yes.
- A `prefix` with fewer than two words that are not options or `sudo` — `rm -rf` or `sudo`
  alone would be a blanket grant. A `dir` of `/`, for the same reason.

**🛡 (ask before every tool) overrides every rule** — the loop does not consult them then.

Like the rest of the approval policy this is a seatbelt: a rule narrows what asks, it does not
widen what the account can do. Every call a rule approves is in the audit log (#115) with the
rule that approved it, and so is every rule added or deleted.
"""
import os

from sqlalchemy.orm import Session

from app import models
from app.database import SessionLocal
from app.tools import host
from app.tools.shellwords import simple_words

KINDS = {"bash": ("exact", "prefix"), "write_file": ("dir",), "edit_file": ("dir",)}
MAX_PATTERN = 500


class RuleError(ValueError):
    """The rule cannot be saved; the message says why (shown to the owner)."""


def _bash_coverable(cmd: str) -> list[str] | None:
    """The command's tokens if a rule may ever cover it, else None."""
    tokens = simple_words(cmd)
    if tokens is None or host._denied(cmd) or host.NOTES_PATTERN.search(cmd):
        return None
    return tokens


def _notes_dir(home: str) -> str:
    return os.path.join(home.rstrip("/"), os.path.dirname(host.NOTES_REL))


def _inside(path: str, directory: str) -> bool:
    return path == directory or path.startswith(directory.rstrip("/") + "/")


def _home() -> str:
    return host._account()[1]


# --- Matching (pure, given the rules) -------------------------------------------------------


def matches(tool: str, kind: str, pattern: str, args: dict, home: str | None = None) -> bool:
    if kind not in KINDS.get(tool, ()):
        return False
    if tool == "bash":
        cmd_tokens = _bash_coverable(args.get("command"))
        rule_tokens = _bash_coverable(pattern)
        if cmd_tokens is None or rule_tokens is None:
            return False
        if kind == "exact":
            return cmd_tokens == rule_tokens
        return cmd_tokens[:len(rule_tokens)] == rule_tokens
    path = args.get("path")
    if not isinstance(path, str) or not path:
        return False
    home = home if home is not None else _home()
    resolved = host._resolve(path, home)
    directory = host._resolve(pattern, home)
    if directory == "/" or _inside(resolved, _notes_dir(home)):
        return False
    return resolved != directory and _inside(resolved, directory)


def validate(tool: str, kind: str, pattern: str, home: str | None = None) -> str:
    """The pattern as it will be stored, or RuleError."""
    if kind not in KINDS.get(tool, ()):
        raise RuleError(f"'{kind}' rules do not exist for {tool}")
    pattern = (pattern or "").strip()
    if not pattern or len(pattern) > MAX_PATTERN:
        raise RuleError("the rule is empty or too long")
    if tool == "bash":
        tokens = _bash_coverable(pattern)
        if tokens is None:
            raise RuleError("a rule can only cover a simple command: no shell syntax "
                            "(; & | $ ` < > ( ) { } \\), nothing on the deny list, nothing under ~/.calivi")
        if kind == "prefix":
            words = [t for t in tokens if t != "sudo" and not t.startswith("-")]
            if len(words) < 2:
                raise RuleError("a prefix needs at least two words besides sudo and options — "
                                "this one would allow too much")
        return pattern  # matched by tokens, so the owner's own spelling is what is shown
    if not (pattern.startswith("/") or pattern == "~" or pattern.startswith("~/")):
        raise RuleError("the directory must be absolute or start with ~/")
    home = home if home is not None else _home()
    directory = host._resolve(pattern, home)
    if directory == "/":
        raise RuleError("a rule for / would allow writing anywhere")
    notes = _notes_dir(home)
    if _inside(directory, notes) or _inside(notes, directory):
        raise RuleError("~/.calivi (the machine notes) is never covered by a rule")
    return pattern.rstrip("/") or pattern


def suggest(tool: str, args: dict) -> dict | None:
    """The narrowest rule that covers this call, for the card to offer; None when no rule may."""
    try:
        if tool == "bash":
            cmd = args.get("command")
            if _bash_coverable(cmd) is None:
                return None
            return {"kind": "exact", "pattern": validate("bash", "exact", cmd)}
        if tool in ("write_file", "edit_file"):
            path = args.get("path")
            if not isinstance(path, str) or not path:
                return None
            parent = os.path.dirname(path.rstrip("/"))
            pattern = validate(tool, "dir", parent)
            return {"kind": "dir", "pattern": pattern} if matches(tool, "dir", pattern, args) else None
    except (RuleError, LookupError):
        return None
    return None


def describe(rule: models.ApprovalRule) -> dict:
    return {"id": rule.id, "tool": rule.tool, "kind": rule.kind, "pattern": rule.pattern}


# --- Storage --------------------------------------------------------------------------------


def find(user_id: int, tool: str, args: dict) -> dict | None:
    """The first of the owner's rules for this tool that covers the call (and counts the use)."""
    if tool not in KINDS:
        return None
    db = SessionLocal()
    try:
        try:
            home = _home()
        except LookupError:
            return None
        rules = (db.query(models.ApprovalRule)
                 .filter(models.ApprovalRule.user_id == user_id, models.ApprovalRule.tool == tool)
                 .order_by(models.ApprovalRule.id).all())
        for rule in rules:
            if matches(tool, rule.kind, rule.pattern, args, home):
                rule.uses = (rule.uses or 0) + 1
                rule.last_used_at = models.utcnow()
                db.commit()
                return describe(rule)
        return None
    finally:
        db.close()


def add(db: Session, user_id: int, tool: str, kind: str, pattern: str) -> models.ApprovalRule:
    pattern = validate(tool, kind, pattern)
    existing = (db.query(models.ApprovalRule)
                .filter_by(user_id=user_id, tool=tool, kind=kind, pattern=pattern).first())
    if existing:
        return existing
    rule = models.ApprovalRule(user_id=user_id, tool=tool, kind=kind, pattern=pattern)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule
