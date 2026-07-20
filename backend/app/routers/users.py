from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import auth, models, schemas
from app.database import get_db

router = APIRouter(prefix="/api", tags=["users"])

SUPER_ADMIN_ID = 1  # id==1 is the super admin, untouchable


def _delete_user_chats(db: Session, user_id: int) -> None:
    """Deletes the user's chats AND their messages.

    A bulk delete does not trigger the ORM cascade, so messages are removed explicitly to
    stop their content being orphaned in the DB (PRAGMA foreign_keys=ON in database.py also
    cascades at DB level — this is the belt-and-braces half).
    """
    chat_ids = select(models.Chat.id).where(models.Chat.user_id == user_id)
    db.query(models.Message).filter(models.Message.chat_id.in_(chat_ids)).delete(synchronize_session=False)
    db.query(models.Chat).filter(models.Chat.user_id == user_id).delete(synchronize_session=False)


@router.get("/users", response_model=list[schemas.UserOut])
def list_users(_admin: models.User = Depends(auth.require_admin), db: Session = Depends(get_db)):
    return db.query(models.User).order_by(models.User.id).all()


# NOTE: the "/users/me" route must be declared BEFORE "/users/{user_id}", otherwise "me"
# is matched against the int path param and yields a 422.
@router.patch("/users/me", response_model=schemas.UserOut)
def update_me(
    payload: schemas.UserUpdate,
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """Self-service: a user may change only their own email/username (role/block unaffected)."""
    data = payload.model_dump(exclude_unset=True)
    if "email" in data:
        email = data["email"].strip().lower()
        if not email or "@" not in email:
            raise HTTPException(400, "Enter a valid email address")
        if db.query(models.User).filter(models.User.email == email, models.User.id != user.id).first():
            raise HTTPException(409, "That email is already registered")
        user.email = email
    if "username" in data:
        username = data["username"].strip()
        if not username:
            raise HTTPException(400, "Username cannot be empty")
        if db.query(models.User).filter(models.User.username == username, models.User.id != user.id).first():
            raise HTTPException(409, "That username is already taken")
        user.username = username
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/me", status_code=204)
def delete_me(
    response: Response,
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """Self-service: deletes the user's own account and all their chats. Not the super admin (id 1)."""
    if user.id == SUPER_ADMIN_ID:
        raise HTTPException(403, "The super admin cannot be deleted")
    _delete_user_chats(db, user.id)
    db.delete(user)
    db.commit()
    auth.clear_session_cookie(response)  # end the session


@router.patch("/users/{user_id}", response_model=schemas.UserOut)
def update_user(
    user_id: int,
    payload: schemas.UserUpdate,
    _admin: models.User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    if user_id == SUPER_ADMIN_ID:
        raise HTTPException(403, "The super admin cannot be modified")
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    data = payload.model_dump(exclude_unset=True)
    if "role" in data and data["role"] not in ("admin", "user"):
        raise HTTPException(400, "Invalid role")
    if "email" in data:
        email = data["email"].strip().lower()
        if not email or "@" not in email:
            raise HTTPException(400, "Enter a valid email address")
        clash = db.query(models.User).filter(models.User.email == email, models.User.id != user_id).first()
        if clash:
            raise HTTPException(409, "That email is already registered")
        user.email = email
    if "username" in data:
        username = data["username"].strip()
        if not username:
            raise HTTPException(400, "Username cannot be empty")
        clash = db.query(models.User).filter(models.User.username == username, models.User.id != user_id).first()
        if clash:
            raise HTTPException(409, "That username is already taken")
        user.username = username
    if "role" in data:
        user.role = data["role"]
    if "blocked" in data:
        user.blocked = data["blocked"]

    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    _admin: models.User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    if user_id == SUPER_ADMIN_ID:
        raise HTTPException(403, "The super admin cannot be deleted")
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    _delete_user_chats(db, user_id)
    db.delete(user)
    db.commit()


@router.get("/settings", response_model=schemas.AuthConfigOut)
def get_settings(_admin: models.User = Depends(auth.require_admin), db: Session = Depends(get_db)):
    s = db.get(models.Setting, 1)
    return schemas.AuthConfigOut(registration_enabled=s.registration_enabled if s else True)


@router.patch("/settings", response_model=schemas.AuthConfigOut)
def update_settings(
    payload: schemas.SettingsUpdate,
    _admin: models.User = Depends(auth.require_admin),
    db: Session = Depends(get_db),
):
    s = db.get(models.Setting, 1)
    if not s:
        s = models.Setting(id=1, registration_enabled=True)
        db.add(s)
    if payload.registration_enabled is not None:
        s.registration_enabled = payload.registration_enabled
    db.commit()
    db.refresh(s)
    return schemas.AuthConfigOut(registration_enabled=s.registration_enabled)
