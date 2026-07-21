"""MCP source adapter — registers a remote MCP server's tools into the shared registry.

This is the "new source" the registry was designed for: `ToolRegistry`, the agentic loop in
`routers/chats.py` and the provider wire format are untouched. Tools arrive with
`source="mcp:<id>"` and JSON Schema parameters, which is what MCP already speaks.

Three decisions worth knowing before changing anything here:

**Connect-per-call, no long-lived sessions.** An MCP session is an async context manager, and
anyio requires its cancel scope to be exited in the task that entered it. Holding sessions
open across requests therefore means a supervisor task per server plus a dispatch queue, plus
reconnection logic. Instead every probe and every tool call opens its own short-lived session.
It costs one handshake per call and buys away that entire class of bug — the right trade at
this scale, and it makes "the server went away" a non-event rather than a state to recover.

**Read-only gate (Phase 1).** A tool is registered only when the server marks it
`readOnlyHint`. Anything else is **withheld entirely** rather than registered as `mutating` — a
tool the model can see but never run only wastes context and invites retry loops. Note the hint
is the *server's own* claim; it is a filter, not a security boundary. The real guarantee comes
from the credential (a read-only token) and from server-side read-only modes such as GitHub's
`/readonly` endpoint. Verified live against Context7 and Exa: both set `readOnlyHint=True`.

**Per-tool modes.** `McpServer.tool_modes` maps a tool to `off` / `auto` / `approve`. Unlisted
tools fall back to `auto` when read-only and `off` when mutating, so an upgrade changes nothing
until an admin opts in. `off` tools still come back in the probe result — Settings has to be
able to list and re-enable them — but are never registered. `approve` tools ARE registered, with
`mutating=True`, which is what makes the registry demand a human decision before running them.

**Namespacing.** Registry names are flat and `register()` overwrites silently, so two servers
exposing the same tool name would clobber each other — and `unregister_source()` for the loser
would then delete the winner's tool. Every MCP tool is therefore namespaced
`mcp__<server>__<tool>`, and the result is length-capped because providers limit tool names.
"""
import asyncio
import contextlib
import re
import time
from dataclasses import dataclass, field

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client

from app import models
from app.config import (
    MCP_CALL_TIMEOUT,
    MCP_CONNECT_TIMEOUT,
    MCP_MAX_TOOL_NAME,
    MCP_PROBE_TTL_DOWN,
    MCP_PROBE_TTL_UP,
)
from app.tools.registry import ERROR_PREFIX, Tool, registry

NAMESPACE_PREFIX = "mcp__"


def source_of(server_id: int) -> str:
    """Registry `source` for one server. Keyed by id, not name, so renaming a server does not
    orphan its already-registered tools."""
    return f"mcp:{server_id}"


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "server"


def namespaced(server_name: str, tool_name: str) -> str:
    """`mcp__<server>__<tool>`, capped at MCP_MAX_TOOL_NAME.

    Only dots-free characters are used: several providers restrict tool names to
    [a-zA-Z0-9_-], so a dotted separator would be rejected. When the cap bites, the *server*
    slug is truncated rather than the tool name — the tool name is what the model reasons
    about, while the slug only has to stay distinct.
    """
    tool = re.sub(r"[^a-zA-Z0-9_-]+", "_", tool_name)
    slug = slugify(server_name)
    budget = MCP_MAX_TOOL_NAME - len(NAMESPACE_PREFIX) - len("__") - len(tool)
    if budget < 1:
        # Pathological tool name: keep it, drop the slug to a single char. Still unique per
        # server in practice, and the registry would rather have a long name than a broken one.
        budget = 1
    return f"{NAMESPACE_PREFIX}{slug[:budget]}__{tool}"


def display_label(tool_name: str) -> str | None:
    """`"<server>: <tool>"` for a namespaced MCP tool name, `None` for anything else.

    Lives next to `namespaced()` on purpose: the namespace format gets exactly one owner. This
    is the ERROR_PREFIX lesson applied to a second shared string — a copy of the parsing rule
    somewhere else would drift the moment the format changes.
    """
    if not tool_name.startswith(NAMESPACE_PREFIX):
        return None
    server, sep, tool = tool_name[len(NAMESPACE_PREFIX):].partition("__")
    return f"{server}: {tool}" if sep and server and tool else None


def build_headers(server: models.McpServer) -> dict[str, str]:
    """Extra headers first, so the secret header cannot be shadowed by a stray `headers` entry."""
    headers = {str(k): str(v) for k, v in (server.headers or {}).items()}
    if server.secret:
        headers[server.secret_header or "Authorization"] = f"{server.secret_prefix or ''}{server.secret}"
    return headers


@contextlib.asynccontextmanager
async def connect(server: models.McpServer):
    """Opens an initialized MCP session. `sse` selects the older HTTP+SSE transport, which
    some hosted servers (Linear) still serve instead of Streamable HTTP."""
    headers = build_headers(server)
    if (server.transport or "http") == "sse":
        client = sse_client(server.url, headers=headers, timeout=MCP_CONNECT_TIMEOUT)
    else:
        client = streamablehttp_client(server.url, headers=headers, timeout=MCP_CONNECT_TIMEOUT)
    async with client as streams:
        read, write = streams[0], streams[1]  # streamable_http also yields a session-id getter
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


# ── Result flattening ─────────────────────────────────────────────────────────
# `tools/call` returns a content array plus an `isError` flag, while the registry's handler
# contract is `-> str`. `isError` MUST map to ERROR_PREFIX: the agentic loop decides success
# by testing the result for that prefix, and a drift on one side silently reports failures as
# successes (that regression already happened once — see ARCHITECTURE.md).


def flatten(result) -> str:
    parts: list[str] = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
        else:
            # Images/embedded resources cannot be expressed in a text tool result. Say so
            # rather than dropping them silently, so the model knows something was withheld.
            parts.append(f"[unsupported content block: {getattr(block, 'type', 'unknown')}]")
    body = "\n".join(p for p in parts if p).strip()
    if result.isError:
        return f"{ERROR_PREFIX} {body or 'the tool reported a failure.'}"
    return body or "(the tool returned no content)"


def _handler(server_id: int, tool_name: str):
    """Handler closure. It re-reads the server row per call rather than closing over it: a
    detached ORM instance would go stale after an edit, and the credential must always be the
    current one."""

    async def run(args: dict) -> str:
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            server = db.get(models.McpServer, server_id)
            if server is None or not server.enabled:
                return f"{ERROR_PREFIX} MCP server is no longer available."
            try:
                async with asyncio.timeout(MCP_CALL_TIMEOUT):
                    async with connect(server) as session:
                        return flatten(await session.call_tool(tool_name, args or {}))
            except asyncio.TimeoutError:
                return f"{ERROR_PREFIX} MCP tool '{tool_name}' timed out."
            except Exception as exc:  # noqa: BLE001 — the loop must survive any server fault
                return f"{ERROR_PREFIX} MCP tool '{tool_name}' failed: {type(exc).__name__}: {exc}"
        finally:
            db.close()

    return run


# ── Probe cache ───────────────────────────────────────────────────────────────


@dataclass
class Entry:
    status: str  # "up" | "down" | "disabled"
    error: str | None = None
    tools: list[dict] = field(default_factory=list)  # every discovered tool, with its mode
    at: float = field(default_factory=time.monotonic)


_cache: dict[int, Entry] = {}
_locks: dict[int, asyncio.Lock] = {}


def invalidate(server_id: int) -> None:
    _cache.pop(server_id, None)
    _locks.pop(server_id, None)


def fresh(server_id: int) -> Entry | None:
    entry = _cache.get(server_id)
    if entry is None:
        return None
    ttl = MCP_PROBE_TTL_UP if entry.status == "up" else MCP_PROBE_TTL_DOWN
    return entry if time.monotonic() - entry.at < ttl else None


MODE_OFF, MODE_AUTO, MODE_APPROVE = "off", "auto", "approve"
MODES = (MODE_OFF, MODE_AUTO, MODE_APPROVE)


def _is_read_only(tool) -> bool:
    ann = getattr(tool, "annotations", None)
    return bool(ann and getattr(ann, "readOnlyHint", False))


def default_mode(read_only: bool) -> str:
    """`auto` for read-only, `off` for everything else — an admin must opt a mutating tool in."""
    return MODE_AUTO if read_only else MODE_OFF


def mode_for(server: models.McpServer, tool_name: str, read_only: bool) -> str:
    mode = (server.tool_modes or {}).get(tool_name)
    return mode if mode in MODES else default_mode(read_only)


async def refresh(server: models.McpServer) -> Entry:
    """Connects, lists the tools and re-registers them. Always replaces this server's whole
    tool set (`unregister_source` first) so a tool the server stopped advertising disappears
    instead of lingering as a phantom the model can still call."""
    if not server.enabled:
        registry.unregister_source(source_of(server.id))
        entry = Entry(status="disabled")
        _cache[server.id] = entry
        return entry

    async with _locks.setdefault(server.id, asyncio.Lock()):
        cached = fresh(server.id)
        if cached is not None:
            return cached
        try:
            async with asyncio.timeout(MCP_CONNECT_TIMEOUT):
                async with connect(server) as session:
                    listed = (await session.list_tools()).tools
        except Exception as exc:  # noqa: BLE001 — an unreachable server is a red dot, not a 500
            registry.unregister_source(source_of(server.id))
            entry = Entry(status="down", error=f"{type(exc).__name__}: {exc}")
            _cache[server.id] = entry
            return entry

        registry.unregister_source(source_of(server.id))
        registered: list[dict] = []
        for tool in listed:
            read_only = _is_read_only(tool)
            mode = mode_for(server, tool.name, read_only)
            name = namespaced(server.name, tool.name)
            description = (tool.description or "").strip()
            registered.append({"name": name, "raw_name": tool.name, "description": description,
                               "read_only": read_only, "mode": mode})
            if mode == MODE_OFF:
                # Listed so Settings can switch it on; never registered, so the model is not
                # told it exists.
                continue
            registry.register(
                Tool(
                    name=name,
                    description=description,
                    parameters=tool.inputSchema or {"type": "object", "properties": {}},
                    handler=_handler(server.id, tool.name),
                    source=source_of(server.id),
                    # `approve` rides on the existing mutating gate: the registry then refuses
                    # to run it without an explicit decision, wherever the call comes from.
                    mutating=(mode == MODE_APPROVE),
                )
            )

        entry = Entry(status="up", tools=registered)
        _cache[server.id] = entry
        return entry


async def get(server: models.McpServer, force: bool = False) -> Entry:
    if force:
        invalidate(server.id)
    return (None if force else fresh(server.id)) or await refresh(server)


async def sync_all() -> None:
    """Startup hook: register every enabled server's tools. Best effort — a server that is
    down must not stop the application from booting; it turns into a red dot in Settings and
    is retried on the next probe."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        servers = db.query(models.McpServer).all()
    finally:
        db.close()
    if servers:
        await asyncio.gather(*(refresh(s) for s in servers), return_exceptions=True)
