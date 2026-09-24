"""Government portals directory, schemes, integration manager, change radar,
global search (spec §16, §17, §18, §25, §35)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..enums import (
    ChangeVerification,
    IntegrationStatus,
    Jurisdiction,
    SourceStatus,
)
from ..services import gov_integrations
from ..services import gov_manager
from ..services.audit import audit_event
from ..services.auth_service import (
    get_current_user,
    get_current_user_optional,
    project_access,
    request_id,
)
from ..services.portal_seed import list_states, search_portals, verify_portal
from ..services.scheme_engine import evaluate_scheme_criteria, list_schemes, match_schemes

router = APIRouter(tags=["government"])


# ═════════════════════════════════════════════════ PORTAL DIRECTORY ══
@router.get("/government-portals")
def portals(
    q: str | None = None,
    level: str | None = None,
    state_code: str | None = None,
    category: str | None = None,
    db: Session = Depends(get_db),
    user: models.User | None = Depends(get_current_user_optional),
) -> dict[str, Any]:
    rows = search_portals(db, q=q, level=level, state_code=state_code, category=category)
    cats = sorted({c for r in db.scalars(select(models.GovernmentPortal)).all() for c in (r.categories or [])})
    return {"portals": rows, "categories": cats, "states": list_states(),
            "notice": "Links open the official government website in a new tab. NIECP-AI is not affiliated with these portals; verification status and last-verified date are shown for each entry."}


@router.post("/government-portals/{portal_id}/verify")
def portal_verify(portal_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    if user.platform_role not in (models.PlatformRole.SYSTEM_ADMIN, models.PlatformRole.ORGANIZATION_ADMIN, models.PlatformRole.REVIEWER):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Portal verification is a reviewer/admin action.")
    portal = verify_portal(db, portal_id, user)
    if portal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Portal not found.")
    audit_event(db, action="portal.verify", action_category="SOURCE", user_id=user.id,
                resource_type="government_portal", resource_id=str(portal_id),
                after={"verification_status": "VERIFIED_GOV_SOURCE"}, commit=True)
    return {"ok": True, "id": portal.id, "last_verified_at": portal.last_verified_at.isoformat() if portal.last_verified_at else None}


# ═════════════════════════════════════════════════════════ SCHEMES ══
@router.get("/schemes")
def schemes(
    q: str | None = None,
    level: str | None = None,
    state_code: str | None = None,
    category: str | None = None,
    db: Session = Depends(get_db),
    user: models.User | None = Depends(get_current_user_optional),
) -> dict[str, Any]:
    from ..knowledge.data.scheme_data import SCHEME_CATEGORY_LABELS

    rows = list_schemes(db, q=q, level=level, state_code=state_code, category=category)
    return {
        "schemes": [
            {"id": s.id, "code": s.code, "name": s.name, "authority": s.authority, "ministry": s.ministry,
             "level": s.level.value if s.level else None, "state_code": s.state_code, "categories": s.categories or [],
             "short_description": s.short_description, "benefits": s.benefits or [],
             "eligibility_summary": s.eligibility_summary, "required_documents": s.required_documents or [],
             "application_process": s.application_process, "application_mode": s.application_mode,
             "official_url": s.official_url, "official_source_name": s.official_source_name,
             "verification_status": s.verification_status.value if s.verification_status else None,
             "last_verified_at": s.last_verified_at.isoformat() if s.last_verified_at else None}
            for s in rows
        ],
        "categories": SCHEME_CATEGORY_LABELS,
        "disclaimer": "NIECP-AI lists schemes from published sources and does not decide eligibility — the administering authority does. Use AI scheme matching on a project for a documented-criteria comparison.",
    }


@router.get("/projects/{project_id}/schemes")
def project_schemes(project_id: int, refresh: bool = False, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    results = match_schemes(db, project, actor=user) if refresh else evaluate_scheme_criteria(db, project)
    return {
        "matches": results,
        "disclaimer": "Each criterion is compared against your project profile using the scheme's documented conditions. Nothing here decides eligibility — apply through the official route and let the authority decide.",
    }


# ════════════════════════════════════════════════ INTEGRATION MANAGER ══
@router.get("/integrations")
def integrations(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    return {"integrations": gov_integrations.integration_status_payload(db)}


@router.get("/integration-registry")
def integration_registry(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """GovernmentIntegrationRegistry (Prompt §12/§23) — one authoritative row
    per provider service. `live` is never true without a real authorized
    connection; provider adapters for NSWS / TN SWS / API Setu are listed as
    PENDING / NOT_AUTHORIZED and are NOT activated."""
    if db.scalars(select(models.GovernmentIntegrationRegistry).limit(1)).first() is None:
        gov_manager.sync_registry(db)
    return {
        "registry": gov_manager.registry_payload(db),
        "declaration": (
            "No government API is live in this deployment. Providers marked PENDING or NOT_AUTHORIZED "
            "will be activated only after formal authorization from the provider. Until then NIECP-AI "
            "offers the official portal and manual workflows."
        ),
    }


@router.post("/integrations/{code}/health-check")
def integration_health(code: str, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    result = gov_integrations.health_check(db, code, actor=user)
    return result


@router.get("/integrations/{code}/logs")
def integration_logs(code: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    if user.platform_role not in (models.PlatformRole.SYSTEM_ADMIN, models.PlatformRole.ORGANIZATION_ADMIN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Integration logs are admin-only.")
    rows = db.scalars(select(models.IntegrationLog).where(models.IntegrationLog.integration_code == code).order_by(models.IntegrationLog.created_at.desc()).limit(50)).all()
    return {"logs": [
        {"id": r.id, "operation": r.operation, "result": r.result.value, "http_status": r.http_status,
         "latency_ms": r.latency_ms, "error_message": r.error_message,
         "created_at": r.created_at.isoformat() if r.created_at else None}
        for r in rows
    ]}


# ═════════════════════════════════════════════════ CHANGE RADAR ══
@router.get("/change-radar")
def change_radar(
    change_type: str | None = None,
    industry: str | None = None,
    state_code: str | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> dict[str, Any]:
    rows = db.scalars(select(models.RegulatoryChange).order_by(models.RegulatoryChange.detected_at.desc()).limit(100)).all()
    out = []
    for c in rows:
        if change_type and c.change_type.value != change_type:
            continue
        if state_code and c.affected_states and state_code not in c.affected_states:
            continue
        if industry and c.affected_industries and industry not in c.affected_industries:
            continue
        out.append({
            "id": c.id, "title": c.title, "change_type": c.change_type.value,
            "what_changed": c.what_changed, "who_may_be_affected": c.who_may_be_affected,
            "why_it_matters": c.why_it_matters, "recommended_review": c.recommended_review,
            "affected_categories": c.affected_categories or [], "affected_industries": c.affected_industries or [],
            "affected_states": c.affected_states or [], "source_url": c.source_url, "publisher": c.publisher,
            "published_on": c.published_on.isoformat() if c.published_on else None,
            "detected_at": c.detected_at.isoformat() if c.detected_at else None,
            "verification_status": c.verification_status.value if c.verification_status else None,
            "is_demo": c.is_demo,
        })
    return {"changes": out,
            "notice": "Entries are shown with their verification status. NIECP-AI does not present unverified reports as regulation — verified entries carry an official source and a reviewer."}


@router.post("/change-radar/{change_id}/review")
def review_change(change_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    if user.platform_role not in (models.PlatformRole.SYSTEM_ADMIN, models.PlatformRole.REVIEWER, models.PlatformRole.ORGANIZATION_ADMIN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Review is a reviewer/admin action.")
    change = db.get(models.RegulatoryChange, change_id)
    if change is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found.")
    change.verification_status = ChangeVerification.VERIFIED_OFFICIAL
    change.reviewed_by = user.id
    change.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    audit_event(db, action="change.review", action_category="SOURCE", user_id=user.id,
                resource_type="regulatory_change", resource_id=str(change_id), commit=True)
    return {"ok": True}


# ═════════════════════════════════════════════════ GLOBAL SEARCH ══
@router.get("/search")
def global_search(
    q: str = Query(min_length=2),
    project_id: int | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> dict[str, Any]:
    ql = q.lower().strip()
    results: dict[str, list[dict[str, Any]]] = {"approvals": [], "documents": [], "applications": [], "schemes": [], "portals": [], "projects": [], "knowledge": []}

    proj_rows = db.scalars(select(models.Project).where(
        (models.Project.created_by == user.id) | (models.Project.organization_id == user.organization_id))).all() if user.organization_id or True else []
    results["projects"] = [{"id": p.id, "name": p.name, "stage": p.stage.value if p.stage else None, "is_demo": p.is_demo}
                           for p in proj_rows if ql in p.name.lower()][:8]

    if project_id:
        project = project_access(db, user, project_id)
        for pa in db.scalars(select(models.ProjectApproval).where(models.ProjectApproval.project_id == project.id)):
            if ql in pa.name.lower() or ql in pa.authority.lower() or ql in (pa.template_code or "").lower():
                results["approvals"].append({"template_code": pa.template_code, "name": pa.name, "state": pa.node_state.value if pa.node_state else None})
        for d in db.scalars(select(models.Document).where(models.Document.project_id == project.id)):
            if ql in d.title.lower() or ql in d.original_filename.lower() or ql in (d.extracted_text_preview or "").lower():
                results["documents"].append({"id": d.id, "title": d.title, "category": d.category.value if d.category else None})
        for a in db.scalars(select(models.Application).where(models.Application.project_id == project.id)):
            if ql in a.title.lower() or ql in (a.official_reference or "").lower() or ql in (a.authority or "").lower():
                results["applications"].append({"id": a.id, "title": a.title, "status": a.status.value if a.status else None})

    for s in list_schemes(db, q=q):
        results["schemes"].append({"code": s.code, "name": s.name, "level": s.level.value if s.level else None})
    for p in search_portals(db, q=q, limit=6):
        results["portals"].append({"id": p["id"], "name": p["name"], "official_url": p["official_url"]})

    from ..ai.retrieval import retrieve

    for chunk in retrieve(db, q, project_id=project_id, top_k=4, include_project_docs=bool(project_id)):
        results["knowledge"].append(chunk.citation_dict())

    total = sum(len(v) for v in results.values())
    return {"query": q, "total": total, "results": results}
