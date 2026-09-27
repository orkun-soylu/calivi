"""Background turns — a reply keeps running when its HTTP request goes away (#85).

The agentic loop (`routers/chats.py::build_stream_response`) is an async generator of NDJSON
lines. It used to be the response body, so a closed tab, a reload or a dropped connection
cancelled it half-way — and Stop was simply a disconnect. Now it runs as an `asyncio` task in
this registry. Every line it yields is appended to the turn's log, and each HTTP response is a
**follower**: it replays the log from the start, then streams what comes next. Followers come
and go; the task does not notice them.

- **One turn per chat.** `start` refuses a second one; the endpoints turn that into a 409.
- **Stop is explicit** (`cancel`). The generator's `finally` still saves the partial reply.
- **In memory, deliberately** — the same call as `approvals.py`: a restart loses an in-flight
  turn, as a crash always did. Single process assumed, as it already is for approvals.
- A finished turn leaves the registry at once. Its reply is in the database by then (the
  generator saves in its `finally`, which runs before the task ends), so a late follower gets
  a 404 and simply reloads the chat.

Thread safety: `cancel` may be called from a sync endpoint (FastAPI runs those in a thread
pool), so it hands the cancellation to the loop with `call_soon_threadsafe`. Everything else
runs on the event loop.
"""
import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from app.config import APPROVAL_HEARTBEAT

PING = json.dumps({"type": "ping"}) + "\n"


class Busy(Exception):
    """The chat already has a running turn."""


@dataclass
class Turn:
    chat_id: int
    user_id: int | None
    loop: asyncio.AbstractEventLoop
    lines: list[str] = field(default_factory=list)
    done: bool = False
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None

    def _append(self, line: str) -> None:
        self.lines.append(line)
        self._wake()

    def _wake(self) -> None:
        # One Event per generation of waiters: set it to wake everyone, then replace it so the
        # next wait blocks again. Cheaper and simpler than a Condition for many followers.
        self.changed.set()
        self.changed = asyncio.Event()


_turns: dict[int, Turn] = {}


def get(chat_id: int) -> Turn | None:
    return _turns.get(chat_id)


def is_active(chat_id: int) -> bool:
    return chat_id in _turns


def start(chat_id: int, user_id: int | None, lines: AsyncIterator[str]) -> Turn:
    """Runs `lines` (the loop's generator) as a background task. Must be called on the loop."""
    if chat_id in _turns:
        raise Busy(chat_id)
    turn = Turn(chat_id=chat_id, user_id=user_id, loop=asyncio.get_running_loop())
    _turns[chat_id] = turn

    async def run() -> None:
        try:
            async for line in lines:
                turn._append(line)
        finally:
            # Ends the generator on cancellation too, so its `finally` saves the partial reply
            # before this turn is gone from the registry.
            await lines.aclose()
            turn.done = True
            if _turns.get(chat_id) is turn:
                del _turns[chat_id]
            turn._wake()

    turn.task = asyncio.create_task(run(), name=f"turn-{chat_id}")
    return turn


async def follow(turn: Turn, heartbeat: float = APPROVAL_HEARTBEAT) -> AsyncIterator[str]:
    """Everything the turn has said so far, then everything it says next, until it ends.

    Pings when nothing has happened for `heartbeat` seconds: a long `apt install` or a model
    prefilling a large prompt is silent, and proxies drop idle connections (nginx after 300s).
    """
    sent = 0
    while True:
        while sent < len(turn.lines):
            yield turn.lines[sent]
            sent += 1
        if turn.done:
            return
        waiter = turn.changed
        try:
            await asyncio.wait_for(waiter.wait(), heartbeat)
        except TimeoutError:
            yield PING


def cancel(chat_id: int) -> bool:
    """Stops the chat's turn, if any. Safe to call from any thread. True if one was running."""
    turn = _turns.get(chat_id)
    if turn is None or turn.task is None:
        return False
    turn.loop.call_soon_threadsafe(turn.task.cancel)
    return True


def clear() -> None:
    """Tests only: forget every turn (their tasks die with the test's event loop)."""
    for turn in _turns.values():
        if turn.task is not None:
            turn.task.cancel()
    _turns.clear()
