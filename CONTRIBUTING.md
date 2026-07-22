# Contributing

Thanks for considering a contribution. This document covers two things: the **legal
requirement** (DCO sign-off) and the **working habits** of this project — especially the
testing discipline, which has one unusual rule.

---

## 1. Sign your commits (required)

This project uses the **Developer Certificate of Origin** instead of a CLA. It is the
lightweight way of stating that you have the right to submit the code under this
project's license. There is no separate document to sign — you add one line to your
commit.

```bash
git commit -s -m "fix: ..."
```

`-s` appends:

```
Signed-off-by: Your Name <you@example.com>
```

The name and email must be real (a pseudonym is fine, but it has to be a reachable
identity). Full text: [`DCO`](DCO).

If you forgot to sign off, amend the last commit:

```bash
git commit --amend -s --no-edit && git push --force-with-lease
```

For several commits at once: `git rebase --signoff main`

---

## 2. Development environment

Setup steps are in the [README](README.md#development). In short:

```bash
# Frontend
cd frontend && npm install
npm run dev          # vite dev server on :5173
npm test             # vitest + jsdom

# Backend
cd backend
python3 -m venv .venv-test && ./.venv-test/bin/pip install -r requirements-dev.txt
./.venv-test/bin/pytest
./.venv-test/bin/uvicorn app.main:app --reload --port 8000
```

Running the backend separately serves the frontend from a different origin, so
`CORS_ORIGINS` applies — it already defaults to `http://localhost:5173`.

---

## 3. Testing discipline — the unusual rule

Passing tests are not enough. **You must show that the test passes for the right
reason.**

### Mutation testing (required when you add a guard)

If you add a guard — a validation, an authorization check, an error handler — then
**deliberately break it, watch the test fail, and put it back.**

```bash
# 1. Disable the guard (delete the line, or replace it with `pass`)
# 2. Run the tests → the RELEVANT test must fail
# 3. Restore it; tests must go green again
```

This rule exists because the project has been burned twice by false green:

- The isolation tests were originally written with `server_id: 1`. Since that server did
  not exist, the endpoint returned 404 regardless of the ownership check — meaning the
  tests would have passed even if `_owned_chat` were removed entirely. The fixtures now
  create a **real** server and a real message, so ownership is the only possible source
  of the 404.
- During one mutation attempt the edit never actually reached the file, which made it
  look like the tests failed to catch the mutation. **Verify that your mutation was
  applied** (check the diff, or `assert` it in your script) — otherwise you will draw the
  wrong conclusion.

### What is tested where

| Layer | Tooling | Location |
|---|---|---|
| Backend | pytest + `httpx.ASGITransport` (real HTTP layer, no live server) | `backend/tests/` |
| Frontend | vitest + jsdom + Testing Library | `*.test.jsx` next to the source file |

Backend tests are redirected to an isolated tmpdir by `conftest.py`. **Do not reorder the
imports in `conftest.py`** — `config`, `auth` and `database` read environment variables at
module level, so the environment must be set up *before* `app` is imported.

### Two traps when testing React hooks

1. **Never nest `act` blocks.** Nesting corrupts React's internal state, and *later*
   tests fail with `result.current === null` — with no clue in the failing test itself.
   Use a `deferred()` helper to hold a flow open instead.
2. **`result.current` is stale mid-flow** — re-renders are not flushed until the `act`
   block closes. To observe an intermediate state, keep the flow open with a deferred.

---

## 4. Code and commit conventions

**Code:** Match the surrounding file — its comment density, naming and idioms. Comments
should explain **why**, not what; if a decision looks counter-intuitive, write down the
reason.

Comments, docstrings and test names are in English throughout. The one deliberate exception
is the Turkish locale block in `frontend/src/i18n.js` — that is product content (one of the
nine shipped languages), not a comment, and must not be "translated".

**Commit subjects:** `type: short description`. Types used in this project:

```
feat  fix  docs  test  refactor  perf  style  i18n  revert
```

Explain the **why** in the body. If you are fixing a bug, describe the symptom, the root
cause, and how you verified the fix — this project treats its history as a diagnostic
resource.

**Architectural decisions belong in `ARCHITECTURE.md`.** If you made a lasting design decision,
or discovered a pitfall someone else will hit again, write it down there. The component
map, tool loop, security notes and "don't fall into this again" warnings all live there.

---

## 5. Before opening a pull request

- [ ] Commits signed off (`git commit -s`)
- [ ] Backend tests pass (`./.venv-test/bin/pytest`)
- [ ] Frontend tests pass (`npm test`)
- [ ] Frontend build is clean (`npm run build`)
- [ ] If you added a guard, you ran a **mutation test**
- [ ] `ARCHITECTURE.md` updated if behaviour changed
- [ ] `CHANGELOG.md` updated under `## [Unreleased]` if the change is user-visible
- [ ] No secrets: no `.env`, API keys, tokens or real hosts/IPs committed

For behavioural changes, verify your work by **actually running it** — don't rely on
tests alone. The app comes up with `docker compose up -d --build`.

---

## 6. Security

If you find a vulnerability, **do not open a public issue** — contact the maintainer
directly.

Things to know while contributing:

- Web search results and document attachments count as **untrusted content** and are
  passed to the model inside delimited blocks (`_wrap_untrusted`). If you add another
  path that carries external content to the model, use the same wrapping.
- The tool layer is currently **read-only**: tools declared `mutating=True` are rejected.
  A pull request that opens this gate will not be accepted without human-in-the-loop
  approval and capability scoping.
- The frontend is served under a strict Content-Security-Policy. If you edit the inline
  theme-bootstrap script in `index.html`, **recompute the CSP hash** (explained in a
  comment in `frontend/nginx.conf`), or the theme will flash on load.
