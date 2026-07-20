"""Login brute-force protection — counter logic plus login endpoint behaviour."""
from collections import deque

import pytest

from app.config import LOGIN_MAX_ATTEMPTS
from app.rate_limit import SlidingWindowLimiter, login_key
from app.routers.auth import login_limiter
from conftest import login, register


# ── Counter logic (pure unit) ────────────────────────────────────────────────


def test_below_the_threshold_it_does_not_lock():
    lim = SlidingWindowLimiter(max_attempts=3, window=60)
    for _ in range(2):
        lim.record_failure("k")
    assert lim.retry_after("k") == 0


def test_at_the_threshold_it_locks_and_reports_retry_after():
    lim = SlidingWindowLimiter(max_attempts=3, window=60)
    for _ in range(3):
        lim.record_failure("k")
    retry = lim.retry_after("k")
    assert 0 < retry <= 61


def test_allowance_returns_as_the_window_slides():
    lim = SlidingWindowLimiter(max_attempts=3, window=60)
    for _ in range(3):
        lim.record_failure("k")
    assert lim.retry_after("k") > 0

    # Push the oldest attempts out of the window (sliding window, not a wholesale reset)
    lim._events["k"] = deque(t - 61 for t in lim._events["k"])
    assert lim.retry_after("k") == 0


def test_partial_slide_only_frees_the_stale_attempts():
    """If one attempt leaves the window, exactly one allowance returns (not all of them)."""
    lim = SlidingWindowLimiter(max_attempts=3, window=60)
    for _ in range(3):
        lim.record_failure("k")
    events = list(lim._events["k"])
    lim._events["k"] = deque([events[0] - 61, events[1], events[2]])

    assert lim.retry_after("k") == 0
    lim.record_failure("k")
    assert lim.retry_after("k") > 0


def test_reset_clears_the_counter():
    lim = SlidingWindowLimiter(max_attempts=1, window=60)
    lim.record_failure("k")
    assert lim.retry_after("k") > 0
    lim.reset("k")
    assert lim.retry_after("k") == 0


def test_keys_do_not_affect_each_other():
    lim = SlidingWindowLimiter(max_attempts=1, window=60)
    lim.record_failure("a")
    assert lim.retry_after("a") > 0
    assert lim.retry_after("b") == 0


def test_stale_keys_are_swept():
    """The dict must not grow without bound (a spray of random usernames must not bloat memory)."""
    lim = SlidingWindowLimiter(max_attempts=5, window=0.01)
    for i in range(1200):
        lim.record_failure(f"k{i}")
    assert len(lim._events) < 1200


def test_login_key_normalises():
    assert login_key("  Orkun  ") == login_key("orkun") == "orkun"


# ── Endpoint behaviour ───────────────────────────────────────────────────────


async def _try_wrong(client, username="victim", n=1):
    for _ in range(n):
        resp = await login(client, username, "wrong-password")
    return resp


async def test_crossing_the_threshold_gives_429_and_retry_after(client, user_client):
    await register(client, "admin")
    await register(user_client, "victim")

    for _ in range(LOGIN_MAX_ATTEMPTS):
        assert (await _try_wrong(user_client)).status_code == 401

    resp = await _try_wrong(user_client)
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) > 0


async def test_even_the_right_password_is_rejected_while_locked(client, user_client):
    """The gate sits BEFORE password verification — otherwise an attacker could still try it."""
    await register(client, "admin")
    await register(user_client, "victim")

    await _try_wrong(user_client, n=LOGIN_MAX_ATTEMPTS)
    assert (await login(user_client, "victim")).status_code == 429


async def test_a_successful_login_resets_the_counter(client, user_client):
    await register(client, "admin")
    await register(user_client, "victim")

    await _try_wrong(user_client, n=LOGIN_MAX_ATTEMPTS - 1)
    assert (await login(user_client, "victim")).status_code == 200  # below the threshold, passes

    # The counter was reset, so the full quota is available again
    for _ in range(LOGIN_MAX_ATTEMPTS - 1):
        assert (await _try_wrong(user_client)).status_code == 401


async def test_locking_one_account_does_not_affect_another(client, user_client):
    await register(client, "admin")
    await register(user_client, "victim")

    await _try_wrong(user_client, n=LOGIN_MAX_ATTEMPTS)
    assert (await login(user_client, "victim")).status_code == 429
    assert (await login(user_client, "admin")).status_code == 200  # admin unaffected


async def test_email_and_username_share_one_counter(client, user_client):
    """Attacking the same account with two identifiers must not double the allowance."""
    await register(client, "admin")
    await register(user_client, "victim")

    for _ in range(LOGIN_MAX_ATTEMPTS):
        await user_client.post(
            "/api/auth/login", json={"identifier": "victim", "password": "wrong"}
        )

    resp = await user_client.post(
        "/api/auth/login", json={"identifier": "victim@test.local", "password": "wrong"}
    )
    assert resp.status_code == 429


async def test_non_existent_users_are_counted_too(client):
    """If they were not, an attacker could try endlessly and enumerate usernames."""
    await register(client, "admin")

    for _ in range(LOGIN_MAX_ATTEMPTS):
        assert (await login(client, "ghost", "x")).status_code == 401
    assert (await login(client, "ghost", "x")).status_code == 429


async def test_a_blocked_user_does_not_pollute_the_counter(admin, user_client):
    """Password CORRECT but the account is blocked → 403; that is not brute force, do not count it."""
    await register(user_client, "blocked")
    await admin.patch("/api/users/2", json={"blocked": True})

    for _ in range(LOGIN_MAX_ATTEMPTS + 2):
        assert (await login(user_client, "blocked")).status_code == 403  # must NEVER become 429


async def test_registration_is_unaffected_by_the_rate_limit(client, user_client):
    """The limit applies to login only: a locked account must not block new sign-ups."""
    await register(client, "admin")
    await register(user_client, "victim")
    await _try_wrong(user_client, n=LOGIN_MAX_ATTEMPTS)

    resp = await user_client.post(
        "/api/auth/register",
        json={"email": "new@test.local", "username": "new", "password": "password123"},
    )
    assert resp.status_code < 400
