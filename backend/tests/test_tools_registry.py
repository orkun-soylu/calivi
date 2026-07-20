"""Tool registry — the read-only gate and error resilience.

In Phase 2 (approval UI + MCP source) this file is the safety net: it must break if the
`mutating` gate is opened by accident, or if `execute` starts leaking exceptions.
"""
import pytest

from app.tools.registry import Tool, ToolRegistry


def _tool(name="sample", mutating=False, handler=None, source="builtin"):
    async def default(args):
        return f"ok:{args}"

    return Tool(
        name=name,
        description="test tool",
        parameters={"type": "object", "properties": {}},
        handler=handler or default,
        source=source,
        mutating=mutating,
    )


@pytest.fixture
def reg():
    return ToolRegistry()


async def test_read_only_tool_runs(reg):
    reg.register(_tool())
    assert await reg.execute("sample", {"x": 1}) == "ok:{'x': 1}"


async def test_mutating_tool_is_rejected(reg):
    """Phase 1 read-only gate — a state-changing tool must not run before approval exists."""
    ran = False

    async def handler(args):
        nonlocal ran
        ran = True
        return "state changed"

    reg.register(_tool(name="dangerous", mutating=True, handler=handler))

    result = await reg.execute("dangerous", {})
    assert ran is False  # the handler must NEVER be entered
    assert result.startswith("ERROR:")


async def test_unknown_tool_returns_error_text(reg):
    """Text rather than an exception: the model can recover and the agentic loop survives."""
    result = await reg.execute("missing", {})
    assert result.startswith("ERROR:")


async def test_handler_blowing_up_does_not_crash_the_loop(reg):
    """A deliberate boundary: the registry does NOT swallow handler exceptions — the caller
    (chats.py) catches them. This test pins that contract, so we find out if the registry
    ever starts swallowing them."""

    async def exploding(args):
        raise RuntimeError("upstream died")

    reg.register(_tool(name="broken", handler=exploding))
    with pytest.raises(RuntimeError):
        await reg.execute("broken", {})


async def test_specs_wire_format(reg):
    reg.register(_tool(name="a"))
    reg.register(_tool(name="b"))

    every = reg.specs()
    assert len(every) == 2
    assert every[0]["type"] == "function"
    assert set(every[0]["function"]) == {"name", "description", "parameters"}

    # Filter by name; unknown names are skipped silently (config may name a retired tool)
    assert [s["function"]["name"] for s in reg.specs(["b", "nope"])] == ["b"]


async def test_unregister_source_clears_that_source(reg):
    """When an MCP source drops, its tools must go and the built-ins must stay."""
    reg.register(_tool(name="local", source="builtin"))
    reg.register(_tool(name="remote1", source="mcp:server"))
    reg.register(_tool(name="remote2", source="mcp:server"))

    reg.unregister_source("mcp:server")
    assert reg.names() == ["local"]


async def test_same_name_overwrites(reg):
    async def newer(args):
        return "new version"

    reg.register(_tool(name="x"))
    reg.register(_tool(name="x", handler=newer))
    assert await reg.execute("x", {}) == "new version"
    assert len(reg.names()) == 1


async def test_web_search_builtin_is_registered_and_read_only():
    """The real registry singleton: Phase 1's only tool must be registered and NOT mutating."""
    from app.tools import builtins  # noqa: F401  importing registers it
    from app.tools.registry import registry

    tool = registry.get("web_search")
    assert tool is not None and tool.mutating is False
