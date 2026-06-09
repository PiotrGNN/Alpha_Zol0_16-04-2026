from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from .audit import record_audit
from .config import settings
from .database import get_db
from .mailer import send_password_reset
from .models import PasswordResetToken, User
from .security import generate_reset_token, hash_password, hash_reset_token

router = APIRouter(prefix="/auth/password-reset", tags=["auth"])


class ResetRequest(BaseModel):
    email: EmailStr


class ResetConfirm(BaseModel):
    token: str
    new_password: str


@router.post("/request", status_code=202)
def request_reset(request: ResetRequest, db: Session = Depends(get_db)):
    response: dict[str, object] = {"accepted": True}
    user = (
        db.query(User)
        .filter(User.email == request.email.lower(), User.is_active.is_(True))
        .one_or_none()
    )
    if user is None:
        return response

    now = datetime.now(timezone.utc)
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).update({PasswordResetToken.used_at: now}, synchronize_session=False)

    raw_token = generate_reset_token()
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_reset_token(raw_token),
            expires_at=now + timedelta(seconds=settings.password_reset_ttl_seconds),
        )
    )
    record_audit(db, action="auth.password_reset_requested", user_id=user.id)
    db.commit()

    try:
        send_password_reset(
            email=user.email,
            reset_url=f"{settings.app_url}/reset-password?token={raw_token}",
        )
    except Exception as exc:
        record_audit(
            db,
            action="auth.password_reset_delivery_failed",
            user_id=user.id,
            metadata={"error_type": type(exc).__name__},
            commit=True,
        )
        if settings.is_production:
            raise HTTPException(status_code=503, detail="password reset unavailable") from exc

    if settings.expose_password_reset_token:
        response["reset_token"] = raw_token
    return response


@router.post("/confirm")
def confirm_reset(request: ResetConfirm, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    reset = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == hash_reset_token(request.token))
        .one_or_none()
    )
    if reset is None or reset.used_at is not None:
        raise HTTPException(status_code=400, detail="invalid or used reset token")

    expires_at = reset.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        raise HTTPException(status_code=400, detail="reset token expired")

    user = db.get(User, reset.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=400, detail="invalid reset token")

    user.password_hash = hash_password(request.new_password)
    user.token_version = int(user.token_version or 0) + 1
    reset.used_at = now
    record_audit(db, action="auth.password_reset_completed", user_id=user.id)
    db.commit()
    return {"reset": True}
