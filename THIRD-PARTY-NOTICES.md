# Third-Party Notices

Calivi itself is MIT licensed (see `LICENSE`). It bundles and redistributes the third-party
assets below, which carry their own licenses.

## Fonts — JetBrains Mono Nerd Font

Redistributed as `frontend/src/fonts/*.woff2` (converted from the upstream TTFs).

- **JetBrains Mono** — Copyright 2020 The JetBrains Mono Project Authors
  (https://github.com/JetBrains/JetBrainsMono), licensed under the
  **SIL Open Font License, Version 1.1**. The full license text ships alongside the font files
  at [`frontend/src/fonts/OFL.txt`](frontend/src/fonts/OFL.txt), as the OFL requires for
  redistribution.
- **Nerd Fonts** — the glyph patching applied on top is from
  [Nerd Fonts](https://github.com/ryanoasis/nerd-fonts). The patched font remains under the
  original typeface's OFL-1.1 licence; the patcher tooling itself is MIT.

> Note on the OFL "Reserved Font Name" clause: the patched files are named
> *JetBrains Mono Nerd Font*, matching upstream Nerd Fonts naming, not plain *JetBrains Mono*.

## Icons

- **Lucide** (https://lucide.dev) — ISC licence. Used for the menu/settings/power icons in
  `frontend/src/assets/` and `frontend/src/components/icons.jsx`.
- The inline copy/edit/delete icons are hand-drawn in a Feather-like style.

## Bundled service

- **SearXNG** (https://github.com/searxng/searxng) — AGPL-3.0. Not vendored into this repository;
  it is pulled as an unmodified upstream Docker image (`searxng/searxng`) by
  `docker-compose.yml`, and configured via `searxng/settings.yml`.

Runtime dependencies installed from npm and PyPI are not listed here; see
`frontend/package.json` and `backend/requirements.txt` for the authoritative lists.
