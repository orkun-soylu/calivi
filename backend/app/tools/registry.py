"""Tool (function-calling) registry — a source-agnostic tool abstraction.

The agentic loop (routers/chats.py) only knows about this registry; it has no idea where
the tools come from (built-in, MCP later...). Three design decisions keep the registry
source-agnostic and MCP-ready:
  1. handlers are async with the signature `(args: dict) -> str`,
  2. sources register tools DYNAMICALLY (register / unregister_source),
  3. schemas are JSON Schema (native tool-calling and MCP speak the same format).

`mutating=True` tools only run when the caller passes `approved=True`, which the agentic loop
does after a human says yes (see `approvals.py`). The check lives here rather than in the loop
so a caller bug cannot skip it. A tool whose risk depends on its arguments (a shell command)
decides per call through `needs_approval` instead; the same gate enforces the answer.

`privileged=True` tools exist only for a privileged caller (the instance owner): they are left
out of that caller's `specs()` and refused by `execute()` as if they did not exist. The loop
decides who is privileged; the registry enforces it.
"""
from dataclasses import dataclass
from typing import Awaitable, Callable

# Marks a tool result as a failure. The agentic loop (routers/chats.py) detects failure by
# testing this prefix, so both sides MUST use this constant — a literal that drifts on one
# side only silently reports failed tool calls as successful (that regression happened once).
ERROR_PREFIX = "ERROR:"


class ToolResult(str):
    """A text result that also carries images (data URIs) for the model to look at.

    A `str`, so everything that handles results — the error-prefix test, clipping, the saved
    steps — keeps working on the text. Only the agentic loop reads `images`: tool messages
    carry text alone, so it attaches them to the next model call when the model can see.
    """

    images: list[str]

    def __new__(cls, text: str, images: list[str] | None = None):
        obj = super().__new__(cls, text)
        obj.images = list(images or [])
        return obj


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON Schema (object)
    handler: Callable[[dict], Awaitable[str]]
    source: str = "builtin"
    mutating: bool = False  # True → always needs a human yes before it runs
    # Per-call decision for a tool whose risk depends on its arguments. Ignored when `mutating`
    # is set (that already means "always").
    needs_approval: Callable[[dict], bool] | None = None
    privileged: bool = False  # True → invisible and unrunnable for a non-privileged caller

    def requires_approval(self, args: dict) -> bool:
        if self.mutating:
            return True
        if self.needs_approval is None:
            return False
        try:
            return bool(self.needs_approval(args))
        except Exception:
            # A classifier that cannot decide must not grant: fail towards asking.
            return True


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def unregister_source(self, source: str) -> None:
        """Removes every tool from one source (e.g. an MCP server that dropped)."""
        for name in [n for n, t in self._tools.items() if t.source == source]:
            del self._tools[name]

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def lookup(self, name: str, privileged: bool = False) -> Tool | None:
        """`get` as seen by one caller: a privileged tool does not exist for anybody else."""
        tool = self._tools.get(name)
        if tool is not None and tool.privileged and not privileged:
            return None
        return tool

    def names(self) -> list[str]:
        return list(self._tools)

    def specs(self, names: list[str] | None = None, privileged: bool = False) -> list[dict]:
        """Native tool-calling wire format (Ollama and OpenAI share the same schema)."""
        tools = self._tools.values() if names is None else [self._tools[n] for n in names if n in self._tools]
        tools = [t for t in tools if privileged or not t.privileged]
        return [
            {
                "type": "function",
                "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
            }
            for t in tools
        ]

    async def execute(
        self, name: str, args: dict, approved: bool = False, privileged: bool = False,
        strict: bool = False,
    ) -> str:
        """Runs the tool and returns a plain-text result. Unknown/unapproved-mutating tool → an
        error string rather than an exception, so the model can recover and the loop survives.

        `approved` defaults to False on purpose. The loop obtains a human decision before
        setting it, but the check stays **here**: loosening it because "the caller handles
        approval now" would move a security boundary into the caller, where a later refactor
        can silently skip it. The loop asks; the registry still refuses.

        `privileged` follows the same rule: default False, and a privileged tool named by a
        non-privileged caller gets the unknown-tool answer, so its existence does not leak.

        `strict` is the user's "ask before every tool" mode: every call needs `approved`,
        whatever the tool's own classification says. It can only add a question, never
        remove one.
        """
        args = args or {}
        tool = self.lookup(name, privileged)
        if tool is None:
            return f"{ERROR_PREFIX} no tool named '{name}'.{self._name_hint(name, privileged)}"
        if (strict or tool.requires_approval(args)) and not approved:
            # Not "changes state": under strict mode a harmless `uptime` lands here too, and a
            # model told it changed state explains the refusal wrongly (seen on calivi-vm).
            return f"{ERROR_PREFIX} the user did not approve this call to '{name}'; it was not run."
        return await tool.handler(args)

    def _name_hint(self, name: str, privileged: bool = False) -> str:
        """Points at the real name when a model drops a namespace (calls `scan_packages` for
        `mcp__cve__scan_packages`). Only a hint: running the guessed tool would bypass the loop's
        per-name approval lookup, and an ambiguous guess could run the wrong server's tool."""
        bare = name.rsplit("__", 1)[-1]
        matches = [
            n for n, t in self._tools.items()
            if n.rsplit("__", 1)[-1] == bare and (privileged or not t.privileged)
        ]
        return f" Did you mean '{matches[0]}'?" if len(matches) == 1 else ""


registry = ToolRegistry()
