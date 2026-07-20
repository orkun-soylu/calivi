"""Server probe cache (routers/servers.py) — TTL, invalidation, single-flight.

The frontend calls /api/servers every 3s; without this cache every request probes all
servers live (a full timeout for each offline one).
"""
import asyncio

import pytest

from app import llm
from app.routers import servers as S


class FakeServer:
    """Minimal stand-in for models.Server (the fields _spec reads, plus id/name)."""

    def __init__(self, id=1, host="host", port=11434, name="s", type="ollama", base_url=None, api_key=None):
        self.id, self.host, self.port, self.name = id, host, port, name
        self.type, self.base_url, self.api_key = type, base_url, api_key


@pytest.fixture
def probe(monkeypatch):
    """Replaces llm.probe with a counter; drive up/down through `probe.status`."""

    class Probe:
        def __init__(self):
            self.count = 0
            self.status = "up"

        async def __call__(self, spec):
            self.count += 1
            # The model name carries the host → a stale result is caught even without the counter
            return self.status, [f"m@{spec['host']}"]

    p = Probe()
    monkeypatch.setattr(llm, "probe", p)
    monkeypatch.setattr(llm, "model_capabilities", lambda spec, names: _all_live(names))
    return p


async def _all_live(names):
    """(live, vision) — this suite does not exercise liveness filtering, so let everything through."""
    return list(names), []


async def test_second_request_comes_from_cache(probe):
    s = FakeServer()
    await S._build_out(s)
    await S._build_out(s)
    assert probe.count == 1


async def test_refresh_bypasses_the_cache(probe):
    s = FakeServer()
    await S._build_out(s)
    await S._build_out(s, refresh=True)
    assert probe.count == 2


async def test_changing_server_settings_forces_a_reprobe(probe):
    """Even if we miss the PATCH, the spec comparison prevents a stale result."""
    s = FakeServer()
    await S._build_out(s)
    s.host = "new-host"
    await S._build_out(s)
    assert probe.count == 2


async def test_down_entries_expire_on_the_short_ttl(probe):
    """The down TTL is short so a server you just powered on shows as \'up\' quickly."""
    probe.status = "down"
    s = FakeServer()
    await S._build_out(s)
    S._cache[s.id].at -= S.PROBE_TTL_DOWN + 1
    await S._build_out(s)
    assert probe.count == 2


async def test_up_entries_survive_the_down_ttl(probe):
    s = FakeServer()
    await S._build_out(s)
    S._cache[s.id].at -= S.PROBE_TTL_DOWN + 1
    await S._build_out(s)
    assert probe.count == 1

    S._cache[s.id].at -= S.PROBE_TTL_UP + 1
    await S._build_out(s)
    assert probe.count == 2


async def test_single_flight_merges_concurrent_requests(probe):
    """Many tabs/users missing at once must share a single probe."""
    s = FakeServer()
    await asyncio.gather(*(S._build_out(s) for _ in range(10)))
    assert probe.count == 1


async def test_a_reused_id_does_not_leak_the_old_result(probe):
    """The servers table is NOT sqlite_autoincrement → ids can be handed out again."""
    await S._build_out(FakeServer(id=1, host="old"))
    S._invalidate(1)
    await S._build_out(FakeServer(id=1, host="new"))
    assert probe.count == 2


async def test_a_cached_response_returns_the_same_content(probe):
    s = FakeServer(host="h1")
    first = await S._build_out(s)
    second = await S._build_out(s)
    assert (first.status, first.models) == (second.status, second.models) == ("up", ["m@h1"])


async def test_cache_works_through_the_endpoint(admin, probe):
    """Including the HTTP layer: two GETs → one probe, ?refresh=1 → another."""
    await admin.post("/api/servers", json={"name": "s", "host": "127.0.0.1", "port": 1})
    after = probe.count  # the POST does its own probe

    await admin.get("/api/servers")
    await admin.get("/api/servers")
    assert probe.count == after  # both served from cache

    await admin.get("/api/servers?refresh=1")
    assert probe.count == after + 1


async def test_endpoint_does_not_show_stale_data_for_a_reused_id(admin, probe):
    """End to end: when an id is reused the list must not show the OLD server\'s result.

    That guarantee really comes from the spec comparison in `_fresh()` (the `_invalidate` in
    DELETE is hygiene on top — see the test below). Removing both would break this.
    """
    old = (await admin.post("/api/servers", json={"name": "old", "host": "10.0.0.1", "port": 1})).json()
    await admin.get("/api/servers")  # populate the cache

    await admin.delete(f"/api/servers/{old['id']}")
    new = (await admin.post("/api/servers", json={"name": "new", "host": "10.0.0.2", "port": 1})).json()
    assert new["id"] == old["id"], "if the id was not reused this test\'s premise is void"

    assert (await admin.get("/api/servers")).json()[0]["models"] == ["m@10.0.0.2"]


async def test_deleted_servers_do_not_pile_up_in_the_cache(admin, probe):
    """Without `_invalidate` the entries of deleted servers would accumulate forever."""
    srv = (await admin.post("/api/servers", json={"name": "s", "host": "10.0.0.9", "port": 1})).json()
    assert srv["id"] in S._cache

    await admin.delete(f"/api/servers/{srv['id']}")
    assert srv["id"] not in S._cache and srv["id"] not in S._locks


async def test_patch_always_probes_live(admin, probe):
    srv = (await admin.post("/api/servers", json={"name": "s", "host": "127.0.0.1", "port": 1})).json()
    after = probe.count

    await admin.patch(f"/api/servers/{srv['id']}", json={"name": "new-name"})
    assert probe.count == after + 1
