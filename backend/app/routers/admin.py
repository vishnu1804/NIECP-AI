"""Notifications, admin panel, analytics, audit logs, organization management
(spec §2, §33, §34, §38, §41, §42, §43)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models
from ..ai import llm as llm_module
from ..ai.retrieval import corpus_stats
from ..config import get_settings, settings
from ..database import get_db
from ..enums import (
    AccountStatus,
    AIMessageRole,
    ApplicationStatus,
    AuditResult,
    NotificationType,
    OrgRole,
    PlatformRole,
    QueryStatus,
    RenewalStatus,
    TaskStatus,
)
from ..services import notifications as notification_service
from ..services.audit import audit_event
from ..services.auth_service import (
    client_ip,
    get_current_user,
    get_org_role,
    project_access,
    request_id,
)

router = APIRouter(tags=["notifications", "admin"])


# ═════════════════════════════════════════════════════ NOTIFICATIONS ══
@router.get("/notifications")
def list_notifications(unread_only: bool = False, limit: int = 50,
                       db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    # personal notifications + project-scoped notifications for accessible projects
    accessible_projects = db.scalars(select(models.Project.id).where(
        (models.Project.created_by == user.id) | (models.Project.organization_id == user.organization_id))).all()
    stmt = select(models.Notification).where(
        (models.Notification.user_id == user.id)
        | (models.Notification.project_id.in_(accessible_projects or [0]))
    )
    if unread_only:
        stmt = stmt.where(models.Notification.read_at.is_(None))
    rows = db.scalars(stmt.order_by(models.Notification.created_at.desc()).limit(limit)).all()
    unread = db.scalar(select(func.count(models.Notification.id)).where(
        (models.Notification.user_id == user.id) | (models.Notification.project_id.in_(accessible_projects or [0])),
        models.Notification.read_at.is_(None))) or 0
    return {"notifications": [
        {"id": n.id, "type": n.notification_type.value, "title": n.title, "body": n.body,
         "severity": n.severity, "link": n.link, "payload": n.payload or {},
         "read": n.read_at is not None, "email_status": n.email_status.value if n.email_status else None,
         "project_id": n.project_id,
         "created_at": n.created_at.isoformat() if n.created_at else None}
        for n in rows
    ], "unread": unread,
       "email_note": ("In-app notifications are live. Email delivery is "
                      + ("configured." if (settings.email_enabled and settings.smtp_host) else
                         "not configured in this deployment (NIECP_EMAIL_ENABLED=0) — notifications stay in-app and this is shown honestly in each delivery status."))}


class ReadUpdate(BaseModel):
    ids: list[int] | None = None
    all: bool = False


@router.post("/notifications/read")
def mark_read(body: ReadUpdate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    stmt = select(models.Notification).where(models.Notification.user_id == user.id, models.Notification.read_at.is_(None))
    if not body.all and body.ids:
        stmt = stmt.where(models.Notification.id.in_(body.ids))
    rows = db.scalars(stmt).all()
    for n in rows:
        n.read_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "marked": len(rows)}


@router.post("/notifications/test")
def test_notification(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    n = notification_service.notify(
        db, user_id=user.id, notification_type=NotificationType.SYSTEM,
        title="Test notification", body="If you can read this, in-app notifications work in this deployment.",
        severity="INFO", email=True,
    )
    return {"ok": True, "id": n.id, "email_status": n.email_status.value, "email_error": n.email_error}


# ═════════════════════════════════════════════════ ORGANIZATION / RBAC ══
class InviteRequest(BaseModel):
    email: str
    full_name: str
    org_role: OrgRole = OrgRole.EMPLOYEE
    can_submit_applications: bool = False
    can_manage_documents: bool = True
    project_scope: list[int] | None = None


class MemberUpdate(BaseModel):
    org_role: OrgRole | None = None
    can_submit_applications: bool | None = None
    can_manage_documents: bool | None = None
    can_manage_users: bool | None = None
    is_active: bool | None = None


@router.get("/organization")
def get_organization(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    if user.organization_id is None:
        return {"organization": None}
    org = db.get(models.Organization, user.organization_id)
    members = db.scalars(select(models.OrganizationMember).where(models.OrganizationMember.organization_id == org.id)).all()
    return {
        "organization": {
            "id": org.id, "name": org.name, "org_type": org.org_type.value, "enterprise_class": org.enterprise_class.value,
            "pan": org.pan, "gstin": org.gstin, "cin": org.cin, "udyam_number": org.udyam_number,
            "state_code": org.state_code, "is_demo": org.is_demo,
        },
        "members": [
            {"user_id": m.user_id, "email": m.user.email, "full_name": m.user.full_name, "role": m.org_role.value,
             "is_active": m.is_active, "can_submit_applications": m.can_submit_applications,
             "can_manage_documents": m.can_manage_documents, "can_manage_users": m.can_manage_users,
             "joined_at": m.created_at.isoformat() if m.created_at else None}
            for m in members
        ],
        "my_role": (get_org_role(db, user, org.id)).value if get_org_role(db, user, org.id) else None,
    }


@router.post("/organization/invite")
def invite_member(body: InviteRequest, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    role = get_org_role(db, user, user.organization_id)
    if role != OrgRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only organization admins can manage members.")
    target = db.scalars(select(models.User).where(models.User.email_normalized == body.email.strip().lower())).first()
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "No NIECP-AI account exists for this email yet. Ask them to register first, then add them here.")
    existing = db.scalars(select(models.OrganizationMember).where(
        models.OrganizationMember.organization_id == user.organization_id,
        models.OrganizationMember.user_id == target.id)).first()
    if existing is not None:
        existing.is_active = True
        existing.org_role = body.org_role
    else:
        db.add(models.OrganizationMember(organization_id=user.organization_id, user_id=target.id,
                                         org_role=body.org_role, can_submit_applications=body.can_submit_applications,
                                         can_manage_documents=body.can_manage_documents, invited_by=user.id,
                                         project_scope=body.project_scope or []))
    audit_event(db, action="org.member.add", action_category="RBAC", user_id=user.id,
                organization_id=user.organization_id, resource_type="user", resource_id=str(target.id),
                after={"role": body.org_role.value}, ip_address=client_ip(request), commit=True)
    return {"ok": True, "member": body.email}


@router.patch("/organization/members/{user_id}")
def update_member(user_id: int, body: MemberUpdate, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    role = get_org_role(db, user, user.organization_id)
    if role != OrgRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only organization admins can manage members.")
    member = db.scalars(select(models.OrganizationMember).where(
        models.OrganizationMember.organization_id == user.organization_id,
        models.OrganizationMember.user_id == user_id)).first()
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found.")
    for attr in ("org_role", "can_submit_applications", "can_manage_documents", "can_manage_users", "is_active"):
        val = getattr(body, attr)
        if val is not None:
            setattr(member, attr, val)
    audit_event(db, action="org.permission.change", action_category="RBAC", user_id=user.id,
                organization_id=user.organization_id, resource_type="organization_member", resource_id=str(user_id),
                after=body.model_dump(exclude_none=True), ip_address=client_ip(request), commit=True)
    return {"ok": True}


@router.delete("/organization/members/{user_id}")
def remove_member(user_id: int, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    role = get_org_role(db, user, user.organization_id)
    if role != OrgRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only organization admins can manage members.")
    if user_id == user.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "You cannot remove yourself from the organization.")
    member = db.scalars(select(models.OrganizationMember).where(
        models.OrganizationMember.organization_id == user.organization_id,
        models.OrganizationMember.user_id == user_id)).first()
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found.")
    member.is_active = False
    audit_event(db, action="org.member.remove", action_category="RBAC", user_id=user.id,
                organization_id=user.organization_id, resource_type="organization_member", resource_id=str(user_id),
                commit=True)
    return {"ok": True}


# ═══════════════════════════════════════════════════════ ANALYTICS ══
@router.get("/projects/{project_id}/analytics")
def project_analytics(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    apps = db.scalars(select(models.Application).where(models.Application.project_id == project.id)).all()
    docs = db.scalars(select(models.Document).where(models.Document.project_id == project.id)).all()
    tasks = db.scalars(select(models.ComplianceTask).where(models.ComplianceTask.project_id == project.id)).all()
    readiness = project.readiness_snapshot or {}
    return {
        "applications": {
            "total": len(apps),
            "by_status": {s.value: sum(1 for a in apps if a.status == s) for s in ApplicationStatus},
            "submitted": sum(1 for a in apps if a.submitted_at is not None),
            "user_confirmed": sum(1 for a in apps if a.user_confirmed_at is not None),
        },
        "documents": {
            "total": len(docs),
            "processed": sum(1 for d in docs if d.status == models.DocumentStatus.PROCESSED),
            "expired": sum(1 for d in docs if d.status == models.DocumentStatus.EXPIRED),
            "with_findings": sum(1 for d in docs if any(v.severity in (models.ValidationSeverity.WARNING, models.ValidationSeverity.BLOCKING) for v in d.validations)),
        },
        "tasks": {"total": len(tasks), "open": sum(1 for t in tasks if t.status == TaskStatus.OPEN),
                  "done": sum(1 for t in tasks if t.status == TaskStatus.DONE),
                  "overdue": sum(1 for t in tasks if t.due_date and t.due_date < date.today() and t.status != TaskStatus.DONE)},
        "readiness": readiness,
        "note": "These metrics describe preparation activity inside NIECP-AI. They are not government approval statistics and must not be read as approval probabilities.",
    }


# ═══════════════════════════════════════════════════════ ADMIN PANEL ══
def require_admin(user: models.User = Depends(get_current_user)) -> models.User:
    if user.platform_role not in (PlatformRole.SYSTEM_ADMIN, PlatformRole.ORGANIZATION_ADMIN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required.")
    return user


@router.get("/admin/overview")
def admin_overview(db: Session = Depends(get_db), user: models.User = Depends(require_admin)) -> dict[str, Any]:
    counts = {
        "users": db.scalar(select(func.count(models.User.id))) or 0,
        "organizations": db.scalar(select(func.count(models.Organization.id))) or 0,
        "projects": db.scalar(select(func.count(models.Project.id))) or 0,
        "documents": db.scalar(select(func.count(models.Document.id))) or 0,
        "applications": db.scalar(select(func.count(models.Application.id))) or 0,
        "audit_events": db.scalar(select(func.count(models.AuditLog.id))) or 0,
        "voice_sessions": db.scalar(select(func.count(models.VoiceSession.id))) or 0,
        "ai_messages": db.scalar(select(func.count(models.AIMessage.id))) or 0,
    }
    return {"counts": counts, "knowledge_corpus": corpus_stats(db),
            "production_blockers": get_settings().validate_production_readiness()}


@router.get("/admin/users")
def admin_users(q: str | None = None, db: Session = Depends(get_db), user: models.User = Depends(require_admin)) -> dict[str, Any]:
    rows = db.scalars(select(models.User).order_by(models.User.created_at.desc()).limit(200)).all()
    out = []
    ql = (q or "").lower()
    for u in rows:
        if ql and ql not in u.email.lower() and ql not in u.full_name.lower():
            continue
        out.append({"id": u.id, "email": u.email, "full_name": u.full_name, "platform_role": u.platform_role.value,
                    "status": u.status.value, "email_verified": u.email_verified_at is not None,
                    "is_demo": u.is_demo_account, "organization_id": u.organization_id,
                    "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
                    "created_at": u.created_at.isoformat() if u.created_at else None})
    return {"users": out}


class AdminUserUpdate(BaseModel):
    platform_role: PlatformRole | None = None
    status: AccountStatus | None = None
    must_change_password: bool | None = None


@router.patch("/admin/users/{user_id}")
def admin_update_user(user_id: int, body: AdminUserUpdate, request: Request, db: Session = Depends(get_db), admin: models.User = Depends(require_admin)) -> dict[str, Any]:
    if admin.platform_role != PlatformRole.SYSTEM_ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only system admins can modify users.")
    target = db.get(models.User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    for attr in ("platform_role", "status", "must_change_password"):
        val = getattr(body, attr)
        if val is not None:
            setattr(target, attr, val)
    audit_event(db, action="admin.user.update", action_category="ADMIN", user_id=admin.id,
                resource_type="user", resource_id=str(user_id),
                after=body.model_dump(exclude_none=True), ip_address=client_ip(request), commit=True)
    return {"ok": True}


@router.delete("/admin/demo-data")
def purge_demo_data(db: Session = Depends(get_db), admin: models.User = Depends(require_admin)) -> dict[str, Any]:
    """Removes every demo-labelled record. Real user data is untouched."""
    if admin.platform_role != PlatformRole.SYSTEM_ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only system admins can purge demo data.")
    removed = 0
    for model in (models.Notification, models.ComplianceTask, models.Inspection, models.GovernmentQuery,
                  models.Renewal, models.Application, models.Document, models.QuestionnaireAnswer,
                  models.ProjectApprovalRequirement, models.ProjectApproval, models.ProjectProfile, models.Project,
                  models.OrganizationMember, models.Organization):
        rows = db.scalars(select(model).where(getattr(model, "is_demo", False) == True)).all()  # noqa: E712
        for row in rows:
            db.delete(row)
            removed += 1
    for u in db.scalars(select(models.User).where(models.User.is_demo_account == True)).all():  # noqa: E712
        db.delete(u)
        removed += 1
    db.commit()
    audit_event(db, action="admin.demo_purge", action_category="ADMIN", user_id=admin.id,
                details={"removed": removed}, commit=True)
    return {"ok": True, "removed": removed}


@router.get("/admin/audit")
def admin_audit(action: str | None = None, category: str | None = None, user_id: int | None = None,
                project_id: int | None = None, security_only: bool = False, limit: int = 100,
                db: Session = Depends(get_db), admin: models.User = Depends(require_admin)) -> dict[str, Any]:
    stmt = select(models.AuditLog).order_by(models.AuditLog.created_at.desc()).limit(min(limit, 500))
    rows = db.scalars(stmt).all()
    out = []
    for a in rows:
        if action and a.action != action:
            continue
        if category and a.action_category != category:
            continue
        if user_id and a.user_id != user_id:
            continue
        if project_id and a.project_id != project_id:
            continue
        if security_only and not a.is_security_event:
            continue
        out.append({"id": a.id, "user_email": a.user_email, "action": a.action, "category": a.action_category,
                    "project_id": a.project_id, "resource_type": a.resource_type, "resource_id": a.resource_id,
                    "result": a.result.value if a.result else None, "agent": a.agent,
                    "correlation_id": a.correlation_id, "integration_mode": a.integration_mode, "provider": a.provider,
                    "is_security_event": a.is_security_event, "details": a.details,
                    "created_at": a.created_at.isoformat() if a.created_at else None})
    return {"events": out}


@router.get("/admin/ai-usage")
def admin_ai_usage(db: Session = Depends(get_db), admin: models.User = Depends(require_admin)) -> dict[str, Any]:
    rows = db.scalars(select(models.AIMessage).where(models.AIMessage.role == AIMessageRole.ASSISTANT).order_by(models.AIMessage.created_at.desc()).limit(200)).all()
    by_agent: dict[str, int] = {}
    by_intent: dict[str, int] = {}
    llm_used = 0
    for m in rows:
        if m.agent:
            by_agent[m.agent.value] = by_agent.get(m.agent.value, 0) + 1
        structured = m.structured or {}
        intent = structured.get("intent") or m.intent
        if intent:
            by_intent[intent] = by_intent.get(intent, 0) + 1
        if structured.get("used_llm"):
            llm_used += 1
    return {"assistant_messages": len(rows), "by_agent": by_agent, "by_intent": by_intent,
            "external_llm_used": llm_used, "llm_status": llm_module.llm_status()}

# ══════════════════════ DEPARTMENT OPERATIONS VIEW (§V screen 5) ══
@router.get("/ops/department-queue")
def department_queue(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """Read-only cross-project operations queue for department/admin review.
    PROTOTYPE / SIMULATED: in this MVP no real government officer workflow
    exists — statuses are self-reported or part of the labelled demo journey."""
    if user.platform_role not in (models.PlatformRole.SYSTEM_ADMIN, models.PlatformRole.ORGANIZATION_ADMIN, models.PlatformRole.REVIEWER):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Department operations view is admin-only.")

    from ..enums import ApplicationStatus, QueryStatus
    from ..services.lifecycle import sla_for_application, project_bottlenecks

    apps = db.scalars(select(models.Application).order_by(models.Application.created_at.desc()).limit(200)).all()
    pending = [a for a in apps if a.status in (ApplicationStatus.SUBMITTED, ApplicationStatus.UNDER_REVIEW,
                                               ApplicationStatus.QUERY_RAISED, ApplicationStatus.USER_RESPONDED, ApplicationStatus.INSPECTION)]
    from sqlalchemy.orm import Session as _S
    queue = []
    for a in pending[:50]:
        p = db.get(models.Project, a.project_id)
        queue.append({
            "application_id": a.id, "title": a.title, "authority": a.authority,
            "project": p.name if p else None, "status": a.status.value,
            "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
            "sla_status": sla_for_application(db, a).get("status"),
            "simulated": bool(a.is_demo),
        })
    queries = db.scalars(select(models.GovernmentQuery).where(
        models.GovernmentQuery.status.in_([QueryStatus.OPEN, QueryStatus.IN_PROGRESS]))).all()
    query_rows = [{"id": q.id, "project_id": q.project_id, "authority": q.authority,
                   "deadline": q.deadline.isoformat() if q.deadline else None,
                   "overdue": bool(q.deadline and q.deadline < date.today()), "simulated": bool(q.is_demo)} for q in queries[:50]]
    bottlenecks_total = 0
    for pid in {a.project_id for a in pending[:20]}:
        p = db.get(models.Project, pid)
        if p is not None:
            bottlenecks_total += project_bottlenecks(db, p)["summary"]["total"]
    return {
        "view": "DEPARTMENT OPERATIONS — PROTOTYPE / SIMULATED",
        "notice": ("Prototype view. No real government officer workflow exists in this MVP: statuses here are self-reported by "
                   "applicants or generated inside the clearly-labelled demo journey. Nothing here is an official government queue."),
        "queue": queue,
        "open_queries": query_rows,
        "summary": {"pending": len(pending), "open_queries": len(query_rows), "bottlenecks": bottlenecks_total,
                    "simulated": sum(1 for a in pending if a.is_demo)},
        "labels": ["PROTOTYPE", "SIMULATED", "READ-ONLY"],
    }
