"""Tool (function-calling) registry — a source-agnostic tool abstraction.

The agentic loop (routers/chats.py) only knows about this registry; it has no idea where
the tools come from (built-in, MCP later...). Three design decisions keep the registry
source-agnostic and MCP-ready:
  1. handlers are async with the signature `(args: dict) -> str`,
  2. sources register tools DYNAMICALLY (register / unregister_source),
  3. schemas are JSON Schema (native tool-calling and MCP speak the same format).

Phase 1 is read-only: `mutating=True` tools are never executed (there is no approval /
human-in-the-loop layer yet). State-changing tools and the MCP source are Phase 2.
"""
from dataclasses import dataclass
from typing import Awaitable, Callable

# Marks a tool result as a failure. The agentic loop (routers/chats.py) detects failure by
# testing this prefix, so both sides MUST use this constant — a literal that drifts on one
# side only silently reports failed tool calls as successful (that regression happened once).
ERROR_PREFIX = "ERROR:"


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON Schema (object)
    handler: Callable[[dict], Awaitable[str]]
    source: str = "builtin"
    mutating: bool = False  # True → not executed in Phase 1 (read-only gate)


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

    def names(self) -> list[str]:
        return list(self._tools)

    def specs(self, names: list[str] | None = None) -> list[dict]:
        """Native tool-calling wire format (Ollama and OpenAI share the same schema)."""
        tools = self._tools.values() if names is None else [self._tools[n] for n in names if n in self._tools]
        return [
            {
                "type": "function",
                "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
            }
            for t in tools
        ]

    async def execute(self, name: str, args: dict) -> str:
        """Runs the tool and returns a plain-text result. Unknown/mutating tool → an error
        string rather than an exception, so the model can recover and the loop survives."""
        tool = self._tools.get(name)
        if tool is None:
            return f"{ERROR_PREFIX} no tool named '{name}'."
        if tool.mutating:
            # Phase 1 read-only gate: state-changing tools are rejected until approval lands.
            return f"{ERROR_PREFIX} tool '{name}' is disabled (only read-only tools are active)."
        return await tool.handler(args or {})


registry = ToolRegistry()
