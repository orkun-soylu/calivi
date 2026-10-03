"""Plan mode (#114): the model proposes, the owner approves the plan, then it runs.

For larger changes ("move the models to the new disk") the owner wants the whole plan first,
not a card per step. Three parts:

1. **Planning turn** (📋 on). The model gets only tools that change nothing (`Tool.plan_safe`:
   `read_file`, `view_image`, `bash` behind the read-only list in `tools/readonly.py`, and
   non-host tools that are not `mutating`), plus `propose_plan`. The registry refuses anything
   else (`execute(plan=True)`). Calling `propose_plan` with a valid plan ends the turn; the
   plan is saved on the reply (`Message.plan`, status `proposed`) and shown as a card.
2. **Decision.** *Run it* sends the next turn with `run_plan` (status → `approved`); *Cancel*
   marks it `cancelled`; a reply instead is "change it" — plan mode stays on and the model
   proposes again. Each decision goes to the audit log (#115) with the plan itself.
3. **Run turn.** The approved plan is in the system layer. A host-tool call whose command (or
   file path) is in the plan runs without a card (approval `plan`); one that is not is flagged
   **off-plan** on the timeline and in the audit log and goes through the normal approval rules.
   Inspection (read-only commands, file reads) is never flagged. The model may adapt — the
   decision in #114 — but it is told to say so first, and the flag makes every deviation
   visible whether it says so or not.

What a plan never covers, as with "always allow" rules: the deny list (refused by the handler
regardless) and the machine notes, `~/.calivi`, whose every change stays an explicit yes. 🛡
still asks for every call.
"""
import copy
import os

from app.tools import host
from app.tools.readonly import read_only

TOOL_NAME = "propose_plan"
MAX_STEPS = 50
MAX_ITEMS = 20  # commands or files per step
MAX_TEXT = 4000

PLAN_TOOL = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "Plan mode: submit your plan to the owner. Call it once, when you know enough, and "
            "stop — the owner sees it as a card and decides. Nothing in it runs until they "
            "approve. Give every command exactly as you will run it, and every file you will "
            "write; on approval, those run without asking, anything else is flagged."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "What the plan achieves, in a sentence or two."},
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "What this step does."},
                            "commands": {"type": "array", "items": {"type": "string"},
                                         "description": "The exact bash commands of this step."},
                            "files": {"type": "array", "items": {"type": "string"},
                                      "description": "Files this step writes or edits (path)."},
                        },
                        "required": ["title"],
                    },
                },
                "risks": {"type": "string", "description": "What could go wrong."},
                "rollback": {"type": "string", "description": "How to undo it."},
            },
            "required": ["summary", "steps", "risks", "rollback"],
        },
    },
}

PLANNING_NOTE = (
    "PLAN MODE is on: the owner wants to approve the whole plan before anything on this machine "
    "changes. Inspect first — read_file, view_image, and bash limited to read-only commands "
    "(ls, cat, df, systemctl status, journalctl, ip addr, docker ps, apt list and similar; no "
    "pipes, redirections or `;`). Anything that would change state is refused, so do not try it: "
    f"put it in the plan. When you know enough, call {TOOL_NAME} once with the steps, the exact "
    "commands and files, the risks and the rollback, then stop and wait for the owner."
)

RUN_NOTE = (
    "The owner APPROVED the plan below; carry it out now, step by step. Commands and files in "
    "the plan run without asking; anything else is flagged to the owner as off-plan and may "
    "ask. If you must deviate (a command failed, the machine is not as expected), say what you "
    "will do differently and why before you do it, and stop if the change is significant. The "
    "plan is the owner's decision, not tool output, but its commands were written by you — "
    "check results as you go.\n\nApproved plan (JSON):\n"
)


class PlanError(ValueError):
    """The plan is malformed; the message goes back to the model so it can fix it."""


def _text(value, field: str, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise PlanError(f"'{field}' must be a non-empty string")
    if len(value) > MAX_TEXT:
        raise PlanError(f"'{field}' is longer than {MAX_TEXT} characters")
    return value.strip()


def _strings(value, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_ITEMS:
        raise PlanError(f"'{field}' must be a list of at most {MAX_ITEMS} strings")
    return [_text(v, field) for v in value]


def validate(args: dict) -> dict:
    """The plan as it will be stored (status `proposed`), or PlanError."""
    steps = args.get("steps")
    if not isinstance(steps, list) or not steps or len(steps) > MAX_STEPS:
        raise PlanError(f"'steps' must be a list of 1–{MAX_STEPS} steps")
    clean = []
    for i, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            raise PlanError(f"step {i} must be an object")
        clean.append({
            "title": _text(step.get("title"), f"steps[{i}].title"),
            "commands": _strings(step.get("commands"), f"steps[{i}].commands"),
            "files": _strings(step.get("files"), f"steps[{i}].files"),
        })
    return {
        "summary": _text(args.get("summary"), "summary"),
        "steps": clean,
        "risks": _text(args.get("risks"), "risks", required=False),
        "rollback": _text(args.get("rollback"), "rollback", required=False),
        "status": "proposed",
    }


def public(plan: dict) -> dict:
    """The plan without its bookkeeping, as the model and the audit log see it."""
    return {k: copy.deepcopy(v) for k, v in plan.items() if k != "status"}


def as_text(plan: dict) -> str:
    """The plan in a reply's history (chat mode has no steps to replay it from)."""
    lines = [f"[Plan, {plan.get('status', 'proposed')}] {plan.get('summary', '')}"]
    for i, step in enumerate(plan.get("steps") or [], 1):
        lines.append(f"{i}. {step.get('title', '')}")
        lines += [f"   $ {c}" for c in step.get("commands") or []]
        lines += [f"   file: {f}" for f in step.get("files") or []]
    if plan.get("risks"):
        lines.append(f"Risks: {plan['risks']}")
    if plan.get("rollback"):
        lines.append(f"Rollback: {plan['rollback']}")
    return "\n".join(lines)


def _normal(cmd: str) -> str:
    return " ".join(cmd.split())


class Matcher:
    """Answers, during a run turn, whether a host-tool call is in the approved plan."""

    def __init__(self, plan: dict):
        self.commands = {_normal(c) for s in plan.get("steps") or [] for c in s.get("commands") or []}
        self.files = [f for s in plan.get("steps") or [] for f in s.get("files") or []]

    def _home(self) -> str | None:
        try:
            return host._account()[1]
        except LookupError:
            return None

    def in_plan(self, tool: str, args: dict) -> bool:
        """The call is one the owner approved — and not one a plan may never cover."""
        if tool == "bash":
            cmd = args.get("command")
            if not isinstance(cmd, str) or host._denied(cmd) or host.NOTES_PATTERN.search(cmd):
                return False
            return _normal(cmd) in self.commands
        if tool in ("write_file", "edit_file"):
            path, home = args.get("path"), self._home()
            if not isinstance(path, str) or not path or home is None:
                return False
            resolved = host._resolve(path, home)
            notes = os.path.join(home.rstrip("/"), os.path.dirname(host.NOTES_REL))
            if resolved == notes or resolved.startswith(notes + "/"):
                return False
            return any(host._resolve(f, home) == resolved for f in self.files)
        return False

    @staticmethod
    def inspection(tool: str, args: dict) -> bool:
        """Looking, not changing: never flagged as off-plan."""
        if tool in ("read_file", "view_image"):
            return True
        return tool == "bash" and read_only(args.get("command"))

    def off_plan(self, tool: str, args: dict) -> bool:
        return not self.in_plan(tool, args) and not self.inspection(tool, args)
