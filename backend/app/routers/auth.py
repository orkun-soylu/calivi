from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app import auth, models, schemas
from app.config import LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW_SECONDS
from app.database import get_db
from app.rate_limit import SlidingWindowLimiter, login_key

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Login attempt counter per account (module level — lives for the process lifetime).
login_limiter = SlidingWindowLimiter(LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW_SECONDS)


def _get_settings(db: Session) -> models.Setting:
    s = db.get(models.Setting, 1)
    if not s:
        s = models.Setting(id=1, registration_enabled=True)
        db.add(s)
        db.commit()
    return s


@router.get("/config", response_model=schemas.AuthConfigOut)
def auth_config(db: Session = Depends(get_db)):
    """Unauthenticated: lets the login screen show or hide the signup tab."""
    return schemas.AuthConfigOut(registration_enabled=_get_settings(db).registration_enabled)


@router.post("/register", response_model=schemas.UserOut)
def register(payload: schemas.RegisterIn, response: Response, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    username = payload.username.strip()
    if not email or not username or not payload.password:
        raise HTTPException(400, "Email, username and password are required")
    if "@" not in email or "." not in email:
        raise HTTPException(400, "Enter a valid email address")

    user_count = db.query(models.User).count()
    # Block when registration is closed — but always allow the first (super admin) sign-up.
    if user_count > 0 and not _get_settings(db).registration_enabled:
        raise HTTPException(403, "Registration is closed")

    if db.query(models.User).filter(models.User.email == email).first():
        raise HTTPException(409, "That email is already registered")
    if db.query(models.User).filter(models.User.username == username).first():
        raise HTTPException(409, "That username is already taken")

    user = models.User(
        email=email,
        username=username,
        password_hash=auth.hash_password(payload.password),
        role="admin" if user_count == 0 else "user",  # first user = super admin (id 1)
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    auth.set_session_cookie(response, user.id)
    return user


@router.post("/login", response_model=schemas.UserOut)
def login(payload: schemas.LoginIn, response: Response, db: Session = Depends(get_db)):
    ident = payload.identifier.strip()
    user = (
        db.query(models.User)
        .filter((models.User.email == ident.lower()) | (models.User.username == ident))
        .first()
    )
    # The key is bound to the account (NOT the raw identifier): otherwise the same account
    # could be attacked via username and email separately, doubling the allowance. If no user
    # exists the identifier itself becomes the key (still counted → usernames cannot be enumerated).
    key = login_key(ident) if user is None else f"user:{user.id}"

    # Brute-force gate, BEFORE password verification — while locked out we do not even run bcrypt.
    retry = login_limiter.retry_after(key)
    if retry:
        raise HTTPException(
            429,
            f"Too many failed login attempts. Try again in {retry // 60 + 1} minute(s).",
            headers={"Retry-After": str(retry)},
        )

    if not user or not auth.verify_password(payload.password, user.password_hash):
        # Non-existent users are counted too: otherwise an attacker could enumerate usernames.
        login_limiter.record_failure(key)
        raise HTTPException(401, "Incorrect username/email or password")
    if user.blocked:
        # The password was CORRECT — not brute force, so do not count it (no penalty for a legitimate user).
        raise HTTPException(403, "Your account has been suspended")

    login_limiter.reset(key)
    auth.set_session_cookie(response, user.id)
    return user


@router.post("/logout")
def logout(response: Response):
    auth.clear_session_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=schemas.UserOut)
def me(user: models.User = Depends(auth.get_current_user)):
    return user
