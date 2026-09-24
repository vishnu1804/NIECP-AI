"""PWA manifest, service worker, offline sync (spec §40)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..enums import SyncConflictResolution
from ..services.auth_service import get_current_user, request_id
from ..services.audit import audit_event
from ..services.pwa import asset_hashes, build_manifest, service_worker_version

router = APIRouter(tags=["pwa"])


@router.get("/manifest.webmanifest")
def manifest() -> JSONResponse:
    return JSONResponse(build_manifest(), media_type="application/manifest+json")


@router.get("/sw-version")
def sw_version() -> dict[str, Any]:
    return {"version": service_worker_version(), "assets": len(asset_hashes())}


# ═════════════════════════════════════════════════════ OFFLINE SYNC ══
class SyncPushItem(BaseModel):
    client_id: str
    entity_type: str
    entity_id: str
    operation: str = "UPSERT"
    payload: dict[str, Any] = Field(default_factory=dict)
    client_updated_at: str | None = None
    base_version: int | None = None


class SyncPush(BaseModel):
    items: list[SyncPushItem]


SYNCABLE_ENTITIES = {"ComplianceTask", "ProjectProfile", "Project", "GovernmentQuery", "Renewal", "Inspection", "Application"}


@router.post("/sync/push")
def sync_push(body: SyncPush, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """Queue offline changes. Conflicts are stored for user resolution — nothing
    is silently overwritten (spec §40)."""
    from ..models_mixins import utcnow

    results = []
    for item in body.items:
        if item.entity_type not in SYNCABLE_ENTITIES:
            results.append({"client_id": item.client_id, "state": "REJECTED",
                            "reason": f"Entity type {item.entity_type} is not synchronizable"})
            continue
        server_row = None
        try:
            model = getattr(models, item.entity_type)
            server_row = db.get(model, int(item.entity_id)) if str(item.entity_id).isdigit() else None
        except (AttributeError, ValueError):
            server_row = None

        conflict_fields: list[str] = []
        server_updated = getattr(server_row, "updated_at", None) if server_row is not None else None
        if server_row is not None and server_updated is not None and item.client_updated_at:
            try:
                client_dt = datetime.fromisoformat(item.client_updated_at.replace("Z", ""))
                if server_updated.replace(tzinfo=None) > client_dt.replace(tzinfo=None):
                    conflict_fields = sorted(set((item.payload or {}).keys()) & {c.name for c in server_row.__table__.columns if c.name not in ("id", "created_at", "updated_at")})
            except ValueError:
                pass

        record = models.SyncRecord(
            user_id=user.id,
            project_id=None,
            entity_type=item.entity_type,
            entity_id=str(item.entity_id),
            client_id=item.client_id,
            operation=item.operation,
            payload=item.payload,
            server_snapshot={},
            client_updated_at=utcnow(),
            base_version=item.base_version,
            state="CONFLICT" if conflict_fields else "PENDING",
            conflict_fields=conflict_fields,
        )
        db.add(record)
        db.flush()
        results.append({
            "client_id": item.client_id, "sync_record_id": record.id,
            "state": record.state,
            "conflict_fields": conflict_fields,
            "message": (
                "Your offline version and server version are different. Choose Keep Local, Keep Server or Review Changes."
                if conflict_fields else "Queued for apply."
            ),
        })
    db.commit()
    return {"ok": True, "results": results}


@router.get("/sync/pending")
def sync_pending(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    rows = db.scalars(select(models.SyncRecord).where(
        models.SyncRecord.user_id == user.id, models.SyncRecord.state.in_(["PENDING", "CONFLICT"]))).all()
    return {"records": [
        {"id": r.id, "entity_type": r.entity_type, "entity_id": r.entity_id, "client_id": r.client_id,
         "state": r.state, "conflict_fields": r.conflict_fields or [], "payload": r.payload,
         "operation": r.operation, "client_updated_at": r.client_updated_at.isoformat() if r.client_updated_at else None}
        for r in rows
    ]}


class SyncResolve(BaseModel):
    sync_record_id: int
    resolution: SyncConflictResolution


@router.post("/sync/resolve")
def sync_resolve(body: SyncResolve, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    record = db.get(models.SyncRecord, body.sync_record_id)
    if record is None or record.user_id != user.id:
        return JSONResponse(status_code=404, content={"detail": "Sync record not found."})
    record.resolution = body.resolution
    if body.resolution == SyncConflictResolution.KEEP_LOCAL:
        record.state = "APPLIED_LOCAL"
        # apply payload onto the entity
        try:
            model = getattr(models, record.entity_type)
            row = db.get(model, int(record.entity_id))
            if row is not None:
                for key, value in (record.payload or {}).items():
                    if hasattr(row, key) and key not in ("id", "created_at"):
                        setattr(row, key, value)
        except (AttributeError, ValueError):
            pass
    elif body.resolution == SyncConflictResolution.KEEP_SERVER:
        record.state = "APPLIED_SERVER"
    elif body.resolution == SyncConflictResolution.REVIEW:
        record.state = "REVIEWING"
    record.applied_at = datetime.utcnow() if body.resolution != SyncConflictResolution.REVIEW else None
    audit_event(db, action="sync.resolve", action_category="SYNC", user_id=user.id,
                resource_type="sync_record", resource_id=str(record.id),
                details={"resolution": body.resolution.value, "entity": record.entity_type}, commit=True)
    return {"ok": True, "state": record.state}


@router.get("/sync/bundle")
def sync_bundle(project_id: int | None = None, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """Offline bundle: project drafts, checklists, profile basics, doc metadata,
    tasks — the data offline mode caches (spec §40)."""
    from fastapi import HTTPException

    from ..services.next_action import todays_tasks

    if project_id is None:
        stmt = select(models.Project).where(models.Project.is_archived.is_(False))
        if user.platform_role != models.PlatformRole.SYSTEM_ADMIN:
            stmt = stmt.where((models.Project.created_by == user.id) | (models.Project.organization_id == user.organization_id))
        projects = db.scalars(stmt).all()
        return {"projects": [{"id": p.id, "name": p.name, "stage": p.stage.value if p.stage else None} for p in projects]}
    from ..services.auth_service import project_access

    project = project_access(db, user, project_id)
    profile = project.profile
    tasks = db.scalars(select(models.ComplianceTask).where(models.ComplianceTask.project_id == project.id)).all()
    docs = db.scalars(select(models.Document).where(models.Document.project_id == project.id)).all()
    return {
        "project": {"id": project.id, "name": project.name, "stage": project.stage.value if project.stage else None},
        "profile": {c.name: str(getattr(profile, c.name)) for c in models.ProjectProfile.__table__.columns
                    if c.name not in ("id", "project_id", "created_at", "updated_at")} if profile else {},
        "tasks": [{"id": t.id, "title": t.title, "status": t.status.value, "due_date": t.due_date.isoformat() if t.due_date else None} for t in tasks],
        "document_metadata": [{"id": d.id, "title": d.title, "category": d.category.value if d.category else None,
                               "status": d.status.value, "expiry_date": d.expiry_date.isoformat() if d.expiry_date else None} for d in docs],
        "today": todays_tasks(db, project),
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }
