from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .audit import record_audit
from .database import get_db
from .dependencies import require_admin, require_pro_user, require_user
from .entitlements import has_artifact_access, require_artifact, require_plan
from .models import Alert, ProductArtifact, SignalRecord, User

router = APIRouter(prefix="/resources", tags=["resources"])


class AlertRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    symbol: str = Field(min_length=3, max_length=40)
    condition: dict = Field(default_factory=dict)


class ArtifactPublishRequest(BaseModel):
    slug: str = Field(min_length=3, max_length=160, pattern=r"^[a-z0-9][a-z0-9-]+$")
    title: str = Field(min_length=3, max_length=240)
    resource_type: str
    required_plan: str
    summary: str = Field(default="", max_length=2000)
    content: dict = Field(default_factory=dict)


class SignalPublishRequest(BaseModel):
    symbol: str = Field(min_length=3, max_length=40)
    strategy: str = Field(min_length=1, max_length=80)
    side: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: dict = Field(default_factory=dict)
    observed_at: datetime | None = None


def _artifact_payload(artifact: ProductArtifact, *, include_content: bool) -> dict:
    payload = {
        "slug": artifact.slug,
        "title": artifact.title,
        "resource_type": artifact.resource_type,
        "required_plan": artifact.required_plan,
        "summary": artifact.summary,
        "created_at": artifact.created_at.isoformat(),
    }
    if include_content:
        payload["content"] = json.loads(artifact.content or "{}")
    return payload


@router.get("/catalog")
def catalog(user: User = Depends(require_user), db: Session = Depends(get_db)):
    artifacts = (
        db.query(ProductArtifact)
        .filter(ProductArtifact.is_active.is_(True))
        .order_by(ProductArtifact.created_at.desc(), ProductArtifact.id.desc())
        .all()
    )
    return [
        {
            **_artifact_payload(item, include_content=False),
            "accessible": has_artifact_access(db, user, item),
        }
        for item in artifacts
    ]


@router.get("/artifacts/{slug}")
def artifact_detail(
    slug: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    artifact = (
        db.query(ProductArtifact)
        .filter(ProductArtifact.slug == slug, ProductArtifact.is_active.is_(True))
        .one_or_none()
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    require_artifact(db, user, artifact)
    record_audit(
        db,
        action="resource.artifact_viewed",
        user_id=user.id,
        resource_type=artifact.resource_type,
        resource_id=artifact.slug,
    )
    db.commit()
    return _artifact_payload(artifact, include_content=True)


@router.get("/signals")
def signal_history(
    limit: int = 50,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    require_plan(db, user, "starter")
    limit = max(1, min(limit, 200))
    rows = (
        db.query(SignalRecord)
        .order_by(SignalRecord.observed_at.desc(), SignalRecord.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": row.id,
            "symbol": row.symbol,
            "strategy": row.strategy,
            "side": row.side,
            "confidence": float(row.confidence) if row.confidence is not None else None,
            "evidence": json.loads(row.evidence or "{}"),
            "observed_at": row.observed_at.isoformat(),
        }
        for row in rows
    ]


@router.post("/alerts", status_code=201)
def create_alert(
    request: AlertRequest,
    user: User = Depends(require_pro_user),
    db: Session = Depends(get_db),
):
    alert = Alert(
        user_id=user.id,
        name=request.name.strip(),
        symbol=request.symbol.upper().strip(),
        condition=json.dumps(request.condition, sort_keys=True),
    )
    db.add(alert)
    db.flush()
    record_audit(
        db,
        action="resource.alert_created",
        user_id=user.id,
        resource_type="alert",
        resource_id=alert.id,
    )
    db.commit()
    db.refresh(alert)
    return {"id": alert.id, "name": alert.name, "symbol": alert.symbol, "active": True}


@router.get("/alerts")
def list_alerts(
    user: User = Depends(require_pro_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Alert)
        .filter(Alert.user_id == user.id)
        .order_by(Alert.created_at.desc(), Alert.id.desc())
        .all()
    )
    return [
        {
            "id": row.id,
            "name": row.name,
            "symbol": row.symbol,
            "condition": json.loads(row.condition or "{}"),
            "active": bool(row.is_active),
        }
        for row in rows
    ]


@router.get("/export/{resource_type}")
def export_resources(
    resource_type: str,
    user: User = Depends(require_pro_user),
    db: Session = Depends(get_db),
):
    if resource_type not in {"signals", "artifacts"}:
        raise HTTPException(status_code=404, detail="unsupported export")
    output = io.StringIO()
    writer = csv.writer(output)
    if resource_type == "signals":
        writer.writerow(["symbol", "strategy", "side", "confidence", "observed_at"])
        for row in (
            db.query(SignalRecord)
            .order_by(SignalRecord.observed_at.desc())
            .limit(1000)
        ):
            writer.writerow(
                [
                    row.symbol,
                    row.strategy,
                    row.side,
                    row.confidence,
                    row.observed_at.isoformat(),
                ]
            )
    else:
        writer.writerow(["slug", "title", "resource_type", "required_plan", "created_at"])
        for row in db.query(ProductArtifact).filter(ProductArtifact.is_active.is_(True)):
            if has_artifact_access(db, user, row):
                writer.writerow(
                    [
                        row.slug,
                        row.title,
                        row.resource_type,
                        row.required_plan,
                        row.created_at.isoformat(),
                    ]
                )
    record_audit(
        db,
        action="resource.exported",
        user_id=user.id,
        resource_type=resource_type,
        metadata={"generated_at": datetime.now(timezone.utc).isoformat()},
    )
    db.commit()
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="zol0-{resource_type}.csv"'},
    )


@router.post("/admin/artifacts", status_code=201)
def publish_artifact(
    request: ArtifactPublishRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if request.resource_type not in {"report", "backtest"}:
        raise HTTPException(status_code=400, detail="unsupported artifact type")
    if request.required_plan not in {"starter", "pro", "one_time"}:
        raise HTTPException(status_code=400, detail="unsupported entitlement")
    artifact = ProductArtifact(
        slug=request.slug,
        title=request.title.strip(),
        resource_type=request.resource_type,
        required_plan=request.required_plan,
        summary=request.summary.strip(),
        content=json.dumps(request.content, sort_keys=True),
    )
    db.add(artifact)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="artifact slug already exists") from exc
    record_audit(
        db,
        action="admin.artifact_published",
        user_id=admin.id,
        resource_type=request.resource_type,
        resource_id=request.slug,
    )
    db.commit()
    return _artifact_payload(artifact, include_content=True)


@router.delete("/admin/artifacts/{slug}", status_code=204)
def deactivate_artifact(
    slug: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    artifact = db.query(ProductArtifact).filter(ProductArtifact.slug == slug).one_or_none()
    if artifact is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    artifact.is_active = False
    record_audit(
        db,
        action="admin.artifact_deactivated",
        user_id=admin.id,
        resource_type=artifact.resource_type,
        resource_id=artifact.slug,
    )
    db.commit()
    return None


@router.post("/admin/signals", status_code=201)
def publish_signal(
    request: SignalPublishRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    side = request.side.lower().strip()
    if side not in {"buy", "sell", "neutral"}:
        raise HTTPException(status_code=400, detail="unsupported signal side")
    observed_at = request.observed_at or datetime.now(timezone.utc)
    signal = SignalRecord(
        symbol=request.symbol.upper().strip(),
        strategy=request.strategy.strip(),
        side=side,
        confidence=request.confidence,
        evidence=json.dumps(request.evidence, sort_keys=True),
        observed_at=observed_at,
    )
    db.add(signal)
    db.flush()
    record_audit(
        db,
        action="admin.signal_published",
        user_id=admin.id,
        resource_type="signal",
        resource_id=signal.id,
    )
    db.commit()
    return {
        "id": signal.id,
        "symbol": signal.symbol,
        "strategy": signal.strategy,
        "side": signal.side,
        "observed_at": signal.observed_at.isoformat(),
    }
