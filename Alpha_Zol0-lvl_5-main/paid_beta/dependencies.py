from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .entitlements import require_plan
from .models import User
from .security import decode_token


def require_user(
    authorization: str | None = Header(default=None), db: Session = Depends(get_db)
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
        )
    try:
        claims = decode_token(authorization[7:], secret=settings.token_secret)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    user = db.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="inactive user",
        )
    if int(user.token_version or 0) != claims.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="session revoked",
        )
    return user


def require_paid_user(
    user: User = Depends(require_user), db: Session = Depends(get_db)
) -> User:
    require_plan(db, user, "starter")
    return user


def require_pro_user(
    user: User = Depends(require_user), db: Session = Depends(get_db)
) -> User:
    require_plan(db, user, "pro")
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin role required",
        )
    return user
