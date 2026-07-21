"""Authentication core: password hashing, JWT, httpOnly cookie sessions, dependencies."""
import datetime
import os

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.config import SECRET_KEY
from app.database import get_db
from app import models

COOKIE_NAME = "calivi_session"
COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days
ALGORITHM = "HS256"
# Cookie Secure flag: on for production (https). Turn it off when testing over plain http.
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").lower() != "false"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_token(user_id: int) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {"sub": str(user_id), "iat": now, "exp": now + datetime.timedelta(seconds=COOKIE_MAX_AGE)}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def set_session_cookie(response: Response, user_id: int) -> None:
    response.set_cookie(
        COOKIE_NAME,
        create_token(user_id),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def get_current_user(request: Request, db: Session = Depends(get_db)) -> models.User:
    """Resolves the session from the cookie. Missing/blocked user → 401 (blocking auto-logs out)."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(401, "Invalid session")
    user = db.get(models.User, user_id)
    if not user or user.blocked:
        raise HTTPException(401, "Session no longer valid")
    return user


def require_admin(user: models.User = Depends(get_current_user)) -> models.User:
    if user.role != "admin":
        raise HTTPException(403, "Admin required")
    return user
