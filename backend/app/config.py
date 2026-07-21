import os
import secrets

DB_PATH = os.environ.get("DB_PATH", "/data/calivi.db")
SYSTEM_PROMPTS_PATH = os.environ.get("SYSTEM_PROMPTS_PATH", "/config/system_prompts.yml")
SEARCH_CONFIG_PATH = os.environ.get("SEARCH_CONFIG_PATH", "/config/search.yml")
TOOLS_CONFIG_PATH = os.environ.get("TOOLS_CONFIG_PATH", "/config/tools.yml")
# The frontend and /api are served from the same origin (nginx proxy), so CORS never comes
# into play in a normal deployment. This setting only matters when you run the backend
# separately during development (vite dev server on :5173). Leave it empty to allow no
# cross-origin requests at all.
CORS_ORIGINS = [o for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",") if o]


def _load_secret() -> str:
    """SECRET_KEY: use the env var if set, otherwise /data/secret_key (generated and persisted).

    This keeps cookies valid across restarts and keeps the secret out of git.

    The fallback is convenient but writes the key **into the data volume**, next to
    calivi.db — so a copy of that volume (a backup) carries both the data and the key that
    signs sessions, and holding it is enough to forge a session for any user. It now also
    guards the encrypted columns (crypto.py), which makes the volume self-sufficient in a
    second way. Prefer CALIVI_SECRET_KEY from the environment; see the note in README.md.
    """
    env = os.environ.get("CALIVI_SECRET_KEY")
    if env:
        return env
    path = os.path.join(os.path.dirname(DB_PATH) or ".", "secret_key")
    try:
        with open(path, encoding="utf-8") as f:
            val = f.read().strip()
            if val:
                return val
    except FileNotFoundError:
        pass
    val = secrets.token_hex(32)
    with open(path, "w", encoding="utf-8") as f:
        f.write(val)
    return val


# Signs session JWTs (auth.py) and, through a separate derived key, encrypts the secrets
# stored in the database (crypto.py). It lives here rather than in auth.py so that the models
# can reach it without importing the auth layer — `models -> crypto -> auth -> models` would
# be a cycle.
SECRET_KEY = _load_secret()

# Set to the PREVIOUS key during a key rotation: values encrypted under it stay readable and
# are re-encrypted under the current key at startup. Remove it once the app has booted once.
SECRET_KEY_OLD = os.environ.get("CALIVI_SECRET_KEY_OLD", "")

# Bundled SearXNG (the calivi-searxng service in docker-compose). Not exposed externally.
SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://calivi-searxng:8080")

OLLAMA_PROBE_TIMEOUT = 2.0
OLLAMA_CHAT_TIMEOUT = 300.0
OPENAI_PROBE_TIMEOUT = 5.0  # a little longer, since these APIs are remote
SEARCH_TIMEOUT = 15.0  # SearXNG JSON search

# Login brute-force protection — see rate_limit.py. The window is per account.
LOGIN_MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_WINDOW_SECONDS = float(os.environ.get("LOGIN_WINDOW_SECONDS", "900"))  # 15 min

# Registration flood protection — global (no account to key on, and no trustworthy client
# IP: see rate_limit.py). Counts CREATED accounts; failed attempts (duplicates, invalid
# input) are not limited — they reveal nothing and must not eat a legitimate user's quota.
REGISTER_MAX_SUCCESS = int(os.environ.get("REGISTER_MAX_SUCCESS", "10"))
REGISTER_WINDOW_SECONDS = float(os.environ.get("REGISTER_WINDOW_SECONDS", "3600"))  # 1 h

# Server probe cache TTLs (seconds) — see routers/servers.py.
# "down" is shorter so a server you just powered on shows up as "up" quickly.
PROBE_TTL_UP = 60.0
PROBE_TTL_DOWN = 15.0

# MCP (see tools/mcp_client.py).
# The probe is not a ping: it opens a session (initialize → negotiate → tools/list), so it
# is far more expensive than the Ollama one and the TTLs are correspondingly longer —
# otherwise every Settings page refresh would re-handshake every server.
MCP_PROBE_TTL_UP = 300.0
MCP_PROBE_TTL_DOWN = 60.0
MCP_CONNECT_TIMEOUT = 10.0  # handshake + tools/list
MCP_CALL_TIMEOUT = 60.0  # a single tools/call (browser automation can be slow)
# Providers cap tool-name length (OpenAI: 64). Namespacing inflates every MCP tool name, so
# it is enforced rather than hoped for.
MCP_MAX_TOOL_NAME = 64

# Tool approval (human-in-the-loop) — see approvals.py.
# A timeout is a DENIAL: silence must never be read as consent.
APPROVAL_TIMEOUT = 300.0
# Sent while waiting so no proxy sees the stream as stalled — no bytes flow while a person is
# deciding. The binding limit is nginx's `proxy_read_timeout 300s` (frontend/nginx.conf), which
# without pings would land exactly on APPROVAL_TIMEOUT above. Traefik is not the constraint: its
# idleTimeout applies to idle keep-alive connections, not a response in flight.
APPROVAL_HEARTBEAT = 20.0
