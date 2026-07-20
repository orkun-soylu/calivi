import asyncio
import time
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import auth, models, schemas, llm
from app.config import PROBE_TTL_DOWN, PROBE_TTL_UP
from app.database import get_db

router = APIRouter(prefix="/api/servers", tags=["servers"])


def _spec(s: models.Server) -> dict:
    return {"type": s.type, "host": s.host, "port": s.port, "base_url": s.base_url, "api_key": s.api_key}


# ── Probe cache ───────────────────────────────────────────────────────────────
# The frontend calls `GET /api/servers` every 3s; probing live on every request meant
# waiting the full PROBE_TIMEOUT for each offline server (slow UI startup). Results are
# now cached with a TTL. There are three ways to invalidate: (1) the TTL expiring,
# (2) a server setting changing (spec comparison / `_invalidate` on PATCH+DELETE),
# (3) manual refresh via `?refresh=1`.


@dataclass
class _Entry:
    spec: dict
    status: str
    models: list[str]
    vision: list[str]
    at: float = field(default_factory=time.monotonic)


_cache: dict[int, _Entry] = {}
# Per-server single-flight: concurrent requests (many tabs/users) share one probe.
_locks: dict[int, asyncio.Lock] = {}


def _fresh(s: models.Server) -> _Entry | None:
    """Returns the cached entry for this server if it is still valid."""
    entry = _cache.get(s.id)
    if entry is None or entry.spec != _spec(s):
        return None  # settings changed → the old result no longer represents this server
    ttl = PROBE_TTL_UP if entry.status == "up" else PROBE_TTL_DOWN
    return entry if time.monotonic() - entry.at < ttl else None


def _invalidate(server_id: int) -> None:
    _cache.pop(server_id, None)
    _locks.pop(server_id, None)


async def _probe(s: models.Server) -> _Entry:
    async with _locks.setdefault(s.id, asyncio.Lock()):
        # Another request may have refreshed it while we waited for the lock.
        entry = _fresh(s)
        if entry is not None:
            return entry
        spec = _spec(s)
        status, model_names = await llm.probe(spec)
        # Retired models are filtered out here: `models` carries only live ones, so they
        # never reach the picker. The verdict lives in this TTL'd cache rather than being
        # permanent → if a model returns (or the failure was transient) it comes back on
        # the next refresh.
        live, vision = await llm.model_capabilities(spec, model_names) if status == "up" else ([], [])
        entry = _Entry(spec=spec, status=status, models=live, vision=vision)
        _cache[s.id] = entry
        return entry


async def _build_out(s: models.Server, refresh: bool = False) -> schemas.ServerOut:
    if refresh:
        _invalidate(s.id)
    entry = (None if refresh else _fresh(s)) or await _probe(s)
    return schemas.ServerOut(
        id=s.id,
        name=s.name,
        type=s.type,
        host=s.host,
        port=s.port,
        base_url=s.base_url,
        has_api_key=bool(s.api_key),
        status=entry.status,
        models=entry.models,
        vision_models=entry.vision,
    )


@router.get("", response_model=list[schemas.ServerOut])
async def list_servers(
    refresh: bool = False,
    _user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    # Any signed-in user can list servers (needed for the chat picker); adding/editing is
    # admin-only. Probes run in parallel so offline servers' timeouts do not add up on a miss.
    return list(
        await asyncio.gather(*(_build_out(s, refresh) for s in db.query(models.Server).all()))
    )


@router.post("", response_model=schemas.ServerOut)
async def create_server(
    payload: schemas.ServerCreate,
    _admin: models.User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    server = models.Server(**payload.model_dump())
    db.add(server)
    db.commit()
    db.refresh(server)
    return await _build_out(server)


@router.patch("/{server_id}", response_model=schemas.ServerOut)
async def update_server(
    server_id: int,
    payload: schemas.ServerUpdate,
    _admin: models.User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    """Partially updates server settings (fields not sent are preserved)."""
    server = db.get(models.Server, server_id)
    if not server:
        raise HTTPException(404, "Server not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(server, key, value)
    db.commit()
    db.refresh(server)
    # After editing settings the user wants to see "does it work now" → always probe live.
    return await _build_out(server, refresh=True)


@router.delete("/{server_id}", status_code=204)
def delete_server(
    server_id: int,
    _admin: models.User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    server = db.get(models.Server, server_id)
    if not server:
        raise HTTPException(404, "Server not found")
    db.delete(server)
    db.commit()
    # `servers` is NOT sqlite_autoincrement → a deleted id can be reassigned to a new server.
    # Without clearing the cache the new server would show the old one's probe result.
    _invalidate(server_id)
