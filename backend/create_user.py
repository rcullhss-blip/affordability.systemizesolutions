#!/usr/bin/env python3
"""
Create or reset a dashboard/portal user directly against the database.

  python create_user.py admin rob@example.com 'StrongPassword123'
  python create_user.py firm  someone@barings.law 'StrongPassword123' --firm barings
  python create_user.py reset someone@barings.law 'NewPassword456'

Needs DATABASE_URL in the environment (or backend/.env). On Render, run it from
the service Shell; locally point DATABASE_URL at the external connection string.
Normally you won't need this — admins manage users from the dashboard (/users)
and the first admin is seeded from ADMIN_EMAIL / ADMIN_PASSWORD on startup.
"""
import sys
from datetime import datetime

from app.core.database import SessionLocal
from app.core.auth import hash_password
from app.models.tables import User


def main(argv):
    if len(argv) < 3:
        print(__doc__); sys.exit(1)
    mode, email, password = argv[0], argv[1].lower().strip(), argv[2]
    firm = argv[argv.index("--firm") + 1] if "--firm" in argv else None
    if len(password) < 10:
        sys.exit("password must be at least 10 characters")
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == email).first()
        if mode == "reset":
            if not u: sys.exit(f"no user {email}")
            u.password_hash = hash_password(password); u.password_changed_at = datetime.utcnow(); u.is_active = True
            db.commit(); print(f"password reset for {email}"); return
        if mode not in ("admin", "firm"):
            sys.exit("mode must be admin | firm | reset")
        if mode == "firm" and not firm:
            sys.exit("--firm <key> is required for a firm user")
        if u:
            sys.exit(f"{email} already exists — use 'reset' to change the password")
        db.add(User(email=email, role=mode, firm=firm if mode == "firm" else None,
                    password_hash=hash_password(password), is_active=True))
        db.commit(); print(f"created {mode} user {email}" + (f" (firm={firm})" if firm else ""))
    finally:
        db.close()


if __name__ == "__main__":
    main(sys.argv[1:])
