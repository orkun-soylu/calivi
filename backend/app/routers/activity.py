"""Settings → Activity: the host-tool audit log (audit.py, #115), read-only.

Only for whoever the host tools are for — the super admin on an instance with them switched on.
Everyone else, and every instance without them, gets 404: the route does not exist for them,
the same way a privileged tool does not.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import audit, auth, config, models
from app.database import get_db
from app.routers.users import SUPER_ADMIN_ID

router = APIRouter(prefix="/api/activity", tags=["activity"])


@router.get("")
def list_activity(
    chat_id: int | None = None, tool: str | None = None, limit: int = 200,
    user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db),
):
    if not (config.HOST_TOOLS_ENABLED and user.id == SUPER_ADMIN_ID):
        raise HTTPException(status_code=404, detail="Not Found")
    rows = audit.read(chat_id=chat_id, tool=tool, limit=limit)
    # Titles for the chats that still exist; a deleted one keeps its id and nothing else.
    ids = {r.get("chat") for r in rows if isinstance(r.get("chat"), int)}
    titles = dict(
        db.query(models.Chat.id, models.Chat.title)
        .filter(models.Chat.id.in_(ids), models.Chat.user_id == user.id).all()
    ) if ids else {}
    for r in rows:
        r["chat_title"] = titles.get(r.get("chat"))
    return {"enabled": audit.enabled(), "entries": rows}
