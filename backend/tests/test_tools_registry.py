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


async def test_unknown_name_hints_the_namespaced_tool(reg):
    """A model that drops the MCP namespace gets the real name back instead of a dead end."""
    reg.register(_tool(name="mcp__cve__scan_packages", source="mcp:cve"))
    result = await reg.execute("scan_packages", {})
    assert result.startswith("ERROR:") and "Did you mean 'mcp__cve__scan_packages'?" in result
    assert "Did you mean" in await reg.execute("other__scan_packages", {})


async def test_unknown_name_gives_no_hint_when_ambiguous_or_absent(reg):
    reg.register(_tool(name="mcp__a__search", source="mcp:a"))
    reg.register(_tool(name="mcp__b__search", source="mcp:b"))
    assert "Did you mean" not in await reg.execute("search", {})
    assert "Did you mean" not in await reg.execute("nothing_like_it", {})


# --- Per-call approval (`needs_approval`) ---------------------------------------------------
# A shell tool cannot be "always mutating" (every `ls` would prompt, and approval decays into
# reflexive clicking) nor "never" — the decision depends on the command. These pin the gate.


def _classified(needs_approval, mutating=False):
    ran = []

    async def handler(args):
        ran.append(args)
        return "ran"

    tool = _tool(name="shell", handler=handler, mutating=mutating)
    tool.needs_approval = needs_approval
    return tool, ran


async def test_per_call_risky_args_are_refused_without_approval(reg):
    tool, ran = _classified(lambda args: args.get("cmd") == "rm -rf /")
    reg.register(tool)

    assert (await reg.execute("shell", {"cmd": "rm -rf /"})).startswith("ERROR:")
    assert ran == []
    assert await reg.execute("shell", {"cmd": "rm -rf /"}, approved=True) == "ran"


async def test_per_call_harmless_args_run_without_approval(reg):
    tool, ran = _classified(lambda args: args.get("cmd") == "rm -rf /")
    reg.register(tool)

    assert await reg.execute("shell", {"cmd": "ls"}) == "ran"
    assert ran == [{"cmd": "ls"}]


async def test_a_classifier_that_blows_up_asks(reg):
    """Fail-safe: a classifier that cannot decide must not grant."""

    def broken(args):
        raise KeyError("cmd")

    tool, ran = _classified(broken)
    reg.register(tool)

    assert (await reg.execute("shell", {})).startswith("ERROR:")
    assert ran == []


async def test_mutating_wins_over_a_permissive_classifier(reg):
    tool, ran = _classified(lambda args: False, mutating=True)
    reg.register(tool)

    assert (await reg.execute("shell", {"cmd": "ls"})).startswith("ERROR:")
    assert ran == []


# --- Privileged tools -----------------------------------------------------------------------
# Host tools (the appliance's own shell) belong to the instance owner. For anybody else they
# must not exist: not offered, not runnable, not even hinted at.


def _privileged(name="host_shell"):
    ran = []

    async def handler(args):
        ran.append(args)
        return "ran"

    tool = _tool(name=name, handler=handler)
    tool.privileged = True
    return tool, ran


async def test_privileged_tool_is_not_offered_to_others(reg):
    tool, _ = _privileged()
    reg.register(tool)
    reg.register(_tool(name="public"))

    assert [s["function"]["name"] for s in reg.specs()] == ["public"]
    assert [s["function"]["name"] for s in reg.specs(["host_shell", "public"])] == ["public"]
    assert {s["function"]["name"] for s in reg.specs(privileged=True)} == {"host_shell", "public"}


async def test_privileged_tool_is_refused_for_others(reg):
    """A model can name a tool it was never offered — the registry is the boundary."""
    tool, ran = _privileged()
    reg.register(tool)

    result = await reg.execute("host_shell", {})
    assert result.startswith("ERROR:")
    assert "no tool named" in result  # indistinguishable from a tool that does not exist
    assert ran == []
    assert await reg.execute("host_shell", {}, privileged=True) == "ran"


async def test_privileged_tool_is_not_leaked_by_the_name_hint(reg):
    tool, _ = _privileged(name="mcp__host__shell")
    reg.register(tool)

    assert "mcp__host__shell" not in await reg.execute("shell", {})
    assert "mcp__host__shell" in await reg.execute("shell", {}, privileged=True)


async def test_lookup_hides_privileged_tools(reg):
    tool, _ = _privileged()
    reg.register(tool)

    assert reg.lookup("host_shell") is None
    assert reg.lookup("host_shell", privileged=True) is tool
    assert reg.get("host_shell") is tool  # the raw accessor stays raw


# --- Strict mode ("ask before every tool") --------------------------------------------------


async def test_strict_asks_even_for_a_harmless_call(reg):
    ran = []

    async def handler(args):
        ran.append(args)
        return "ran"

    reg.register(_tool(name="harmless", handler=handler))
    assert (await reg.execute("harmless", {}, strict=True)).startswith("ERROR:")
    assert ran == []
    assert await reg.execute("harmless", {}, strict=True, approved=True) == "ran"


async def test_strict_cannot_reveal_a_privileged_tool(reg):
    """Strict only ever adds a question; approving it must not reach a hidden tool."""
    tool, ran = _privileged()
    reg.register(tool)
    result = await reg.execute("host_shell", {}, strict=True, approved=True)
    assert "no tool named" in result
    assert ran == []
