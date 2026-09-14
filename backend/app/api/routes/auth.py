"""Sign-in and user management."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import (
    Principal, create_token, hash_password, verify_password,
    require_admin, require_user, MAX_PASSWORD_BYTES,
)


def _check_new_password(pw: str) -> None:
    if len(pw) < 10:
        raise HTTPException(status_code=400, detail="Password must be at least 10 characters")
    if len(pw.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise HTTPException(status_code=400, detail="Password must be 72 characters or fewer")
from app.core.database import get_db
from app.models.tables import User

router = APIRouter()

FIRMS = ("first_legal", "barings", "accord", "ryans", "tr_sols", "jf_law", "woodville")


def _public(u: User) -> dict:
    return {
        "id": u.id, "email": u.email, "name": u.name, "role": u.role, "firm": u.firm,
        "is_active": u.is_active,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    email = body.email.lower().strip()
    if "@" not in email:
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    user = db.query(User).filter(User.email == email).first()
    # Same message for unknown email / wrong password / disabled account.
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    user.last_login_at = datetime.utcnow()
    db.commit()
    return {"token": create_token(user), "user": _public(user)}


@router.get("/me")
def me(p: Principal = Depends(require_user)):
    return _public(p.user)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password")
def change_password(body: ChangePasswordIn, p: Principal = Depends(require_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, p.user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    _check_new_password(body.new_password)
    p.user.password_hash = hash_password(body.new_password)
    p.user.password_changed_at = datetime.utcnow()
    db.commit()
    # The caller's own token is now stale — hand back a fresh one.
    return {"ok": True, "token": create_token(p.user)}


# ── Admin: user management ────────────────────────────────────────────────────

class UserIn(BaseModel):
    email: str
    password: str
    name: Optional[str] = None
    role: str = "firm"            # "admin" | "firm"
    firm: Optional[str] = None    # required for role "firm"


@router.get("/users", dependencies=[Depends(require_admin)])
def list_users(db: Session = Depends(get_db)):
    return [_public(u) for u in db.query(User).order_by(User.role, User.email).all()]


@router.post("/users", dependencies=[Depends(require_admin)], status_code=201)
def create_user(body: UserIn, db: Session = Depends(get_db)):
    if body.role not in ("admin", "firm"):
        raise HTTPException(status_code=400, detail="role must be 'admin' or 'firm'")
    if body.role == "firm" and body.firm not in FIRMS:
        raise HTTPException(status_code=400, detail=f"firm must be one of {', '.join(FIRMS)}")
    _check_new_password(body.password)
    email = body.email.lower().strip()
    if "@" not in email or " " in email:
        raise HTTPException(status_code=400, detail="Enter a valid email address")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="A user with that email already exists")
    u = User(
        email=email, name=body.name, role=body.role,
        firm=body.firm if body.role == "firm" else None,
        password_hash=hash_password(body.password), is_active=True,
    )
    db.add(u)
    db.commit()
    return _public(u)


class ResetPasswordIn(BaseModel):
    new_password: str


@router.post("/users/{user_id}/reset-password", dependencies=[Depends(require_admin)])
def reset_password(user_id: int, body: ResetPasswordIn, db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    _check_new_password(body.new_password)
    u.password_hash = hash_password(body.new_password)
    u.password_changed_at = datetime.utcnow()   # signs that user out everywhere
    db.commit()
    return {"ok": True}


@router.post("/users/{user_id}/deactivate")
def deactivate_user(user_id: int, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if p.user and p.user.id == u.id:
        raise HTTPException(status_code=400, detail="You can't deactivate your own account")
    u.is_active = False
    db.commit()
    return {"ok": True}


@router.post("/users/{user_id}/activate", dependencies=[Depends(require_admin)])
def activate_user(user_id: int, db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    u.is_active = True
    db.commit()
    return {"ok": True}
