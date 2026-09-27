# Changelog

Notable changes to Calivi, newest first.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions are
[SemVer](https://semver.org/spec/v2.0.0.html), with the caveat that the major version is `0`:
**while it stays there, anything may change between releases**, including the database schema.
Read this file before upgrading.

## [Unreleased]

### Added

- The Debian package is built for **Ubuntu 24.04 LTS and 26.04 LTS** as well as Debian 13
  (#95): one build per distribution, since each has its own Python (3.12, 3.14, 3.13).

### Changed

- Dependencies updated for Python 3.14: SQLAlchemy 2.0.54, pydantic 2.13.5, uvloop 0.22.1,
  httptools 0.8.0, PyYAML 6.0.3.

## [0.6.0] — 2026-09-27

calivi-vm becomes updatable. Calivi now ships as a Debian package too, attached to each release
as `calivi_X.Y.Z-1_amd64.deb`, so a VM updates in place with `apt install` — including one
from an older image — and an update waits for a running reply instead of cutting it.

> **Upgrading a calivi-vm:** download the `.deb` from this release and `sudo apt install
> ./calivi_0.6.0-1_amd64.deb`. Your chats and settings in `/var/lib/calivi` stay. Docker
> installs: nothing to do; no schema change.

### Added

- **calivi-vm updates as a Debian package** (#95). `packaging/build-deb.sh` builds
  `calivi_X.Y.Z-N_amd64.deb`, to be attached to releases. `apt install ./calivi_….deb` updates a
  VM — including one from an older image — without touching its chats. The restart waits for a
  running reply to finish. A signed APT repository comes next.

### Changed

- calivi-vm paths follow Debian: the bootstrap helper is `/usr/sbin/calivi-bootstrap-user`, and
  the units and first-boot script live under `/usr/lib`. Installing the package migrates older
  images.

## [0.5.0] — 2026-09-27

Agent mode. On calivi-vm a chat now works like a coding agent's session: the model remembers
the commands it ran and what they printed, and the reply shows each step with its output and
its approval. Normal installs keep plain chats.

> **Upgrading:** two columns are added on startup (`chats.mode`, default `chat`, and
> `messages.steps`). Existing chats stay plain chats; on calivi-vm, new chats start in agent
> mode and an existing one can be switched from the chat header.

### Added

- **Agent mode** (#91), the default for new chats on calivi-vm. A reply's tool steps are kept:
  the model remembers what it ran and what came back on later turns, instead of only its own
  summary. The steps show as a timeline in the reply — each command with its status, and its
  output one click away. An approval card appears in the step it belongs to, live and after a
  reload. A toggle in the chat header switches a chat between agent and plain chat. Chats on
  a normal install stay plain chats.

### Fixed

- Re-attaching to a running reply (after a reload or a chat switch) could show its text, or
  its steps, twice.
- One unreachable MCP server could make every MCP server show as unreachable, so the model got
  no MCP tools at all. Slow-failing DNS lookups filled uvloop's 4-thread resolver pool and the
  other servers' probes timed out waiting behind them. The pool is now 64 threads, in the Docker
  image and the calivi-vm service alike.

## [0.4.0] — 2026-09-27

Replies that outlive the tab. A reply now runs on the server, so closing the tab, reloading,
losing the connection or switching chats no longer stops it — and opening the chat again picks
it up where it is. This is what calivi-vm needed for long, multi-step jobs, and it applies to
every install.

> **Upgrading:** no schema change. **Closing the tab no longer stops a reply — Stop (or Esc)
> does.** A reply that is running when the backend restarts is lost, as before.

### Changed

- **A reply keeps running when you close the tab** (#85). It runs on the server as a background
  task. Reloading, switching chats or reopening Calivi on another device re-attaches to it —
  pending approval cards included. **Closing the tab no longer stops a reply: use Stop (or
  Esc).** While a reply is running, sending, editing, deleting a message and compacting in that
  chat are refused (409).

### Fixed

- **Settings, the sign-in screen and user management in German, Spanish, Italian, Portuguese,
  Russian, Japanese and Chinese.** 43 texts were missing in each of those seven languages and
  fell back to Turkish. They are translated now, and a test fails if any language is missing a
  key, has an empty text or drops a `{variable}`.

## [0.3.0] — 2026-09-27

calivi-vm. A Proxmox image that boots straight into Calivi and lets the chat model **operate
the VM it runs on**: bash, file reads, writes and edits, behind approval cards for anything
destructive. The same release adds the approval machinery that makes this safe to hand to a
model. A normal `docker compose` install behaves as before; everything host-related is off
unless `CALIVI_HOST_TOOLS=1`.

> **Upgrading:** no schema change. `/api/auth/me`, `/login` and `/register` return one more
> field (`host_tools`), and `/api/auth/config` returns `host_setup`. Both are always `false`
> outside calivi-vm.

### Added

- **calivi-vm** (#78, #83): `appliance/` builds a Proxmox-ready qcow2 (Debian 13, Calivi
  installed natively on :80, standard kernel so a passed-through GPU gets its drivers), and
  `proxmox-create.sh` creates the VM (q35 + OVMF, ready for passthrough). The session key and a
  setup code are generated on each VM's first boot, never in the image, and the console shows
  the address and the code. See [`appliance/README.md`](appliance/README.md).
- **Host tools** (#80): `bash`, `read_file`, `write_file`, `edit_file`, run as the machine
  owner's Linux account. Destructive or access-cutting commands (`rm`, `mv`, `dd`,
  `systemctl stop`, firewall changes, `| sh`, writes into system paths, …) ask first. A few
  (`rm -rf /`, the fork bomb) are refused outright. Writes outside home ask. Commands time out
  (120s default); a job left in the background does not hold the call open.
- **Claiming the machine** (#82): on calivi-vm the first registration needs the setup code from
  the console and also creates a Linux account with the same name and password, in `sudo`, with
  optional hostname, timezone and SSH key. Registration then closes. A single root helper, the
  service account's only sudo rule, does the work and re-validates everything it is given.
- **"Ask before every tool"** (#81): a 🛡 toggle next to 🔧 that puts every tool call behind an
  approval card. It is shown only to the calivi-vm owner.
- **Per-call approval and owner-only tools** (#79): a tool can decide per call whether it
  needs approval, and a tool can be restricted to the super admin, for whom alone it exists.
- **Setup prompt for coding agents** — [calivi.ai/prompt](https://calivi.ai/prompt) carries one
  prompt (`docs/setup-prompt.txt`) that has Claude Code, Codex or any coding agent install,
  configure and verify Calivi, then hand back the URL. It preserves an existing install's
  `.env`, volume and secret key, and leaves the first (admin) sign-up to you.

### Changed

- `max_iterations` in `tools.yml` accepts up to 200 (was 20). Operating a machine takes far
  more tool calls than a documentation lookup. The default is unchanged.
- A tool call refused for lack of approval now says so, rather than claiming the call
  "changes state".

## [0.2.0] — 2026-09-26

Long chats and phones. A chat can now be compacted so a long conversation stops re-sending its
whole history on every turn, and below 768px Calivi switches to a phone layout. The heavy-
development caveat from 0.1.0 still applies — run it with backups.

> **Upgrading:** three columns are added to `chats` on startup (`summary`, `summary_upto_id`,
> `context_mode`). Existing chats behave exactly as before until you compact one.

### Added

- Conversation compaction (#62). A long chat can now be compacted: older messages are
  summarised by the model you pick, and from then on the model gets that summary plus the last
  few turns instead of the whole history — so a long chat no longer has to be fully re-processed
  after a restart. The messages themselves stay in the chat. Compaction only happens when you
  ask for it; past an estimated size (`COMPACT_SUGGEST_TOKENS`, default 16000) the chat suggests
  it. A switch sends the full history again whenever a detail matters, and "View summary" shows
  exactly what the model is working from. Editing or deleting a summarised message drops the
  summary. New columns on `chats` are added automatically on startup.
- A phone layout (#61). Below 768px the chat list and the open chat are separate full-screen
  views: tap a chat to open it, and the back button — or your phone's back gesture — returns to
  the list. Message bubbles use more of the width, the model pickers shrink to fit, and Settings
  opens full screen. The desktop layout is unchanged.
- When a model calls a tool by a name that does not exist but matches exactly one registered
  tool once the namespace is dropped (`scan_packages` for `mcp__cve__scan_packages`), the error
  returned to the model now names the real tool, so its next attempt can succeed. The tool is not
  run on the guess.
- A favicon, so the browser tab shows the Calivi mark instead of a blank page icon. It is the
  same mark the calivi.ai landing page uses.
- `OLLAMA_CHAT_TIMEOUT` is now configurable via environment variable (seconds, default `300`,
  unchanged). The old hard-coded value silently dropped very large prompts: it caps the silence
  between stream chunks, and prompt processing produces none, so a prompt big enough to prefill
  for over five minutes timed out before the model had said anything — with no hint that its
  size was the cause. Large-context setups can now raise it.

### Fixed

- When a model called the same MCP tool more than once in one answer with different arguments,
  only the first call left a chip, so the output of the later call — often the one the answer
  relied on — could not be opened after a reload. Each distinct call now keeps its own chip, and
  MCP chip labels show a short summary of the arguments. Exact repeats still collapse into one.
- The stdio bridge image no longer breaks on a fresh build. `mcp-server-time` was pinned but its
  `mcp` dependency was not, so a rebuild picked up `mcp` 2.x, which renamed `McpError` to
  `MCPError`: the server died on import and the proxy restarted in a loop with "Connection
  closed". The server's venv now installs `mcp<2`.
- Scrolling up to read a long answer while it was still streaming no longer snaps back to the
  bottom on every new token. The chat now follows new output only while you are at the bottom;
  scroll up and it stays where you left it, scroll back down and it follows again. Sending a
  message or opening a chat still takes you to the end.
- When a tool-using answer hit the `max_iterations` cap, the model could reply with a tool call
  written out as text (for example `<…:function_calls>` markup) instead of an answer, and that
  markup was saved as the reply. The last turn already ran without tools; it now also tells the
  model so — no tools left, answer from the results gathered, do not write tool calls.

### Security

- Dependency updates for published advisories. Dependabot's grouped pull requests for these left
  the dependencies uninstallable — Starlette 1.x needs a newer FastAPI, and Vite 8 needs a newer
  React plugin — so the fixes land here as a set that resolves and passes the tests:
  - **Backend:** FastAPI 0.115.6 → 0.141.1 with Starlette 0.41.3 → 1.3.1 (7 advisories, among them
    a denial of service through large multipart uploads, which the document upload uses), and
    PyJWT 2.10.1 → 2.13.0 (7 advisories; sessions are HS256 with a server-side secret, so the
    JWK and key-confusion ones do not apply, while the unbounded-decoding denial of service does).
  - **Test tooling:** pytest 8.3.4 → 9.0.3 and pytest-asyncio 0.25.0 → 1.4.0 (the old plugin pins
    pytest below 9). The test JWT secret is now 48 bytes, since PyJWT 2.13 warns below 32.
  - **Frontend build:** PostCSS → 8.5.28. Vite is back on 6.4.3, which has no open advisory: the
    grouped update had moved it to 8 without the React plugin that supports 8, so `npm ci`
    failed. Moving to Vite 8 is left for a separate change.

## [0.1.0] — 2026-07-22

The first tagged release. Everything below already worked before this tag; it marks a point
someone can install and stay on, instead of tracking `main`.

> **Heavy development.** Things break between commits, defaults change, and security holes get
> found and closed as the code moves. There is no stable channel yet and no versioned upgrade
> path — a migration is not guaranteed to leave an existing database untouched. Run it with
> backups. `0.1.0` is a starting line, not a stability promise.

### Added — chat and routing

- Self-hosted, multi-user chat for **Ollama** (native `/api/chat`) and any **OpenAI-compatible**
  server (`/v1/chat/completions`), through one interface.
- Server and model chosen from the top bar **per message**. Only servers that answered their last
  probe appear in the picker.
- Streaming replies, with reasoning models' thinking in a separate pane. Stop with the button or
  `Esc`; whatever streamed so far is kept.
- Retired cloud models are filtered out of the picker, so a model that died upstream cannot be
  selected into a broken chat.

### Added — control over a conversation

- Every reply stores the **model**, the **server** and the **tokens/sec** that produced it, so a
  chat reopened later still says what answered, where, and how fast.
- Delete a message to walk the conversation back.
- Edit a message and either regenerate from that point — optionally on a different model — or
  fork into a new chat, keeping the history intact.
- Copy a single answer, or the whole conversation, to the clipboard in one click.

### Added — tools, web search, MCP

- A tool layer behind one composer toggle. The model calls tools on its own initiative, and which
  tool ran stays visible in the conversation across reloads.
- Bundled **SearXNG** for web search — no external service, no API key.
- **MCP** servers over Streamable HTTP or HTTP+SSE, with presets for Context7, GitHub and Exa.
  Individual tools can be switched off without removing the server.
- Tool output is inspectable: every call opens its raw response, stored with the message.

### Added — safety

- **Approval before anything changes.** Read-only tools run on their own; anything that can change
  state is off until enabled, and then asks before every single run. Silence is a denial, never
  consent.
- **stdio MCP servers run in a separate sandboxed container** — its own `internal` network with no
  internet and no LAN, non-root, read-only filesystem, all capabilities dropped, no published
  port. Servers are pinned into the image rather than fetched at call time.
- **Secrets encrypted at rest.** Provider API keys and MCP tokens are encrypted in the database,
  so a copy of it is not a copy of your credentials.
- Brute-force protection on login, per-user chat isolation, and a super admin that cannot be
  demoted or deleted.

### Added — content

- Vision: images to vision-capable models, including paste-from-clipboard, with a full-screen
  viewer.
- Documents: PDF / docx / txt / code / csv / json extracted as **text** (not OCR) and handed to any
  model. Parsing runs in a killable subprocess with size and count caps.
- Markdown, tables, KaTeX, and code blocks with copy buttons.

### Added — interface and deployment

- Light/dark theme with a selectable accent colour; nine languages (TR, EN, DE, ES, IT, PT, RU,
  JA, ZH).
- `docker compose up -d --build` and nothing else. Data lives in SQLite.
- **About 700 MB on disk for the whole stack**, web search included — backend 230 MB, frontend
  95.8 MB, SearXNG 372 MB (measured on arm64).

[Unreleased]: https://github.com/orkun-soylu/calivi/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/orkun-soylu/calivi/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/orkun-soylu/calivi/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/orkun-soylu/calivi/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/orkun-soylu/calivi/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/orkun-soylu/calivi/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/orkun-soylu/calivi/releases/tag/v0.1.0
