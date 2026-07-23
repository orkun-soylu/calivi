# Changelog

Notable changes to Calivi, newest first.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions are
[SemVer](https://semver.org/spec/v2.0.0.html), with the caveat that the major version is `0`:
**while it stays there, anything may change between releases**, including the database schema.
Read this file before upgrading.

## [Unreleased]

### Added

- A favicon, so the browser tab shows the Calivi mark instead of a blank page icon. It is the
  same mark the calivi.ai landing page uses.

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

[Unreleased]: https://github.com/orkun-soylu/calivi/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/orkun-soylu/calivi/releases/tag/v0.1.0
