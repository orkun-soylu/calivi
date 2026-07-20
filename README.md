# calivi

A self-hosted, multi-user chat interface for Ollama and OpenAI-compatible servers.
You pick which model runs where — no hidden routing.

Your own GPU box, Ollama Cloud, OpenRouter, Moonshot, LM Studio, vLLM,
llama.cpp-server — all from the same chat window.

```
┌──────────────┐     ┌──────────────┐     ┌────────────────────────┐
│   Browser    │────▶│ nginx (:8090)│────▶│ FastAPI backend        │
└──────────────┘     │  SPA + /api  │     │  SQLite · tool loop    │
                     └──────────────┘     └───────────┬────────────┘
                                                      │
                                  ┌───────────────────┼───────────────────┐
                                  ▼                   ▼                   ▼
                            Ollama servers    OpenAI-compatible     SearXNG (bundled)
                            (LAN / remote)    API (cloud / local)   web search
```

---

## Highlights

- **Multi-server, manual selection** — You choose the server and model from the top bar;
  no automatic routing. Only reachable (`up`) servers appear in the picker.
- **Two server types** — `ollama` (native `/api/chat`) and `openai` (OpenAI-compatible
  `/v1/chat/completions`). One interface drives both.
- **Streaming with reasoning** — Responses stream in; reasoning models' thinking tokens
  are shown in a separate box. Interrupt with the **Stop** button or **Esc** (whatever
  was generated so far is kept).
- **Multi-user** — httpOnly cookie + JWT sessions, admin/user roles. Each user sees only
  their own chats. Registration can be closed by an admin.
- **Vision** — Send images to vision-capable models, including paste-from-clipboard and a
  full-screen viewer (lightbox).
- **Document attachments** — PDF / docx / txt / code / csv / json are extracted as
  **text** and handed to the model (lossless text, not OCR).
- **Web search (tool)** — Bundled SearXNG. The model calls the tool *on its own
  initiative*; which tool ran is visible in the conversation.
- **Message editing** — Edit a message and either **Update** (regenerate from that point,
  optionally on a different model) or **New chat** (branch while keeping history).
- **Markdown + math** — Code blocks with copy buttons, tables, KaTeX.
- **9 languages** — TR, EN, DE, ES, IT, PT, RU, JA, ZH.
- **Light/dark theme** with a selectable accent color.

---

## Installation

**Requirements:** Docker and Docker Compose. Nothing else.

```bash
git clone <repo-url> calivi
cd calivi
docker compose up -d --build
```

Open **http://localhost:8090** (or the host's LAN address: `http://192.168.x.x:8090`).

> **The first person to sign up becomes the admin.** Create the first account from the
> registration screen — it is the **super admin** (id 1) and cannot be deleted or
> demoted. Later sign-ups become regular users; you can close registration entirely
> under Settings → General.

### Adding a server

Settings (⚙) → **Servers** → use the form at the bottom:

| Type | Fields | Example |
|---|---|---|
| `ollama` | host + port | `192.168.1.50` : `11434` |
| `openai` | base URL + API key | `https://openrouter.ai/api/v1` |

The model list is fetched automatically (`/api/tags` or `/v1/models`). A green light on
the row means the server is reachable; red servers are hidden from the chat picker.

> **Ollama must be reachable over the network.** By default Ollama listens only on
> `127.0.0.1`. To reach it from another machine, run it with `OLLAMA_HOST=0.0.0.0`.

### Configuration (environment variables)

Everything has a sensible default. To override, create a `.env` file in the project root
(Compose reads it automatically):

```bash
# .env
CALIVI_PORT=8090        # exposed port
COOKIE_SECURE=false     # set to true behind HTTPS — see the warning below
```

Other variables the backend understands (`backend/app/config.py`): `DB_PATH`,
`SYSTEM_PROMPTS_PATH`, `TOOLS_CONFIG_PATH`, `SEARXNG_URL`, `CORS_ORIGINS`,
`LOGIN_MAX_ATTEMPTS`, `LOGIN_WINDOW_SECONDS`.

> ### ⚠️ Putting it behind HTTPS: set `COOKIE_SECURE=true`
> This Compose file serves plain HTTP, so the default is `false`. If you put Calivi
> behind a TLS-terminating reverse proxy (Traefik, Caddy, nginx…), **set it to `true`** —
> otherwise the session cookie is sent without the `Secure` flag.
>
> The opposite is a trap too: with `true` over plain HTTP the browser refuses to send the
> cookie and **login fails silently**. Most browsers treat `http://localhost` as
> privileged, so this can work on localhost and then break from a LAN address.

---

## Configuration files

The YAML files under `config/` are mounted into the container and re-read on every
request — **no restart needed**. Most are also editable from the Settings UI.

| File | Purpose |
|---|---|
| `config/system_prompts.yml` | Per-model system prompts (the `default` key is the fallback) — **not in git**, see below |
| `config/tools.yml` | Tool (function-calling) layer: on/off, loop cap, `web_search` options |
| `config/vision_models.yml` | Manual overrides for vision detection (`force_vision` / `force_text`) |
| `searxng/settings.yml` | Bundled SearXNG. No port is exposed; change `secret_key` if you expose it publicly |

`config/system_prompts.yml` is **git-ignored**: system prompts tend to name your own
hardware and models, and they are the one config that is genuinely personal. Start from
the example:

```bash
cp config/system_prompts.example.yml config/system_prompts.yml
```

Running without it is fine too — no system message is sent, and the Settings →
System Prompts editor creates the file when you first save. The "Default" button in that
editor restores the factory defaults from `backend/app/defaults/system_prompts.yml`.

---

## Backups

All user data (`calivi.db` plus the session signing key) lives in a named volume called
`calivi-data` — not a bind mount.

```bash
docker compose stop calivi-backend
VOL=$(docker volume inspect calivi_calivi-data --format '{{.Mountpoint}}')
sudo tar czf calivi-backup-$(date +%F).tar.gz --numeric-owner -C "$VOL" .
docker compose start calivi-backend
```

Use `--numeric-owner` when restoring: `calivi.db` and `secret_key` belong to different
users.

---

## Development

```bash
# Frontend (vite dev server on :5173)
cd frontend && npm install && npm run dev
npm test                    # vitest + jsdom

# Backend
cd backend
python3 -m venv .venv-test && ./.venv-test/bin/pip install -r requirements-dev.txt
./.venv-test/bin/pytest     # real HTTP layer (httpx ASGITransport), no live server needed
./.venv-test/bin/uvicorn app.main:app --reload --port 8000
```

When the backend runs separately, the frontend is served from a different origin
(`:5173`), so `CORS_ORIGINS` comes into play — it already defaults to
`http://localhost:5173`.

**See `CLAUDE.md` for architecture, design decisions and known pitfalls** — the component
map, tool loop, security notes and "don't fall into this again" warnings live there.

---

## Built with

**Backend:** FastAPI · SQLAlchemy · SQLite · httpx · PyJWT · bcrypt
**Frontend:** React · Vite · Tailwind · react-markdown · KaTeX
**Deployment:** Docker Compose (backend + nginx/frontend + SearXNG)

---

## Security

Calivi is designed as a single-tenant application running on your own network. Before
exposing it directly to the internet, know that:

- Web search results and document attachments are treated as **untrusted content** and
  passed to the model inside delimited blocks (prompt-injection defence).
- The frontend is served with a strict Content-Security-Policy; remote images in model
  output are not fetched (a data-exfiltration vector).
- Login attempts are rate-limited per account (default: 5 attempts / 15 minutes).
- The tool layer is currently **read-only** — state-changing tools are rejected.

---

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

Commits must be signed off under the [DCO](DCO) (`git commit -s`). There is no CLA.

## License

[MIT](LICENSE) © 2026 Orkun Soylu

Icons by [Lucide](https://lucide.dev) (ISC). Typeface: JetBrains Mono Nerd Font
(SIL OFL 1.1). Full attribution for bundled third-party assets is in
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
