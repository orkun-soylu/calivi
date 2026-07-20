<!--
Thanks for contributing to Calivi. Please describe the change and tick the checklist.
See CONTRIBUTING.md for the full conventions.
-->

### What and why

<!-- What does this change do, and why? If it fixes a bug, describe the symptom, the root
cause, and how you verified the fix — this project treats its history as a diagnostic resource. -->

Closes #

### Checklist

- [ ] Commits are signed off (`git commit -s`)
- [ ] Backend tests pass (`cd backend && ./.venv-test/bin/pytest`)
- [ ] Frontend tests pass (`cd frontend && npm test`)
- [ ] Frontend build is clean (`npm run build`)
- [ ] If I added a guard, I ran a **mutation test** (deliberately broke it and confirmed a test fails)
- [ ] `ARCHITECTURE.md` updated if behaviour or a design decision changed
- [ ] No secrets: no `.env`, API keys, tokens or real hosts/IPs committed
