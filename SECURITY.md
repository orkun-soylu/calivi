# Security policy

## Supported versions

Calivi is at `0.x` and under heavy development. Security fixes land on `main` and ship in the
next release; older releases do not get backports.

| Version | Supported |
|---|---|
| `main` | ✅ |
| Latest release (currently `v0.1.0`) | ✅ until the next release |
| Anything older | ❌ |

If you run Calivi, run the latest release or `main`.

## Reporting a vulnerability

**Please do not report a vulnerability in a public issue, discussion or pull request.**

Report it privately through GitHub:
**[Report a vulnerability](https://github.com/orkun-soylu/calivi/security/advisories/new)**
(the repository's *Security* tab → *Advisories* → *Report a vulnerability*). Only the maintainer
sees the report.

A useful report includes:

- the affected version or commit;
- how Calivi is deployed — the bundled `docker compose` setup, anything in front of it (reverse
  proxy, TLS), and relevant settings such as `COOKIE_SECURE`;
- steps to reproduce, or a proof of concept;
- the impact: what an attacker gains, and what access they need first (none, a normal user
  account, an admin account);
- logs if they help — with API keys, tokens, hostnames and IP addresses removed.

## What to expect

Calivi has a single maintainer, so this is best effort rather than a guaranteed timeline. You
can expect:

- a reply in the private advisory thread, where the report is discussed;
- if the issue is confirmed, a fix on `main` and a published GitHub security advisory that
  credits you, unless you prefer not to be named;
- coordinated disclosure: please keep the details private until the fix is released.

## Scope

**In scope** — anything that breaks a boundary Calivi claims to enforce:

- authentication and sessions; one user reaching another user's chats; a non-admin reaching
  admin-only functionality; the super admin being demoted or deleted;
- the tool layer: a state-changing tool running without approval, or the sandboxed stdio MCP
  bridge reaching the internet or the LAN;
- the prompt-injection defences around untrusted content (web search results, uploaded
  documents, tool output), for example content that escapes its delimiters;
- secrets at rest: provider API keys or MCP tokens readable from a copy of the database;
- the frontend's Content-Security-Policy, or script execution through rendered model output;
- document extraction: a crafted file that hangs or crashes the backend despite the extraction
  limits;
- a vulnerable dependency, when you can show the vulnerable code is reachable in Calivi.

**Out of scope:**

- anything an **admin** can already do — admins are trusted by design, for example pointing a
  model server or an MCP server at an internal address;
- a model producing wrong, harmful or "jailbroken" text without crossing one of the boundaries
  above;
- deployments that switch a protection off, such as `COOKIE_SECURE=false` on plain HTTP or a
  weak, hand-picked `CALIVI_SECRET_KEY`;
- scanner output without a demonstrated impact, or a missing hardening header on its own;
- vulnerabilities in the third-party model servers, MCP servers or services Calivi connects to —
  please report those to their maintainers.
