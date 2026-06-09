from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .audit import record_audit
from .config import settings
from .database import get_db
from .dependencies import require_user
from .entitlements import active_plan_code
from .models import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/logout", status_code=204)
def logout(user: User = Depends(require_user), db: Session = Depends(get_db)):
    user.token_version = int(user.token_version or 0) + 1
    record_audit(db, action="auth.logout", user_id=user.id)
    db.commit()
    return None


@router.get("/session")
def session_info(user: User = Depends(require_user), db: Session = Depends(get_db)):
    return {
        "user_id": user.id,
        "active_plan": active_plan_code(db, user.id),
        "session_ttl_seconds": settings.token_ttl_seconds,
        "token_version": int(user.token_version or 0),
    }
