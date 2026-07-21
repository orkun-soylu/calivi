"""MCP server CRUD — admin only, mirroring routers/servers.py.

Adding an MCP server grants every user of this instance whatever that server can do, so the
whole router is admin-gated: there is no read-only listing for ordinary users the way
`/api/servers` has one for the chat picker.
"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import auth, models, schemas
from app.database import get_db
from app.tools import mcp_client

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


async def _build_out(server: models.McpServer, refresh: bool = False) -> schemas.McpServerOut:
    entry = await mcp_client.get(server, force=refresh)
    return schemas.McpServerOut(
        id=server.id,
        name=server.name,
        url=server.url,
        transport=server.transport,
        has_secret=bool(server.secret),
        secret_header=server.secret_header,
        secret_prefix=server.secret_prefix,
        headers=server.headers or {},
        enabled=server.enabled,
        disabled_tools=server.disabled_tools or [],
        status=entry.status,
        error=entry.error,
        tools=[schemas.McpToolOut(**t) for t in entry.tools],
        skipped_tools=entry.skipped,
    )


@router.get("", response_model=list[schemas.McpServerOut])
async def list_mcp_servers(
    refresh: bool = False,
    _admin: models.User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    servers = db.query(models.McpServer).all()
    # Probes run in parallel so several unreachable servers do not add up their timeouts.
    return list(await asyncio.gather(*(_build_out(s, refresh) for s in servers)))


@router.post("", response_model=schemas.McpServerOut)
async def create_mcp_server(
    payload: schemas.McpServerCreate,
    _admin: models.User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    server = models.McpServer(**payload.model_dump())
    db.add(server)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # The name is the tool-name namespace, so duplicates are rejected rather than
        # silently producing colliding tool names.
        raise HTTPException(409, "An MCP server with that name already exists")
    db.refresh(server)
    return await _build_out(server, refresh=True)


@router.patch("/{server_id}", response_model=schemas.McpServerOut)
async def update_mcp_server(
    server_id: int,
    payload: schemas.McpServerUpdate,
    _admin: models.User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    """Partial update; fields that are not sent are preserved — omitting `secret` keeps the
    stored secret, the same contract as `PATCH /api/servers`."""
    server = db.get(models.McpServer, server_id)
    if not server:
        raise HTTPException(404, "MCP server not found")
    old_source = mcp_client.source_of(server.id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(server, key, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An MCP server with that name already exists")
    db.refresh(server)
    # A rename changes the tool namespace, so the previously registered names have to go;
    # `refresh` re-registers under the new ones.
    mcp_client.registry.unregister_source(old_source)
    return await _build_out(server, refresh=True)


@router.delete("/{server_id}", status_code=204)
async def delete_mcp_server(
    server_id: int,
    _admin: models.User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    server = db.get(models.McpServer, server_id)
    if not server:
        raise HTTPException(404, "MCP server not found")
    db.delete(server)
    db.commit()
    # Drop the tools immediately — otherwise a deleted server's tools stay callable until
    # the next restart.
    mcp_client.registry.unregister_source(mcp_client.source_of(server_id))
    mcp_client.invalidate(server_id)
