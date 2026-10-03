"""Settings → Activity: the host-tool audit log (audit.py, #115), read-only, and the owner's
"always allow" rules (approval_rules.py, #113), which can be deleted here.

Only for whoever the host tools are for — the super admin on an instance with them switched on.
Everyone else, and every instance without them, gets 404: the route does not exist for them,
the same way a privileged tool does not.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import approval_rules, audit, auth, config, models
from app.database import get_db
from app.routers.users import SUPER_ADMIN_ID

router = APIRouter(prefix="/api", tags=["activity"])


def _owner(user: models.User = Depends(auth.get_current_user)) -> models.User:
    if not (config.HOST_TOOLS_ENABLED and user.id == SUPER_ADMIN_ID):
        raise HTTPException(status_code=404, detail="Not Found")
    return user


@router.get("/activity")
def list_activity(
    chat_id: int | None = None, tool: str | None = None, limit: int = 200,
    user: models.User = Depends(_owner), db: Session = Depends(get_db),
):
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


@router.get("/approval-rules")
def list_rules(user: models.User = Depends(_owner), db: Session = Depends(get_db)):
    rules = (db.query(models.ApprovalRule).filter(models.ApprovalRule.user_id == user.id)
             .order_by(models.ApprovalRule.id).all())
    return [{**approval_rules.describe(r), "uses": r.uses or 0, "created_at": r.created_at,
             "last_used_at": r.last_used_at} for r in rules]


@router.delete("/approval-rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int, user: models.User = Depends(_owner), db: Session = Depends(get_db)):
    rule = db.get(models.ApprovalRule, rule_id)
    if rule is None or rule.user_id != user.id:
        raise HTTPException(404, "Rule not found")
    described = approval_rules.describe(rule)
    db.delete(rule)
    db.commit()
    audit.record_rule("rule_deleted", user.id, described)
