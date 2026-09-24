"""Applications & the Get Approval workflow (spec §14, §15)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..enums import (
    Applicability,
    ApplicationStatus,
    AuditResult,
    IntegrationMode,
    SourceStatus,
    SubmissionChannel,
)
from ..services import demo_government
from ..services import gov_manager
from ..services.audit import audit_confirmation, audit_event
from ..services.auth_service import client_ip, get_current_user, project_access, request_id
from ..services.readiness import documents_readiness

router = APIRouter(tags=["applications"])

WORKFLOW_ORDER = [
    ApplicationStatus.DRAFT,
    ApplicationStatus.READY_TO_APPLY,
    ApplicationStatus.USER_CONFIRMED,
    ApplicationStatus.SUBMITTED,
    ApplicationStatus.UNDER_REVIEW,
    ApplicationStatus.QUERY_RAISED,
    ApplicationStatus.USER_RESPONDED,
    ApplicationStatus.INSPECTION,
    ApplicationStatus.APPROVED,
    ApplicationStatus.REJECTED,
    ApplicationStatus.WITHDRAWN,
    ApplicationStatus.EXPIRED,
    ApplicationStatus.RENEWAL_DUE,
    ApplicationStatus.CANCELLED,
]


def _application_payload(db: Session, a: models.Application) -> dict[str, Any]:
    from ..services.lifecycle import lifecycle_for_application
    return {
        "id": a.id,
        "lifecycle": lifecycle_for_application(db, a),
        "project_id": a.project_id,
        "title": a.title,
        "authority": a.authority,
        "approval_template_code": a.approval_template_code,
        "status": a.status.value if a.status else None,
        "submission_channel": a.submission_channel.value if a.submission_channel else None,
        "integration_mode": a.integration_mode.value if a.integration_mode else IntegrationMode.MANUAL.value,
        "provider": a.provider,
        "correlation_id": a.correlation_id,
        "official_reference": a.official_reference,
        "official_reference_source": a.official_reference_source.value if a.official_reference_source else None,
        "official_portal_url": a.official_portal_url,
        "readiness_score": a.readiness_score,
        "prepared_at": a.prepared_at.isoformat() if a.prepared_at else None,
        "user_confirmed_at": a.user_confirmed_at.isoformat() if a.user_confirmed_at else None,
        "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
        "submitted_by_user": a.submitted_by_user,
        "decision_date": a.decision_date.isoformat() if a.decision_date else None,
        "valid_until": a.valid_until.isoformat() if a.valid_until else None,
        "fee_paid": float(a.fee_paid) if a.fee_paid is not None else None,
        "fee_payment_reference": a.fee_payment_reference,
        "status_is_self_reported": a.status_is_self_reported,
        "is_demo": a.is_demo,
        "notes": a.notes,
        "preparation_summary": a.preparation_summary or {},
        "application_data": a.application_data or {},
        "history": [
            {"status": h.status.value, "previous": h.previous_status.value if h.previous_status else None,
             "at": h.created_at.isoformat() if h.created_at else None,
             "changed_by": h.changed_by, "reason": h.reason,
             "source_status": h.source_status.value if h.source_status else None,
             "evidence_reference": h.evidence_reference}
            for h in a.history
        ],
        "queries": [
            {"id": q.id, "status": q.status.value, "authority": q.authority, "reference_number": q.reference_number,
             "deadline": q.deadline.isoformat() if q.deadline else None}
            for q in a.queries
        ],
        "inspections": [
            {"id": i.id, "status": i.status.value, "department": i.department,
             "date": i.inspection_date.isoformat() if i.inspection_date else None}
            for i in a.inspections
        ],
    }


class ApplicationCreate(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    approval_template_code: str | None = None
    authority: str | None = None


class ApplicationUpdate(BaseModel):
    title: str | None = None
    authority: str | None = None
    notes: str | None = None
    official_reference: str | None = None
    official_reference_confirmation: bool | None = Field(default=None, description="Must be true to record an official reference from the user")
    fee_paid: float | None = None
    fee_payment_reference: str | None = None
    decision_date: str | None = None
    valid_until: str | None = None
    application_data: dict[str, Any] | None = None


class StatusUpdate(BaseModel):
    status: ApplicationStatus
    reason: str | None = None
    evidence_reference: str | None = None
    self_reported_confirmation: bool = Field(description="User confirms this status reflects what the authority actually communicated")


@router.get("/projects/{project_id}/applications")
def list_applications(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    rows = db.scalars(select(models.Application).where(models.Application.project_id == project.id).order_by(models.Application.updated_at.desc())).all()
    return {"applications": [_application_payload(db, a) for a in rows], "workflow_states": [s.value for s in WORKFLOW_ORDER]}


@router.post("/projects/{project_id}/applications", status_code=status.HTTP_201_CREATED)
def create_application(project_id: int, body: ApplicationCreate, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    approval = None
    if body.approval_template_code:
        approval = db.scalars(select(models.ProjectApproval).where(
            models.ProjectApproval.project_id == project.id,
            models.ProjectApproval.template_code == body.approval_template_code)).first()
        if approval is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "That approval is not in this project's analysis. Run the analysis first.")
    app = models.Application(
        project_id=project.id,
        organization_id=project.organization_id,
        project_approval_id=approval.id if approval else None,
        approval_template_code=body.approval_template_code,
        title=body.title.strip(),
        authority=body.authority or (approval.authority if approval else None),
        official_portal_url=approval.official_portal_url if approval else None,
        status=ApplicationStatus.DRAFT,
        created_by=user.id,
    )
    db.add(app)
    db.flush()
    db.add(models.ApplicationStatusHistory(application_id=app.id, status=ApplicationStatus.DRAFT,
                                           changed_by=user.id, reason="Application created",
                                           source_status=SourceStatus.AI_INTERPRETATION))
    audit_event(db, action="application.create", action_category="APPLICATION", user_id=user.id,
                project_id=project.id, resource_type="application", resource_id=str(app.id),
                after={"title": app.title}, commit=True)
    return {"ok": True, "application": _application_payload(db, app)}


@router.get("/projects/{project_id}/applications/{application_id}")
def get_application(project_id: int, application_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    app = db.get(models.Application, application_id)
    if app is None or app.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found.")
    return _application_payload(db, app)


@router.patch("/projects/{project_id}/applications/{application_id}")
def update_application(project_id: int, application_id: int, body: ApplicationUpdate, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    app = db.get(models.Application, application_id)
    if app is None or app.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found.")
    if body.title is not None:
        app.title = body.title.strip()[:300]
    if body.authority is not None:
        app.authority = body.authority
    if body.notes is not None:
        app.notes = body.notes
    if body.application_data is not None:
        merged = dict(app.application_data or {})
        merged.update(body.application_data)
        app.application_data = merged
    if body.fee_paid is not None:
        app.fee_paid = body.fee_paid
    if body.fee_payment_reference is not None:
        app.fee_payment_reference = body.fee_payment_reference
    for attr in ("decision_date", "valid_until"):
        raw = getattr(body, attr)
        if raw:
            try:
                setattr(app, attr, date.fromisoformat(raw))
            except ValueError:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Invalid date {attr}")
    if body.official_reference:
        if not body.official_reference_confirmation:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Recording an official reference requires your explicit confirmation that it comes from the authority (acknowledgement, portal, or letter) — NIECP-AI never generates reference numbers.",
            )
        app.official_reference = body.official_reference.strip()[:160]
        app.official_reference_source = SourceStatus.USER_PROVIDED
    audit_event(db, action="application.update", action_category="APPLICATION", user_id=user.id,
                project_id=project.id, resource_type="application", resource_id=str(app.id), commit=True)
    db.commit()
    return {"ok": True, "application": _application_payload(db, app)}


@router.post("/projects/{project_id}/applications/{application_id}/prepare")
def prepare_application(project_id: int, application_id: int, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """Step 4 of Get Approval — build the preparation package from real state."""
    project = project_access(db, user, project_id)
    app = db.get(models.Application, application_id)
    if app is None or app.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found.")
    approval = app.project_approval
    profile = project.profile
    requirements = []
    if approval is not None:
        for req in approval.requirements:
            requirements.append({"title": req.title, "satisfied": req.is_satisfied,
                                 "document_id": req.satisfied_by_document_id, "mandatory": req.is_mandatory})
    docs_comp = documents_readiness(db, project)
    missing_facts = []
    if approval is not None:
        missing_facts = [m.get("label") for m in (approval.missing_information or [])]
    summary = {
        "authority": app.authority,
        "requirements": requirements,
        "documents_required": docs_comp.get("required_count", 0),
        "documents_satisfied": docs_comp.get("satisfied_count", 0),
        "missing_documents": docs_comp.get("missing", [])[:20],
        "profile_facts_missing": missing_facts,
        "profile_snapshot": {
            "organization_name": profile.organization_name if profile else None,
            "pan": profile.pan if profile else None,
            "gstin": profile.gstin if profile else None,
            "udyam_number": profile.udyam_number if profile else None,
            "state": profile.state_code if profile else None,
            "district": profile.district if profile else None,
            "industry": profile.industry_code if profile else None,
            "total_investment": float(profile.total_investment) if profile and profile.total_investment is not None else None,
            "number_of_employees": profile.number_of_employees if profile else None,
        },
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "notice": "This package organises your information for the official application. NIECP-AI does not submit it — you file it on the official portal (or via a provisioned verified integration).",
    }
    app.preparation_summary = summary
    app.prepared_at = datetime.utcnow()
    app.readiness_score = _application_readiness(summary)
    if app.status == ApplicationStatus.DRAFT:
        app.status = ApplicationStatus.READY_TO_APPLY
        db.add(models.ApplicationStatusHistory(application_id=app.id, status=ApplicationStatus.READY_TO_APPLY,
                                               previous_status=ApplicationStatus.DRAFT, changed_by=user.id,
                                               reason="Preparation package generated", source_status=SourceStatus.AI_INTERPRETATION))
    audit_event(db, action="application.prepare", action_category="APPLICATION", user_id=user.id,
                project_id=project.id, resource_type="application", resource_id=str(app.id), commit=True)
    db.commit()
    return {"ok": True, "application": _application_payload(db, app)}


def _application_readiness(summary: dict[str, Any]) -> float:
    reqs = summary.get("requirements", [])
    satisfied = sum(1 for r in reqs if r.get("satisfied"))
    doc_score = 100.0 * satisfied / len(reqs) if reqs else 60.0
    missing_docs = len(summary.get("missing_documents", []))
    total_docs = summary.get("documents_required", 0)
    doc2 = 100.0 * (total_docs - missing_docs) / total_docs if total_docs else 60.0
    facts_penalty = min(30.0, 5.0 * len(summary.get("profile_facts_missing", [])))
    return round(max(0.0, 0.5 * doc_score + 0.5 * doc2 - facts_penalty), 1)


@router.post("/projects/{project_id}/applications/{application_id}/confirm")
def confirm_application(project_id: int, application_id: int, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """Step 5 — the explicit user confirmation gate (spec §15)."""
    project = project_access(db, user, project_id)
    app = db.get(models.Application, application_id)
    if app is None or app.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found.")
    if app.prepared_at is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Prepare the application package before confirming.")
    app.user_confirmed_at = datetime.utcnow()
    app.user_confirmed_by = user.id
    if app.status == ApplicationStatus.READY_TO_APPLY:
        app.status = ApplicationStatus.USER_CONFIRMED
        db.add(models.ApplicationStatusHistory(application_id=app.id, status=ApplicationStatus.USER_CONFIRMED,
                                               previous_status=ApplicationStatus.READY_TO_APPLY, changed_by=user.id,
                                               reason="Preparation package confirmed by the user",
                                               source_status=SourceStatus.USER_PROVIDED))
    app.confirmation_text = (
        f"I confirm that I have reviewed the preparation package for “{app.title}” and that the information in it is "
        "accurate to the best of my knowledge. I understand NIECP-AI does not submit applications to government "
        "authorities — I will submit on the official portal myself unless a verified integration is provisioned."
    )
    audit_confirmation(db, user, project.id, what="application.preparation.confirmed",
                       resource_type="application", resource_id=str(app.id),
                       confirmation_text=app.confirmation_text, request_id=request_id(request))
    db.commit()
    return {"ok": True, "application": _application_payload(db, app)}


@router.post("/projects/{project_id}/applications/{application_id}/status")
def update_status(project_id: int, application_id: int, body: StatusUpdate, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    app = db.get(models.Application, application_id)
    if app is None or app.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found.")
    if not body.self_reported_confirmation:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Status updates describe what the government authority communicated. Please confirm the status you enter reflects official communication (portal, letter, email, or officer communication).",
        )
    previous = app.status
    app.status = body.status
    app.status_is_self_reported = True
    if body.status == ApplicationStatus.SUBMITTED and app.submitted_at is None:
        app.submitted_at = datetime.utcnow()
        app.submitted_by_user = True
    db.add(models.ApplicationStatusHistory(
        application_id=app.id, status=body.status, previous_status=previous, changed_by=user.id,
        reason=body.reason, source_status=SourceStatus.USER_PROVIDED, evidence_reference=body.evidence_reference,
        effective_at=datetime.utcnow(),
    ))
    # propagate outcome to the approval node and renewal tracking
    approval = app.project_approval
    if approval is not None:
        from ..enums import ApprovalNodeState

        state_map = {
            ApplicationStatus.APPROVED: ApprovalNodeState.APPROVED,
            ApplicationStatus.REJECTED: ApprovalNodeState.REJECTED,
            ApplicationStatus.SUBMITTED: ApprovalNodeState.SUBMITTED,
            ApplicationStatus.UNDER_REVIEW: ApprovalNodeState.SUBMITTED,
            ApplicationStatus.QUERY_RAISED: ApprovalNodeState.QUERY_RAISED,
            ApplicationStatus.INSPECTION: ApprovalNodeState.SUBMITTED,
        }
        if body.status in state_map:
            approval.node_state = state_map[body.status]
    if body.status == ApplicationStatus.APPROVED and app.valid_until:
        db.add(models.Renewal(
            project_id=project.id, organization_id=project.organization_id, title=f"Renewal: {app.title}",
            renewal_type="APPLICATION", approval_code=app.approval_template_code, application_id=app.id,
            issued_date=date.today(), due_date=app.valid_until, status=models.RenewalStatus.UPCOMING,
            official_portal_url=app.official_portal_url, source_status=SourceStatus.USER_PROVIDED,
        ))
    audit_event(db, action="application.status", action_category="APPLICATION", user_id=user.id,
                project_id=project.id, resource_type="application", resource_id=str(app.id),
                before={"status": previous.value if previous else None},
                after={"status": body.status.value, "reason": body.reason, "evidence": body.evidence_reference},
                commit=True)
    db.commit()
    return {"ok": True, "application": _application_payload(db, app)}


@router.get("/projects/{project_id}/applications/{application_id}/execution-options")
def execution_options(project_id: int, application_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """Spec §24 — how may this application be executed? Channels are reported
    honestly: authorized API only if a real verified connection exists (never
    in this deployment), official redirect when a stored portal URL exists,
    manual always, demo where the deployment allows it."""
    project = project_access(db, user, project_id)
    app = db.get(models.Application, application_id)
    if app is None or app.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found.")
    options = gov_manager.decide_execution_channels(db, project=project, application=app)
    options["readiness"] = {
        "prepared": app.prepared_at is not None,
        "user_confirmed": app.user_confirmed_at is not None,
        "blockers": demo_government._missing_blockers(app),
    }
    return options


@router.post("/projects/{project_id}/applications/{application_id}/redirect")
def official_redirect(project_id: int, application_id: int, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """OfficialRedirectAdapter — APPLICATION PREPARATION COMPLETE →
    [ OPEN OFFICIAL GOVERNMENT PORTAL ]. Uses only stored verified URLs;
    audits OFFICIAL_REDIRECT_OPENED."""
    project = project_access(db, user, project_id)
    app = db.get(models.Application, application_id)
    if app is None or app.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found.")
    result = gov_manager.official_redirect(db, project=project, application=app, user=user, request_id=request_id(request))
    if not result.get("ok"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, result.get("error", "No verified official portal URL stored."))
    db.commit()
    return result


@router.get("/projects/{project_id}/applications/{application_id}/manual-packet")
def manual_packet(project_id: int, application_id: int, format: str = "json", db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> Any:
    """ManualApplicationAdapter — view/copy/download the application packet for
    offline filing. Recording outcomes reuses the existing manual gates."""
    from fastapi.responses import PlainTextResponse

    project = project_access(db, user, project_id)
    app = db.get(models.Application, application_id)
    if app is None or app.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found.")
    packet = gov_manager.manual_packet(db, project=project, application=app)
    audit_event(db, action="MANUAL_PACKET_GENERATED", action_category="GOVERNMENT_EXECUTION",
                user_id=user.id, project_id=project.id, resource_type="application",
                resource_id=str(app.id), integration_mode="MANUAL", provider="manual", commit=True)
    if format == "text":
        return PlainTextResponse(
            gov_manager.render_manual_text(packet),
            headers={"Content-Disposition": f"attachment; filename=application-{app.id}-packet.txt"},
        )
    return packet


@router.delete("/projects/{project_id}/applications/{application_id}")
def delete_application(project_id: int, application_id: int, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    app = db.get(models.Application, application_id)
    if app is None or app.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found.")
    audit_event(db, action="application.delete", action_category="APPLICATION", user_id=user.id,
                project_id=project.id, resource_type="application", resource_id=str(app.id),
                before={"title": app.title, "status": app.status.value if app.status else None}, commit=True)
    db.delete(app)
    db.commit()
    return {"ok": True}
