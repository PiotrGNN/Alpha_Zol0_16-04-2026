from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .audit import record_audit
from .database import get_db
from .dependencies import require_pro_user, require_user
from .entitlements import has_artifact_access, require_artifact, require_plan
from .models import Alert, ProductArtifact, SignalRecord, User

router = APIRouter(prefix="/resources", tags=["resources"])


class AlertRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    symbol: str = Field(min_length=3, max_length=40)
    condition: dict = Field(default_factory=dict)


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
        for row in db.query(SignalRecord).order_by(SignalRecord.observed_at.desc()).limit(1000):
            writer.writerow([row.symbol, row.strategy, row.side, row.confidence, row.observed_at.isoformat()])
    else:
        writer.writerow(["slug", "title", "resource_type", "required_plan", "created_at"])
        for row in db.query(ProductArtifact).filter(ProductArtifact.is_active.is_(True)):
            if has_artifact_access(db, user, row):
                writer.writerow([row.slug, row.title, row.resource_type, row.required_plan, row.created_at.isoformat()])
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
