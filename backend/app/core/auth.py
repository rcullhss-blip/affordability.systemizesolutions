"""
Authentication for the admin dashboard and firm portals.

Principals:
  * A signed-in user (JWT bearer token issued by POST /api/v1/auth/login).
      role "admin"  — Systemize staff: everything.
      role "firm"   — an instructing solicitor's user: only their own firm's
                      batches/jobs/uploads. `user.firm` is the firm key
                      (barings, accord, first_legal, ryans, ...).
  * A partner machine (X-API-Key matching IRL_CASE_API_KEY or
    PROCLAIM_WEBHOOK_API_KEY) — treated as admin for the routes that already
    accepted those keys (tracker pulls, reprocess, retry-failed, s3-prefix).

Tokens: HS256 JWT signed with SECRET_KEY, 12h lifetime. Sent as
`Authorization: Bearer <token>`; GET download links (tracker CSV, LOC zip) may
pass `?token=` instead because an <a href> cannot carry a header.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
import bcrypt
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.tables import User

ALGORITHM = "HS256"
TOKEN_LIFETIME = timedelta(hours=12)

_bearer = HTTPBearer(auto_error=False)
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


# bcrypt directly (not passlib: passlib 1.7.4 is unmaintained and breaks with
# bcrypt >= 4.1 — "error reading bcrypt version" / 72-byte ValueError).
MAX_PASSWORD_BYTES = 72   # bcrypt's hard limit; longer inputs are rejected, never truncated


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        raise ValueError("password too long (max 72 bytes)")
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        raw = password.encode("utf-8")
        if len(raw) > MAX_PASSWORD_BYTES:
            return False
        return bcrypt.checkpw(raw, password_hash.encode("ascii"))
    except Exception:
        return False


def create_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "firm": user.firm,
        "iat": int(now.timestamp()),
        "exp": int((now + TOKEN_LIFETIME).timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


@dataclass
class Principal:
    """Who is calling. `user` is None for a partner API key."""
    role: str                     # "admin" | "firm"
    firm: Optional[str] = None    # firm key for role "firm"
    user: Optional[User] = None
    via_api_key: bool = False

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def can_access_firm(self, firm: Optional[str]) -> bool:
        return self.is_admin or (self.firm is not None and self.firm == (firm or "first_legal"))


def _partner_key_ok(api_key: Optional[str]) -> bool:
    if not api_key:
        return False
    return api_key in {k for k in (settings.IRL_CASE_API_KEY, settings.PROCLAIM_WEBHOOK_API_KEY) if k}


def _token_from(request: Request, creds: Optional[HTTPAuthorizationCredentials]) -> Optional[str]:
    if creds and creds.scheme.lower() == "bearer" and creds.credentials:
        return creds.credentials
    return request.query_params.get("token")  # download links


def _user_from_token(token: str, db: Session) -> User:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Session expired or invalid — please sign in again")
    user = db.get(User, int(payload.get("sub", 0)))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Account not found or disabled")
    # Password change invalidates tokens issued before it.
    if user.password_changed_at and payload.get("iat", 0) < int(user.password_changed_at.replace(tzinfo=timezone.utc).timestamp()):
        raise HTTPException(status_code=401, detail="Session expired — please sign in again")
    return user


def require_auth(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Security(_bearer),
    api_key: Optional[str] = Security(_api_key_header),
    db: Session = Depends(get_db),
) -> Principal:
    """Any signed-in user, or a partner API key."""
    token = _token_from(request, creds)
    if token:
        user = _user_from_token(token, db)
        return Principal(role=user.role, firm=user.firm, user=user)
    if _partner_key_ok(api_key):
        return Principal(role="admin", via_api_key=True)
    raise HTTPException(
        status_code=401,
        detail="Sign in required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_admin(principal: Principal = Depends(require_auth)) -> Principal:
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Admin access only")
    return principal


def require_user(principal: Principal = Depends(require_auth)) -> Principal:
    """A signed-in human (not an API key) — for password changes etc."""
    if principal.user is None:
        raise HTTPException(status_code=403, detail="User sign-in required")
    return principal


def assert_firm_access(principal: Principal, firm: Optional[str]) -> None:
    if not principal.can_access_firm(firm):
        raise HTTPException(status_code=403, detail="Not available for your firm")


def seed_admin_from_env(db: Session) -> None:
    """First-run bootstrap: if there are no users and ADMIN_EMAIL/ADMIN_PASSWORD
    are set, create the admin so the dashboard is usable straight after deploy."""
    if not (settings.ADMIN_EMAIL and settings.ADMIN_PASSWORD):
        return
    if db.query(User).count() > 0:
        return
    db.add(User(
        email=settings.ADMIN_EMAIL.lower().strip(),
        name="Admin",
        role="admin",
        password_hash=hash_password(settings.ADMIN_PASSWORD),
        is_active=True,
    ))
    db.commit()
