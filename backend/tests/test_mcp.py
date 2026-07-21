"""MCP source adapter: namespacing, the read-only gate, result flattening and CRUD.

No network: `mcp_client.connect` is replaced by a fake session, so everything below exercises
the real refresh/registration/flattening code without a live MCP server.
"""
import contextlib
from types import SimpleNamespace

import pytest

from app import models
from app.config import MCP_MAX_TOOL_NAME
from app.database import SessionLocal
from app.tools import mcp_client
from app.tools.registry import ERROR_PREFIX, registry
from tests.conftest import register


# ── Fakes ─────────────────────────────────────────────────────────────────────


def fake_tool(name, read_only=True, description="d", schema=None):
    return SimpleNamespace(
        name=name,
        description=description,
        inputSchema=schema or {"type": "object", "properties": {}},
        annotations=SimpleNamespace(readOnlyHint=read_only),
    )


def fake_result(text="ok", is_error=False, blocks=None):
    content = blocks if blocks is not None else [SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(content=content, isError=is_error)


class FakeSession:
    def __init__(self, tools, result=None):
        self._tools = tools
        self._result = result or fake_result()
        self.calls = []

    async def list_tools(self):
        return SimpleNamespace(tools=self._tools)

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return self._result


@contextlib.contextmanager
def patched_connect(monkeypatch, session):
    @contextlib.asynccontextmanager
    async def fake_connect(_server):
        yield session

    monkeypatch.setattr(mcp_client, "connect", fake_connect)
    yield session


def make_server(name="ctx7", url="https://example.test/mcp", **kw):
    db = SessionLocal()
    try:
        server = models.McpServer(name=name, url=url, **kw)
        db.add(server)
        db.commit()
        db.refresh(server)
        db.expunge(server)
        return server
    finally:
        db.close()


# ── Namespacing ───────────────────────────────────────────────────────────────


def test_namespacing_uses_underscores_not_dots():
    # Several providers restrict tool names to [a-zA-Z0-9_-]; a dotted separator is rejected.
    name = mcp_client.namespaced("My Server!", "query-docs")
    assert name == "mcp__my_server__query-docs"
    assert "." not in name


def test_namespaced_name_respects_provider_length_cap():
    name = mcp_client.namespaced("a" * 200, "b" * 20)
    assert len(name) <= MCP_MAX_TOOL_NAME
    # The tool name survives intact; the server slug is what gets truncated.
    assert name.endswith("b" * 20)


@pytest.mark.anyio
async def test_same_tool_name_on_two_servers_does_not_clobber(monkeypatch):
    """The bug this guards: the registry is a flat dict and `register()` overwrites silently,
    so two servers exposing `read_file` would collide — and unregistering the loser would then
    delete the winner's tool."""
    a = make_server(name="alpha")
    b = make_server(name="beta")
    with patched_connect(monkeypatch, FakeSession([fake_tool("read_file")])):
        await mcp_client.refresh(a)
        await mcp_client.refresh(b)

    assert registry.get("mcp__alpha__read_file") is not None
    assert registry.get("mcp__beta__read_file") is not None

    # Dropping one server must leave the other's tool untouched.
    registry.unregister_source(mcp_client.source_of(a.id))
    assert registry.get("mcp__alpha__read_file") is None
    assert registry.get("mcp__beta__read_file") is not None


# ── Read-only gate ────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_mutating_tools_default_to_off(monkeypatch):
    """Fail-safe default: an admin has to opt a state-changing tool in, so an upgrade that
    discovers new mutating tools changes nothing."""
    server = make_server()
    tools = [fake_tool("query-docs", read_only=True), fake_tool("create-issue", read_only=False)]
    with patched_connect(monkeypatch, FakeSession(tools)):
        entry = await mcp_client.refresh(server)

    assert entry.status == "up"
    by_name = {t["raw_name"]: t for t in entry.tools}
    assert by_name["query-docs"]["mode"] == "auto"
    assert by_name["create-issue"]["mode"] == "off"
    # Listed for Settings, but the model is not told it exists.
    assert registry.get("mcp__ctx7__create-issue") is None
    assert registry.get("mcp__ctx7__query-docs") is not None


@pytest.mark.anyio
async def test_missing_annotations_are_treated_as_mutating(monkeypatch):
    """Fail-safe: a server that sends no annotations gets nothing registered."""
    tool = SimpleNamespace(
        name="whatever", description="", inputSchema={}, annotations=None
    )
    server = make_server()
    with patched_connect(monkeypatch, FakeSession([tool])):
        entry = await mcp_client.refresh(server)

    assert entry.tools[0]["mode"] == "off"
    assert registry.get("mcp__ctx7__whatever") is None


@pytest.mark.anyio
async def test_approve_mode_registers_the_tool_as_mutating(monkeypatch):
    """`approve` rides on the existing mutating gate — that is what makes the registry refuse
    to run it without a decision, no matter who calls."""
    server = make_server(tool_modes={"create-issue": "approve"})
    with patched_connect(monkeypatch, FakeSession([fake_tool("create-issue", read_only=False)])):
        await mcp_client.refresh(server)

    tool = registry.get("mcp__ctx7__create-issue")
    assert tool is not None
    assert tool.mutating is True
    # ...and it still cannot run without approval.
    assert (await registry.execute(tool.name, {})).startswith(ERROR_PREFIX)
    assert not (await registry.execute(tool.name, {}, approved=True)).startswith(ERROR_PREFIX)


@pytest.mark.anyio
async def test_auto_mode_can_force_a_mutating_tool_to_run_unattended(monkeypatch):
    """An explicit admin choice, and it must be explicit — never a default."""
    server = make_server(tool_modes={"create-issue": "auto"})
    with patched_connect(monkeypatch, FakeSession([fake_tool("create-issue", read_only=False)])):
        await mcp_client.refresh(server)

    assert registry.get("mcp__ctx7__create-issue").mutating is False


@pytest.mark.anyio
async def test_tool_dropped_by_server_disappears_from_registry(monkeypatch):
    server = make_server()
    with patched_connect(monkeypatch, FakeSession([fake_tool("gone"), fake_tool("stays")])):
        await mcp_client.refresh(server)
    assert registry.get("mcp__ctx7__gone") is not None

    mcp_client.invalidate(server.id)
    with patched_connect(monkeypatch, FakeSession([fake_tool("stays")])):
        await mcp_client.refresh(server)
    # A phantom tool the model can still call but the server no longer serves is worse than
    # no tool at all.
    assert registry.get("mcp__ctx7__gone") is None
    assert registry.get("mcp__ctx7__stays") is not None


# ── Result flattening ─────────────────────────────────────────────────────────


def test_flatten_joins_text_blocks():
    result = fake_result(blocks=[SimpleNamespace(type="text", text="a"), SimpleNamespace(type="text", text="b")])
    assert mcp_client.flatten(result) == "a\nb"


def test_flatten_maps_is_error_to_the_shared_error_prefix():
    """The agentic loop decides success by testing for ERROR_PREFIX. A literal that drifts on
    one side reports every failure as a success — that regression already happened once."""
    assert mcp_client.flatten(fake_result("boom", is_error=True)).startswith(ERROR_PREFIX)
    assert "boom" in mcp_client.flatten(fake_result("boom", is_error=True))


def test_flatten_success_never_looks_like_an_error():
    assert not mcp_client.flatten(fake_result("all good")).startswith(ERROR_PREFIX)


def test_flatten_reports_unsupported_blocks_instead_of_dropping_them():
    result = fake_result(blocks=[SimpleNamespace(type="image", data="...")])
    out = mcp_client.flatten(result)
    assert "unsupported content block" in out and "image" in out


def test_flatten_empty_content_is_not_an_error():
    assert not mcp_client.flatten(fake_result(blocks=[])).startswith(ERROR_PREFIX)


# ── Handler ───────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_handler_calls_the_original_unnamespaced_tool(monkeypatch):
    server = make_server()
    session = FakeSession([fake_tool("query-docs")], result=fake_result("docs!"))
    with patched_connect(monkeypatch, session):
        await mcp_client.refresh(server)
        tool = registry.get("mcp__ctx7__query-docs")
        out = await tool.handler({"q": "x"})

    assert out == "docs!"
    # The server knows nothing about our namespace.
    assert session.calls == [("query-docs", {"q": "x"})]


@pytest.mark.anyio
async def test_handler_returns_an_error_string_when_the_server_fails(monkeypatch):
    """The agentic loop must survive a broken MCP server: an error string, never an exception."""
    server = make_server()

    class Boom(FakeSession):
        async def call_tool(self, name, args):
            raise RuntimeError("connection reset")

    with patched_connect(monkeypatch, Boom([fake_tool("query-docs")])):
        await mcp_client.refresh(server)
        out = await registry.get("mcp__ctx7__query-docs").handler({})

    assert out.startswith(ERROR_PREFIX)
    assert "connection reset" in out


@pytest.mark.anyio
async def test_unreachable_server_is_down_not_an_exception(monkeypatch):
    @contextlib.asynccontextmanager
    async def boom(_server):
        raise OSError("no route to host")
        yield  # pragma: no cover

    monkeypatch.setattr(mcp_client, "connect", boom)
    entry = await mcp_client.refresh(make_server())
    assert entry.status == "down"
    assert "no route to host" in entry.error


@pytest.mark.anyio
async def test_disabled_server_registers_nothing(monkeypatch):
    server = make_server(enabled=False)
    with patched_connect(monkeypatch, FakeSession([fake_tool("query-docs")])):
        entry = await mcp_client.refresh(server)
    assert entry.status == "disabled"
    assert registry.get("mcp__ctx7__query-docs") is None


# ── Headers ───────────────────────────────────────────────────────────────────


def test_secret_goes_into_the_configured_header_with_its_prefix():
    github = models.McpServer(
        name="gh", url="u", secret="ghp_x", secret_header="Authorization", secret_prefix="Bearer "
    )
    assert mcp_client.build_headers(github)["Authorization"] == "Bearer ghp_x"

    # Context7 uses a custom header and a raw value — not `Authorization: Bearer`.
    ctx = models.McpServer(name="c", url="u", secret="k", secret_header="CONTEXT7_API_KEY", secret_prefix="")
    assert mcp_client.build_headers(ctx)["CONTEXT7_API_KEY"] == "k"


def test_extra_headers_are_kept_and_cannot_shadow_the_secret():
    server = models.McpServer(
        name="gh",
        url="u",
        secret="tok",
        secret_header="Authorization",
        secret_prefix="Bearer ",
        headers={"X-MCP-Readonly": "true", "Authorization": "attacker"},
    )
    headers = mcp_client.build_headers(server)
    assert headers["X-MCP-Readonly"] == "true"
    assert headers["Authorization"] == "Bearer tok"


def test_no_secret_means_no_auth_header():
    # Context7 works without a key (rate-limited) — an empty secret must not send a bare prefix.
    assert "Authorization" not in mcp_client.build_headers(models.McpServer(name="c", url="u"))


# ── CRUD / API ────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_mcp_routes_are_admin_only(admin, user_client, monkeypatch):
    await register(user_client, "bob")
    cases = [
        ("GET", "/api/mcp", None),
        ("POST", "/api/mcp", {"name": "x", "url": "https://a.test/mcp"}),
        ("PATCH", "/api/mcp/1", {"name": "x"}),
        ("DELETE", "/api/mcp/1", None),
    ]
    for method, url, body in cases:
        resp = await user_client.request(method, url, json=body)
        assert resp.status_code == 403, f"{method} {url} → {resp.status_code}"


@pytest.mark.anyio
async def test_create_never_returns_the_secret(admin, monkeypatch):
    with patched_connect(monkeypatch, FakeSession([fake_tool("query-docs")])):
        resp = await admin.post(
            "/api/mcp",
            json={"name": "ctx7", "url": "https://example.test/mcp", "secret": "s3cret"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["has_secret"] is True
    assert "secret" not in body
    assert "s3cret" not in resp.text


@pytest.mark.anyio
async def test_patch_without_secret_preserves_it(admin, monkeypatch):
    with patched_connect(monkeypatch, FakeSession([fake_tool("query-docs")])):
        created = (await admin.post(
            "/api/mcp", json={"name": "ctx7", "url": "https://example.test/mcp", "secret": "keepme"}
        )).json()
        resp = await admin.patch(f"/api/mcp/{created['id']}", json={"name": "renamed"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["has_secret"] is True
    db = SessionLocal()
    try:
        assert db.get(models.McpServer, created["id"]).secret == "keepme"
    finally:
        db.close()


@pytest.mark.anyio
async def test_rename_moves_the_tool_namespace(admin, monkeypatch):
    with patched_connect(monkeypatch, FakeSession([fake_tool("query-docs")])):
        created = (await admin.post(
            "/api/mcp", json={"name": "ctx7", "url": "https://example.test/mcp"}
        )).json()
        assert registry.get("mcp__ctx7__query-docs") is not None
        await admin.patch(f"/api/mcp/{created['id']}", json={"name": "context7"})

    # Stale names under the old namespace would stay callable forever otherwise.
    assert registry.get("mcp__ctx7__query-docs") is None
    assert registry.get("mcp__context7__query-docs") is not None


@pytest.mark.anyio
async def test_duplicate_name_is_rejected(admin, monkeypatch):
    with patched_connect(monkeypatch, FakeSession([fake_tool("t")])):
        await admin.post("/api/mcp", json={"name": "dup", "url": "https://a.test/mcp"})
        resp = await admin.post("/api/mcp", json={"name": "dup", "url": "https://b.test/mcp"})
    # Duplicate names would produce colliding tool namespaces.
    assert resp.status_code == 409


@pytest.mark.anyio
async def test_delete_unregisters_the_tools(admin, monkeypatch):
    with patched_connect(monkeypatch, FakeSession([fake_tool("query-docs")])):
        created = (await admin.post(
            "/api/mcp", json={"name": "ctx7", "url": "https://example.test/mcp"}
        )).json()
        assert registry.get("mcp__ctx7__query-docs") is not None
        resp = await admin.delete(f"/api/mcp/{created['id']}")

    assert resp.status_code == 204
    # Without this the deleted server's tools stay callable until the next restart.
    assert registry.get("mcp__ctx7__query-docs") is None


# ── Per-tool enable/disable ───────────────────────────────────────────────────


@pytest.mark.anyio
async def test_off_tool_is_listed_but_not_registered(monkeypatch):
    """Turning a tool off must hide it from the model, yet keep it visible in Settings so it
    can be turned back on — a tool that vanishes from the UI cannot be re-enabled."""
    server = make_server(tool_modes={"create-note": "off"})
    tools = [fake_tool("query-docs"), fake_tool("create-note")]
    with patched_connect(monkeypatch, FakeSession(tools)):
        entry = await mcp_client.refresh(server)

    by_name = {t["raw_name"]: t for t in entry.tools}
    assert by_name["query-docs"]["mode"] == "auto"
    assert by_name["create-note"]["mode"] == "off"
    assert registry.get("mcp__ctx7__query-docs") is not None
    assert registry.get("mcp__ctx7__create-note") is None


@pytest.mark.anyio
async def test_switching_a_tool_back_on_registers_it_again(monkeypatch, admin):
    with patched_connect(monkeypatch, FakeSession([fake_tool("query-docs")])):
        created = (await admin.post(
            "/api/mcp", json={"name": "ctx7", "url": "https://example.test/mcp",
                              "tool_modes": {"query-docs": "off"}}
        )).json()
        assert registry.get("mcp__ctx7__query-docs") is None

        resp = await admin.patch(f"/api/mcp/{created['id']}", json={"tool_modes": {}})

    assert resp.status_code == 200, resp.text
    assert registry.get("mcp__ctx7__query-docs") is not None


@pytest.mark.anyio
async def test_tool_modes_survive_a_round_trip(admin, monkeypatch):
    with patched_connect(monkeypatch, FakeSession([fake_tool("t")])):
        created = (await admin.post(
            "/api/mcp", json={"name": "ctx7", "url": "https://example.test/mcp",
                              "tool_modes": {"t": "approve"}}
        )).json()
    assert created["tool_modes"] == {"t": "approve"}


@pytest.mark.anyio
async def test_an_unknown_mode_falls_back_to_the_safe_default(monkeypatch):
    """A hand-edited or corrupted value must not become an accidental grant."""
    server = make_server(tool_modes={"create-issue": "yes-please"})
    with patched_connect(monkeypatch, FakeSession([fake_tool("create-issue", read_only=False)])):
        entry = await mcp_client.refresh(server)
    assert entry.tools[0]["mode"] == "off"
    assert registry.get("mcp__ctx7__create-issue") is None


@pytest.mark.anyio
async def test_tool_out_carries_the_raw_name(monkeypatch):
    """The UI toggles tools by their server-side name. Sending it avoids a second parser for
    the namespace format in JavaScript — mcp_client stays its only owner."""
    server = make_server()
    with patched_connect(monkeypatch, FakeSession([fake_tool("query-docs")])):
        entry = await mcp_client.refresh(server)
    assert entry.tools[0]["raw_name"] == "query-docs"
    assert entry.tools[0]["name"] == "mcp__ctx7__query-docs"
