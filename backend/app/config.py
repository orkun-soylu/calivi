import os

DB_PATH = os.environ.get("DB_PATH", "/data/calivi.db")
SYSTEM_PROMPTS_PATH = os.environ.get("SYSTEM_PROMPTS_PATH", "/config/system_prompts.yml")
SEARCH_CONFIG_PATH = os.environ.get("SEARCH_CONFIG_PATH", "/config/search.yml")
TOOLS_CONFIG_PATH = os.environ.get("TOOLS_CONFIG_PATH", "/config/tools.yml")
# The frontend and /api are served from the same origin (nginx proxy), so CORS never comes
# into play in a normal deployment. This setting only matters when you run the backend
# separately during development (vite dev server on :5173). Leave it empty to allow no
# cross-origin requests at all.
CORS_ORIGINS = [o for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",") if o]

# Bundled SearXNG (the calivi-searxng service in docker-compose). Not exposed externally.
SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://calivi-searxng:8080")

OLLAMA_PROBE_TIMEOUT = 2.0
OLLAMA_CHAT_TIMEOUT = 300.0
OPENAI_PROBE_TIMEOUT = 5.0  # a little longer, since these APIs are remote
SEARCH_TIMEOUT = 15.0  # SearXNG JSON search

# Login brute-force protection — see rate_limit.py. The window is per account.
LOGIN_MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_WINDOW_SECONDS = float(os.environ.get("LOGIN_WINDOW_SECONDS", "900"))  # 15 min

# Server probe cache TTLs (seconds) — see routers/servers.py.
# "down" is shorter so a server you just powered on shows up as "up" quickly.
PROBE_TTL_UP = 60.0
PROBE_TTL_DOWN = 15.0
