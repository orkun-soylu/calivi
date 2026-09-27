"""Tool layer package. Exports `registry` and triggers registration of the built-in tools
by importing them (import side-effect). `from app.tools import registry` is enough."""
from app.tools.registry import ERROR_PREFIX, Tool, ToolRegistry, registry
from app.tools import builtins  # noqa: F401 — importing registers the built-in tools
from app.tools import host  # noqa: F401 — registers the host tools, only if CALIVI_HOST_TOOLS=1

__all__ = ["ERROR_PREFIX", "Tool", "ToolRegistry", "registry"]
