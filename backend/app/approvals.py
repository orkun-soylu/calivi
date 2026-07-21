"""Pending tool-call approvals — the human-in-the-loop half of the tool layer.

The agentic loop runs inside a `StreamingResponse`, so asking for approval means pausing the
generator mid-stream and waiting for a decision that arrives on a *different* request. This
module is that rendezvous: the loop creates a pending entry and awaits its event, and
`POST /api/chats/{chat_id}/approvals/{id}` resolves it.

**In-process and deliberately so.** A pending approval lives in memory, so a closed tab or a
backend restart loses it and the message has to be retried. The durable alternative (persisting
the half-finished tool turn and resuming in a new request) would mean persisting tool turns as
messages, which the data model deliberately avoids — see ARCHITECTURE.md. A decision that is
made in seconds does not justify changing the data model.
"""
import asyncio
import secrets
import time
from dataclasses import dataclass, field


@dataclass
class Pending:
    chat_id: int
    user_id: int
    tool: str
    args: dict
    event: asyncio.Event = field(default_factory=asyncio.Event)
    approved: bool = False
    created_at: float = field(default_factory=time.monotonic)


_pending: dict[str, Pending] = {}


def create(chat_id: int, user_id: int, tool: str, args: dict) -> str:
    """Registers a pending approval and returns its id (unguessable: it is a capability)."""
    approval_id = secrets.token_urlsafe(16)
    _pending[approval_id] = Pending(chat_id=chat_id, user_id=user_id, tool=tool, args=args)
    return approval_id


def get(approval_id: str) -> Pending | None:
    return _pending.get(approval_id)


def discard(approval_id: str) -> None:
    """Always call this when the waiting loop leaves, including on an abort — a stream killed by
    a closed tab raises CancelledError (a BaseException), and without this the entry leaks."""
    _pending.pop(approval_id, None)


def resolve(approval_id: str, chat_id: int, user_id: int, approved: bool) -> bool:
    """Records a decision. Returns False when the approval is unknown or belongs to someone
    else — approving is granting a capability, so both the owner and the chat must match."""
    pending = _pending.get(approval_id)
    if pending is None or pending.user_id != user_id or pending.chat_id != chat_id:
        return False
    pending.approved = approved
    pending.event.set()
    return True


async def wait(approval_id: str, timeout: float, heartbeat: float):
    """Yields once per `heartbeat` while waiting, then finally the decision.

    The generator yields rather than simply awaiting because **no bytes flow down the stream
    while a human is deciding**, and nginx's `proxy_read_timeout` (300s) measures exactly that
    gap — without pings it would fire at the same moment as the auto-denial. Callers forward
    each `None` as a ping.

    Yields `None` on each heartbeat tick and `True`/`False` once as the final value. A timeout
    is a denial: silence must never be read as consent.
    """
    pending = _pending.get(approval_id)
    if pending is None:
        yield False
        return
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            yield False
            return
        try:
            await asyncio.wait_for(pending.event.wait(), timeout=min(heartbeat, remaining))
        except asyncio.TimeoutError:
            yield None  # heartbeat — keeps the connection alive
            continue
        yield pending.approved
        return


def clear() -> None:
    """Test helper — module state must not leak between tests."""
    _pending.clear()
