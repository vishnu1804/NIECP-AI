"""Projects, onboarding, Master Project Profile, dynamic questionnaire,
AI analysis, approvals, dependency graph, readiness, next-best-actions."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..enums import (
    Applicability,
    ApprovalNodeState,
    ProjectStage,
    ProjectType,
    SourceStatus,
)
from ..services import readiness as readiness_service
from ..services.approval_engine import get_critical_path, graph_payload, run_discovery
from ..services.audit import audit_event
from ..services.auth_service import (
    client_ip,
    get_current_user,
    project_access,
    request_id,
    user_agent,
)
from ..services.next_action import next_best_actions, todays_tasks
from ..services.profile_facts import build_facts, label_for
from ..services.questionnaire import build_questionnaire, save_answers

router = APIRouter(tags=["projects"])


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "project").lower()).strip("-")
    return slug[:80] or "project"


def _project_payload(project: models.Project, db: Session) -> dict[str, Any]:
    profile = project.profile
    counts = {
        "approvals_applies": db.scalar(select(func.count(models.ProjectApproval.id)).where(
            models.ProjectApproval.project_id == project.id, models.ProjectApproval.applicability == Applicability.APPLIES)) or 0,
        "approvals_conditional": db.scalar(select(func.count(models.ProjectApproval.id)).where(
            models.ProjectApproval.project_id == project.id, models.ProjectApproval.applicability == Applicability.CONDITIONAL)) or 0,
        "documents": db.scalar(select(func.count(models.Document.id)).where(models.Document.project_id == project.id)) or 0,
        "applications": db.scalar(select(func.count(models.Application.id)).where(models.Application.project_id == project.id)) or 0,
        "open_tasks": db.scalar(select(func.count(models.ComplianceTask.id)).where(
            models.ComplianceTask.project_id == project.id,
            models.ComplianceTask.status.in_([models.TaskStatus.OPEN, models.TaskStatus.BLOCKED]))) or 0,
    }
    return {
        "id": project.id,
        "name": project.name,
        "slug": project.slug,
        "description": project.description,
        "stage": project.stage.value if project.stage else None,
        "is_demo": project.is_demo,
        "is_archived": project.is_archived,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "last_ai_analysis_at": project.last_ai_analysis_at.isoformat() if project.last_ai_analysis_at else None,
        "readiness_overall": (project.readiness_snapshot or {}).get("overall"),
        "profile_complete": profile is not None,
        "industry": (profile.industry_code if profile else None),
        "state": (profile.state_code if profile else None),
        "counts": counts,
    }


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=240)
    description: str | None = None
    stage: ProjectStage = ProjectStage.IDEA


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=240)
    description: str | None = None
    stage: ProjectStage | None = None
    is_archived: bool | None = None


class ProfileIn(BaseModel):
    """Master Project Profile — partial updates allowed (spec §4)."""

    # organisation
    organization_name: str | None = None
    applicant_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    organization_type: str | None = None
    enterprise_class: str | None = None
    pan: str | None = None
    gstin: str | None = None
    cin: str | None = None
    udyam_number: str | None = None
    startup_dpiit_number: str | None = None
    is_startup_recognized: bool | None = None
    is_export_oriented: bool | None = None
    # project
    project_type: str | None = None
    industry_code: str | None = None
    industry_other_description: str | None = None
    sub_industry: str | None = None
    project_stage: str | None = None
    # location
    state_code: str | None = None
    district: str | None = None
    city_village: str | None = None
    industrial_area: str | None = None
    in_notified_industrial_area: bool | None = None
    land_tenure: str | None = None
    land_area_sqm: float | None = None
    built_up_area_sqm: float | None = None
    survey_number: str | None = None
    zoning_classification: str | None = None
    is_coastal_regulation_zone: bool | None = None
    is_eco_sensitive_zone: bool | None = None
    is_forest_land: bool | None = None
    # investment
    total_investment: float | None = None
    land_investment: float | None = None
    building_investment: float | None = None
    machinery_investment: float | None = None
    annual_turnover: float | None = None
    working_capital: float | None = None
    employment_generated: int | None = None
    women_employed: int | None = None
    # operations
    production_type: str | None = None
    production_capacity: str | None = None
    raw_materials: list[str] | None = None
    chemicals_used: list[str] | None = None
    hazardous_substances: list[str] | None = None
    uses_hazardous_chemicals: bool | None = None
    is_mah_directed: bool | None = None
    water_consumption_kld: float | None = None
    wastewater_generated_kld: float | None = None
    has_etp: bool | None = None
    has_stp: bool | None = None
    air_emissions_present: bool | None = None
    emission_sources: list[str] | None = None
    has_boiler: bool | None = None
    boiler_capacity_tph: float | None = None
    has_dg_set: bool | None = None
    dg_set_kva: float | None = None
    fire_risk_level: str | None = None
    electrical_load_kw: float | None = None
    htaht_connection_required: bool | None = None
    e_waste_generated: bool | None = None
    plastic_waste_generated: bool | None = None
    hazardous_waste_generated: bool | None = None
    hazardous_waste_tpa: float | None = None
    solid_waste_generated: bool | None = None
    biomedical_waste_generated: bool | None = None
    construction_demolition_waste: bool | None = None
    battery_waste_generated: bool | None = None
    uses_batteries: bool | None = None
    workers_on_site: int | None = None
    buys_from_msme_suppliers: bool | None = None
    is_factory_under_factories_act: bool | None = None
    operates_in_shifts: bool | None = None
    uses_contract_labour: bool | None = None
    # business
    domestic_sales_annual: float | None = None
    export_annual: float | None = None
    import_annual: float | None = None
    number_of_employees: int | None = None
    power_requirement_kw: float | None = None
    water_requirement_kld: float | None = None


class AnswersIn(BaseModel):
    answers: list[dict[str, Any]]


# ─────────────────────────────────────────────────────────────── CRUD ──
@router.get("/projects")
def list_projects(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    stmt = select(models.Project).where(models.Project.is_archived.is_(False))
    if user.platform_role != models.PlatformRole.SYSTEM_ADMIN:
        stmt = stmt.where(
            (models.Project.created_by == user.id)
            | (models.Project.organization_id == user.organization_id)
        )
    rows = db.scalars(stmt.order_by(models.Project.updated_at.desc())).all()
    return {"projects": [_project_payload(p, db) for p in rows]}


@router.post("/projects", status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectCreate, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = models.Project(
        name=body.name.strip(),
        slug=_slugify(body.name),
        description=body.description,
        organization_id=user.organization_id,
        created_by=user.id,
        stage=body.stage,
    )
    db.add(project)
    db.flush()
    db.add(models.ProjectProfile(project_id=project.id))
    audit_event(db, action="project.create", action_category="PROJECT", user_id=user.id, user_email=user.email,
                project_id=project.id, resource_type="project", resource_id=str(project.id),
                after={"name": project.name}, ip_address=client_ip(request), commit=True)
    return {"ok": True, "project": _project_payload(project, db)}


@router.get("/projects/{project_id}")
def get_project(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    payload = _project_payload(project, db)
    payload["next_actions"] = [{**a, "link": (a["link"] or "").replace("{pid}", str(project.id))} for a in next_best_actions(db, project)]
    payload["today"] = todays_tasks(db, project)
    return payload


@router.patch("/projects/{project_id}")
def update_project(project_id: int, body: ProjectUpdate, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    before = {"name": project.name, "stage": str(project.stage)}
    if body.name is not None:
        project.name = body.name.strip()
        project.slug = _slugify(body.name)
    if body.description is not None:
        project.description = body.description
    if body.stage is not None:
        project.stage = body.stage
    if body.is_archived is not None:
        project.is_archived = body.is_archived
    audit_event(db, action="project.update", action_category="PROJECT", user_id=user.id, project_id=project.id,
                resource_type="project", resource_id=str(project.id), before=before,
                after={"name": project.name, "stage": str(project.stage)}, commit=True)
    return {"ok": True, "project": _project_payload(project, db)}


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    audit_event(db, action="project.delete", action_category="PROJECT", user_id=user.id, project_id=project.id,
                resource_type="project", resource_id=str(project.id), before={"name": project.name}, commit=True)
    project.is_archived = True
    db.commit()
    return {"ok": True, "archived": True}


# ──────────────────────────────────────────────────── profile & wizard ──
@router.get("/projects/{project_id}/profile")
def get_profile(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    profile = project.profile
    if profile is None:
        return {"profile": {}, "facts": {}, "industry_code": None}
    data = {}
    for column in models.ProjectProfile.__table__.columns:
        if column.name in ("id", "project_id", "created_at", "updated_at"):
            continue
        value = getattr(profile, column.name)
        if hasattr(value, "value"):
            value = value.value
        elif isinstance(value, datetime):
            value = value.isoformat()
        data[column.name] = value
    facts = build_facts(project, profile)
    return {
        "profile": data,
        "industry_code": profile.industry_code,
        "derived": {
            "is_manufacturing": facts.get("_is_manufacturing"),
            "food_related": facts.get("_food_related"),
            "question_sets": facts.get("_derived_question_sets"),
            "industry_name": facts.get("_industry_name"),
        },
    }


@router.patch("/projects/{project_id}/profile")
def update_profile(project_id: int, body: ProfileIn, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    profile = project.profile
    if profile is None:
        profile = models.ProjectProfile(project_id=project.id)
        db.add(profile)
        db.flush()
    changed: dict[str, Any] = {}
    for field, value in body.model_dump(exclude_unset=True).items():
        enum_map = {
            "organization_type": models.OrganizationType, "enterprise_class": models.EnterpriseClass,
            "project_type": models.ProjectType, "project_stage": models.ProjectStage, "land_tenure": models.LandTenure,
        }
        if field in enum_map and value is not None:
            try:
                value = enum_map[field](value)
            except ValueError:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Invalid value for {field}: {value}")
        before = getattr(profile, field, None)
        if hasattr(before, "value"):
            before = before.value
        if before != value:
            changed[field] = {"before": before, "after": str(value) if hasattr(value, "value") else value}
        setattr(profile, field, value)
    db.flush()
    if changed:
        audit_event(db, action="profile.update", action_category="PROFILE", user_id=user.id, project_id=project.id,
                    resource_type="project_profile", resource_id=str(profile.id), before={k: v["before"] for k, v in changed.items()},
                    after={k: v["after"] for k, v in changed.items()}, ip_address=client_ip(request), commit=True)
    return {"ok": True, "changed": list(changed.keys())}


@router.get("/projects/{project_id}/questionnaire")
def get_questionnaire(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    return build_questionnaire(db, project)


@router.post("/projects/{project_id}/questionnaire")
def post_answers(project_id: int, body: AnswersIn, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    saved = save_answers(db, project, body.answers, user)
    audit_event(db, action="questionnaire.answers", action_category="PROFILE", user_id=user.id,
                project_id=project.id, resource_type="questionnaire", details={"saved": saved},
                ip_address=client_ip(request), commit=True)
    return {"ok": True, "saved": saved, "questionnaire": build_questionnaire(db, project)}


# ───────────────────────────────────────────── AI analysis & approvals ──
@router.post("/projects/{project_id}/analysis")
def run_analysis(project_id: int, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    profile = project.profile
    if profile is None or not (profile.industry_code or profile.industry_other_description):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Set the industry first (Basic project information), then run the analysis.")
    summary = run_discovery(db, project, actor=user, user_agent=user_agent(request), request_id=request_id(request))
    readiness_service.compute_readiness(db, project)
    approvals = db.scalars(select(models.ProjectApproval).where(models.ProjectApproval.project_id == project.id)).all()
    applies = [
        {
            "template_code": pa.template_code,
            "name": pa.name,
            "category": pa.category.value if pa.category else None,
            "authority": pa.authority,
            "applicability": pa.applicability.value,
            "node_state": pa.node_state.value,
            "confidence": pa.confidence.value if pa.confidence else None,
            "source_status": pa.source_status.value,
            "why": pa.why_it_applies,
            "facts_used": pa.matched_facts,
            "matched_facts": pa.matched_facts,
            "missing_information": pa.missing_information,
            "missing_facts": pa.missing_information,
            "legal_basis": pa.legal_basis,
            "source": {"name": pa.official_portal_name, "url": pa.official_portal_url},
            "verification_status": pa.source_status.value,
            "portal_name": pa.official_portal_name,
            "portal_url": pa.official_portal_url,
            "layer": pa.graph_layer,
            "requirements": [{"title": r.title, "satisfied": r.is_satisfied, "category": r.document_category.value if r.document_category else None} for r in pa.requirements],
        }
        for pa in approvals
        if pa.applicability != Applicability.NOT_APPLICABLE
    ]
    readiness = db.get(models.Project, project.id)
    return {
        "ok": True,
        "summary": summary,
        "disclaimer": "Applicability results are planning-level indications from a deterministic rule engine evaluated on your profile. Confirm each requirement with the authority via the official portal before relying on it.",
        "approvals": applies,
        "critical_path": get_critical_path(db, project),
        "readiness_overall": (readiness.readiness_snapshot or {}).get("overall"),
    }


@router.get("/projects/{project_id}/approvals")
def list_approvals(
    project_id: int,
    category: str | None = None,
    applicability: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    rows = db.scalars(select(models.ProjectApproval).where(models.ProjectApproval.project_id == project.id).order_by(models.ProjectApproval.graph_layer, models.ProjectApproval.id)).all()
    out = []
    ql = (q or "").lower()
    for pa in rows:
        if category and (pa.category.value if pa.category else None) != category:
            continue
        if applicability and (pa.applicability.value if pa.applicability else None) != applicability:
            continue
        if ql and ql not in pa.name.lower() and ql not in pa.authority.lower():
            continue
        out.append(_approval_payload(pa))
    cats = sorted({(pa.category.value if pa.category else "OTHER") for pa in rows})
    return {"approvals": out, "categories": cats}


def _approval_payload(pa: models.ProjectApproval) -> dict[str, Any]:
    return {
        "id": pa.id,
        "template_code": pa.template_code,
        "name": pa.name,
        "category": pa.category.value if pa.category else None,
        "authority": pa.authority,
        "jurisdiction": pa.jurisdiction.value if pa.jurisdiction else None,
        "applicability": pa.applicability.value if pa.applicability else None,
        "node_state": pa.node_state.value if pa.node_state else None,
        "source_status": pa.source_status.value if pa.source_status else None,
        "confidence": pa.confidence.value if pa.confidence else None,
        "why": pa.why_it_applies,
        "matched_rules": pa.matched_rule_keys,
        "matched_facts": pa.matched_facts,
        "missing_information": pa.missing_information,
        "legal_basis": pa.legal_basis,
        "verification_note": pa.verification_note,
        "portal_name": pa.official_portal_name,
        "portal_url": pa.official_portal_url,
        "estimated_timeline_days": pa.estimated_timeline_days,
        "requirements": [
            {"id": r.id, "title": r.title, "type": r.requirement_type, "satisfied": r.is_satisfied,
             "document_id": r.satisfied_by_document_id, "mandatory": r.is_mandatory,
             "category": r.document_category.value if r.document_category else None}
            for r in pa.requirements
        ],
        "dependencies": pa.dependencies,
        "dependents": pa.dependents,
        "is_on_critical_path": pa.is_on_critical_path,
        "user_notes": pa.user_notes,
        "user_dismissed": pa.user_dismissed,
        "user_confirmed_required": pa.user_confirmed_required,
    }


@router.get("/projects/{project_id}/approvals/{template_code}")
def get_approval(project_id: int, template_code: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    pa = db.scalars(select(models.ProjectApproval).where(
        models.ProjectApproval.project_id == project.id, models.ProjectApproval.template_code == template_code)).first()
    if pa is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Approval not found for this project. Run the analysis first.")
    payload = _approval_payload(pa)
    template = pa.template
    if template is not None:
        payload["catalogue"] = {
            "description": template.description,
            "process_summary": template.process_summary,
            "statutory_timeline_text": template.statutory_timeline_text,
            "fee_information": template.fee_information,
            "validity_text": template.validity_text,
            "renewal_period_months": template.renewal_period_months,
            "applicability_conditions": template.applicability_conditions,
            "last_verified_at": template.last_verified_at.isoformat() if template.last_verified_at else None,
        }
    return payload


class ApprovalAction(BaseModel):
    action: str = Field(description="confirm_required | dismiss | restore | set_state | note")
    node_state: str | None = None
    note: str | None = None
    requirement_id: int | None = None
    satisfied: bool | None = None


@router.post("/projects/{project_id}/approvals/{template_code}/action")
def approval_action(project_id: int, template_code: str, body: ApprovalAction, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    pa = db.scalars(select(models.ProjectApproval).where(
        models.ProjectApproval.project_id == project.id, models.ProjectApproval.template_code == template_code)).first()
    if pa is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Approval not found.")
    if body.action == "confirm_required":
        pa.user_confirmed_required = True
        audit_event(db, action="approval.confirm_required", action_category="APPROVAL", user_id=user.id,
                    project_id=project.id, resource_type="project_approval", resource_id=str(pa.id), commit=False)
    elif body.action == "dismiss":
        pa.user_dismissed = True
        audit_event(db, action="approval.dismiss", action_category="APPROVAL", user_id=user.id,
                    project_id=project.id, resource_type="project_approval", resource_id=str(pa.id),
                    details={"name": pa.name}, commit=False)
    elif body.action == "restore":
        pa.user_dismissed = False
    elif body.action == "note":
        pa.user_notes = (body.note or "")[:4000]
    elif body.action == "requirement":
        req = db.get(models.ProjectApprovalRequirement, body.requirement_id)
        if req is None or req.project_approval_id != pa.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
        req.is_satisfied = bool(body.satisfied)
        if req.is_satisfied and req.satisfied_by_document_id is None:
            # link a matching document if one exists
            docs = db.scalars(select(models.Document).where(models.Document.project_id == project.id)).all()
            for d in docs:
                if d.title and (d.title.lower() in req.title.lower() or req.title.lower() in d.title.lower()):
                    req.satisfied_by_document_id = d.id
                    break
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown action.")
    from ..services.approval_engine import mark_critical_path

    mark_critical_path(db, project)
    db.commit()
    return {"ok": True, "approval": _approval_payload(pa), "critical_path": get_critical_path(db, project)}


@router.get("/projects/{project_id}/graph")
def dependency_graph(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    return graph_payload(db, project)


@router.get("/projects/{project_id}/critical-path")
def critical_path(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    return {"steps": get_critical_path(db, project)}


@router.get("/projects/{project_id}/readiness")
def readiness(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    return readiness_service.compute_readiness(db, project)


@router.get("/projects/{project_id}/next-actions")
def next_actions(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    actions = next_best_actions(db, project)
    return {"actions": [{**a, "link": (a["link"] or "").replace("{pid}", str(project.id))} for a in actions], "today": todays_tasks(db, project)}
