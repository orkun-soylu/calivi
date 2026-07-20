"""Test environment and shared fixtures.

CAREFUL — environment ordering: `app.config` / `app.auth` / `app.database` read the
environment at module level (engine from DB_PATH, SECRET_KEY, config file paths). The
environment must therefore be set up **before `app` is imported**. pytest imports
conftest.py before the test modules, which makes this the right place; do not move the
`import app...` lines above the environment block.
"""
import os
import tempfile

TMP = tempfile.mkdtemp(prefix="calivi-tests-")

os.environ["DB_PATH"] = os.path.join(TMP, "test.db")
os.environ["CALIVI_SECRET_KEY"] = "test-secret-key"  # keeps it from writing /data/secret_key
os.environ["COOKIE_SECURE"] = "false"  # httpx will not send Secure cookies to http://testserver
os.environ["SYSTEM_PROMPTS_PATH"] = os.path.join(TMP, "system_prompts.yml")
os.environ["VISION_OVERRIDES_PATH"] = os.path.join(TMP, "vision_models.yml")
os.environ["SEARCH_CONFIG_PATH"] = os.path.join(TMP, "search.yml")
os.environ["TOOLS_CONFIG_PATH"] = os.path.join(TMP, "tools.yml")

import httpx  # noqa: E402
import pytest  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app import ollama_client  # noqa: E402
from app.routers import auth as auth_router  # noqa: E402
from app.routers import servers as servers_router  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    """Every test starts with an empty DB (ids from 1 — the super admin rule depends on id)."""
    import app.models  # noqa: F401  registers the models on Base

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    # Module-level state must not leak between tests (it lives for the whole process).
    servers_router._cache.clear()
    servers_router._locks.clear()
    ollama_client._vision_cache.clear()  # never expires — a leak would keep a stale vision verdict
    auth_router.login_limiter.clear()
    yield


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def register(client: httpx.AsyncClient, username: str, password: str = "password123"):
    """Signs up and leaves the session cookie on the client. First sign-up → id 1, super admin."""
    resp = await client.post(
        "/api/auth/register",
        json={"email": f"{username}@test.local", "username": username, "password": password},
    )
    assert resp.status_code < 400, resp.text
    return resp.json()


async def login(client: httpx.AsyncClient, username: str, password: str = "password123"):
    return await client.post("/api/auth/login", json={"identifier": username, "password": password})


@pytest.fixture
async def admin(client):
    """id 1 = super admin (first sign-up). The returned client carries their session."""
    await register(client, "admin")
    return client


@pytest.fixture
async def user_client():
    """A second client with its own cookie jar (for a regular user's session)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
