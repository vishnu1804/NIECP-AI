"""Compliance tasks, calendar, renewals, government queries, inspections
(spec §20-§24)."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..enums import (
    InspectionStatus,
    QueryStatus,
    RenewalStatus,
    SourceStatus,
    TaskPriority,
    TaskStatus,
)
from ..services import notifications as notification_service
from ..services import query_translator
from ..services.audit import audit_confirmation, audit_event
from ..services.auth_service import client_ip, get_current_user, project_access, request_id
from ..services.next_action import todays_tasks

router = APIRouter(tags=["compliance"])


# ═════════════════════════════════════════════════════════════ TASKS ══
class TaskCreate(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    description: str | None = None
    priority: TaskPriority = TaskPriority.MEDIUM
    due_date: str | None = None
    assigned_to: int | None = None
    approval_code: str | None = None
    checklist: list[dict[str, Any]] | None = None


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    due_date: str | None = None
    assigned_to: int | None = None
    checklist: list[dict[str, Any]] | None = None


def _task_payload(t: models.ComplianceTask) -> dict[str, Any]:
    return {
        "id": t.id, "title": t.title, "description": t.description,
        "task_type": t.task_type, "status": t.status.value, "priority": t.priority.value,
        "due_date": t.due_date.isoformat() if t.due_date else None,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        "assigned_to": t.assigned_to, "approval_code": t.approval_code,
        "checklist": t.checklist or [], "is_demo": t.is_demo,
        "source_status": t.source_status.value if t.source_status else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


@router.get("/projects/{project_id}/compliance")
def list_tasks(project_id: int, status_filter: str | None = Query(default=None, alias="status"),
               db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    rows = db.scalars(select(models.ComplianceTask).where(models.ComplianceTask.project_id == project.id).order_by(models.ComplianceTask.due_date.asc().nullslast())).all()
    out = [_task_payload(t) for t in rows]
    if status_filter:
        out = [t for t in out if t["status"] == status_filter]
    return {"tasks": out}


@router.post("/projects/{project_id}/compliance", status_code=status.HTTP_201_CREATED)
def create_task(project_id: int, body: TaskCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    due = date.fromisoformat(body.due_date) if body.due_date else None
    task = models.ComplianceTask(project_id=project.id, organization_id=project.organization_id,
                                 title=body.title.strip(), description=body.description, priority=body.priority,
                                 due_date=due, assigned_to=body.assigned_to, approval_code=body.approval_code,
                                 checklist=body.checklist or [], source_status=SourceStatus.USER_PROVIDED)
    db.add(task)
    db.flush()
    notification_service.notify(db, user_id=None, project_id=project.id,
                                notification_type=notification_service.NotificationType.NEW_TASK,
                                title=f"New task: {task.title}", severity="INFO", link="/projects/{pid}/compliance",
                                commit=False)
    audit_event(db, action="task.create", action_category="COMPLIANCE", user_id=user.id, project_id=project.id,
                resource_type="compliance_task", resource_id=str(task.id), commit=True)
    return {"ok": True, "task": _task_payload(task)}


@router.patch("/projects/{project_id}/compliance/{task_id}")
def update_task(project_id: int, task_id: int, body: TaskUpdate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    task = db.get(models.ComplianceTask, task_id)
    if task is None or task.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found.")
    if body.title is not None:
        task.title = body.title.strip()[:300]
    if body.description is not None:
        task.description = body.description
    if body.status is not None:
        task.status = body.status
        task.completed_at = datetime.utcnow() if body.status == TaskStatus.DONE else None
    if body.priority is not None:
        task.priority = body.priority
    if body.due_date is not None:
        task.due_date = date.fromisoformat(body.due_date) if body.due_date else None
    if body.assigned_to is not None:
        task.assigned_to = body.assigned_to
    if body.checklist is not None:
        task.checklist = body.checklist
    audit_event(db, action="task.update", action_category="COMPLIANCE", user_id=user.id, project_id=project.id,
                resource_type="compliance_task", resource_id=str(task.id), after={"status": task.status.value}, commit=True)
    return {"ok": True, "task": _task_payload(task)}


@router.delete("/projects/{project_id}/compliance/{task_id}")
def delete_task(project_id: int, task_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    task = db.get(models.ComplianceTask, task_id)
    if task is None or task.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found.")
    db.delete(task)
    db.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════ CALENDAR ══
@router.get("/projects/{project_id}/calendar")
def calendar(project_id: int, year: int | None = None, month: int | None = None,
             db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    today = date.today()
    year, month = year or today.year, month or today.month
    start = date(year, month, 1)
    end = date(year + (month == 12), (month % 12) + 1, 1)

    events: list[dict[str, Any]] = []
    for r in db.scalars(select(models.Renewal).where(models.Renewal.project_id == project.id)):
        if r.due_date and start <= r.due_date < end:
            events.append({"date": r.due_date.isoformat(), "kind": "renewal", "id": r.id, "title": r.title,
                           "status": r.status.value, "priority": "CRITICAL" if r.status == RenewalStatus.OVERDUE else "HIGH",
                           "portal_url": r.official_portal_url, "is_demo": r.is_demo})
    for t in db.scalars(select(models.ComplianceTask).where(models.ComplianceTask.project_id == project.id)):
        if t.due_date and start <= t.due_date < end:
            events.append({"date": t.due_date.isoformat(), "kind": "task", "id": t.id, "title": t.title,
                           "status": t.status.value, "priority": t.priority.value, "is_demo": t.is_demo})
    for q in db.scalars(select(models.GovernmentQuery).where(models.GovernmentQuery.project_id == project.id)):
        if q.deadline and start <= q.deadline < end:
            events.append({"date": q.deadline.isoformat(), "kind": "query", "id": q.id,
                           "title": f"Respond: {q.reference_number or q.authority or 'query'}",
                           "status": q.status.value, "priority": "CRITICAL", "is_demo": q.is_demo})
    for i in db.scalars(select(models.Inspection).where(models.Inspection.project_id == project.id)):
        if i.inspection_date and start <= i.inspection_date < end:
            events.append({"date": i.inspection_date.isoformat(), "kind": "inspection", "id": i.id,
                           "title": f"Inspection: {i.department or 'scheduled'}", "status": i.status.value,
                           "priority": "HIGH", "is_demo": i.is_demo})
    for d in db.scalars(select(models.Document).where(models.Document.project_id == project.id)):
        if d.expiry_date and start <= d.expiry_date < end:
            events.append({"date": d.expiry_date.isoformat(), "kind": "document_expiry", "id": d.id,
                           "title": f"Expires: {d.title}", "status": d.status.value, "priority": "HIGH",
                           "is_demo": d.is_demo})
    events.sort(key=lambda e: e["date"])
    upcoming = todays_tasks(db, project)
    return {"year": year, "month": month, "events": events, "next_7_days": upcoming}


# ═══════════════════════════════════════════════════════════ RENEWALS ══
class RenewalCreate(BaseModel):
    title: str
    renewal_type: str = "LICENCE"
    due_date: str
    issued_date: str | None = None
    document_id: int | None = None
    approval_code: str | None = None
    reminder_days: list[int] | None = None
    official_portal_url: str | None = None
    notes: str | None = None


@router.get("/projects/{project_id}/renewals")
def list_renewals(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    notification_service.update_renewal_statuses(db)
    rows = db.scalars(select(models.Renewal).where(models.Renewal.project_id == project.id).order_by(models.Renewal.due_date.asc())).all()
    today = date.today()
    return {"renewals": [
        {"id": r.id, "title": r.title, "renewal_type": r.renewal_type, "due_date": r.due_date.isoformat() if r.due_date else None,
         "issued_date": r.issued_date.isoformat() if r.issued_date else None,
         "status": r.status.value, "days_remaining": (r.due_date - today).days if r.due_date else None,
         "reminder_days": r.reminder_days, "document_id": r.document_id, "approval_code": r.approval_code,
         "official_portal_url": r.official_portal_url, "notes": r.notes, "is_demo": r.is_demo}
        for r in rows
    ]}


@router.post("/projects/{project_id}/renewals", status_code=status.HTTP_201_CREATED)
def create_renewal(project_id: int, body: RenewalCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    try:
        due = date.fromisoformat(body.due_date)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid due date.")
    renewal = models.Renewal(project_id=project.id, organization_id=project.organization_id, title=body.title.strip(),
                             renewal_type=body.renewal_type, due_date=due,
                             issued_date=date.fromisoformat(body.issued_date) if body.issued_date else None,
                             document_id=body.document_id, approval_code=body.approval_code,
                             reminder_days=body.reminder_days or [90, 60, 30, 7],
                             official_portal_url=body.official_portal_url, notes=body.notes,
                             source_status=SourceStatus.USER_PROVIDED)
    db.add(renewal)
    notification_service.update_renewal_statuses(db)
    audit_event(db, action="renewal.create", action_category="COMPLIANCE", user_id=user.id, project_id=project.id,
                resource_type="renewal", resource_id=str(renewal.id), commit=True)
    return {"ok": True, "id": renewal.id}


@router.post("/projects/{project_id}/renewals/{renewal_id}/renew")
def mark_renewed(project_id: int, renewal_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    renewal = db.get(models.Renewal, renewal_id)
    if renewal is None or renewal.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Renewal not found.")
    renewal.status = RenewalStatus.RENEWED
    if renewal.due_date:
        renewal.issued_date = renewal.due_date
        # roll forward one year as the next expected cycle (user-editable)
        renewal.due_date = renewal.due_date.replace(year=renewal.due_date.year + 1)
        renewal.status = RenewalStatus.UPCOMING
        renewal.reminders_sent = []
    audit_event(db, action="renewal.renewed", action_category="COMPLIANCE", user_id=user.id, project_id=project.id,
                resource_type="renewal", resource_id=str(renewal.id), commit=True)
    return {"ok": True, "next_due": renewal.due_date.isoformat() if renewal.due_date else None}


# ═══════════════════════════════════════════ GOVERNMENT QUERIES ══
class QueryCreate(BaseModel):
    authority: str | None = None
    reference_number: str | None = None
    query_text: str = Field(min_length=5)
    date_received: str | None = None
    deadline: str | None = None
    application_id: int | None = None
    required_documents: list[str] | None = None


class QueryUpdate(BaseModel):
    status: QueryStatus | None = None
    response_text: str | None = None
    response_confirmation: bool | None = None
    required_documents: list[str] | None = None
    deadline: str | None = None
    attachment_document_ids: list[int] | None = None


@router.get("/projects/{project_id}/queries")
def list_queries(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    rows = db.scalars(select(models.GovernmentQuery).where(models.GovernmentQuery.project_id == project.id).order_by(models.GovernmentQuery.created_at.desc())).all()
    return {"queries": [_query_payload(q) for q in rows]}


def _query_payload(q: models.GovernmentQuery) -> dict[str, Any]:
    return {
        "id": q.id, "application_id": q.application_id, "authority": q.authority,
        "reference_number": q.reference_number, "query_text": q.query_text,
        "date_received": q.date_received.isoformat() if q.date_received else None,
        "deadline": q.deadline.isoformat() if q.deadline else None,
        "status": q.status.value, "required_documents": q.required_documents or [],
        "response_text": q.response_text,
        "response_attachments": q.response_attachments or [],
        "responded_at": q.responded_at.isoformat() if q.responded_at else None,
        "user_confirmed_response_at": q.user_confirmed_response_at.isoformat() if q.user_confirmed_response_at else None,
        "ai_explanation": q.ai_explanation, "ai_suggested_steps": q.ai_suggested_steps or [],
        "translator": q.translator or None, "is_demo": q.is_demo,
    }


@router.post("/projects/{project_id}/queries", status_code=status.HTTP_201_CREATED)
def create_query(project_id: int, body: QueryCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    q = models.GovernmentQuery(
        project_id=project.id, application_id=body.application_id, authority=body.authority,
        reference_number=body.reference_number, query_text=body.query_text,
        date_received=date.fromisoformat(body.date_received) if body.date_received else date.today(),
        deadline=date.fromisoformat(body.deadline) if body.deadline else None,
        required_documents=body.required_documents or [],
        source_status=SourceStatus.USER_PROVIDED,
    )
    # full deterministic translation (spec §21): plain language, missing items,
    # needed documents, recommended action, response preparation — grounded in
    # the project's real state, always labelled as an AI-generated explanation.
    translation = query_translator.translate(db, query=q, project=project)
    q.ai_explanation = translation["plain_language_explanation"]
    q.ai_suggested_steps = translation["response_preparation"]["steps"]
    q.translator = translation
    db.add(q)
    db.flush()
    notification_service.notify(db, user_id=None, project_id=project.id,
                                notification_type=notification_service.NotificationType.APPLICATION_QUERY,
                                title=f"Government query recorded: {q.reference_number or q.authority or 'query'}",
                                severity="WARNING", link="/projects/{pid}/queries", commit=False)
    audit_event(db, action="QUERY_RECORDED", action_category="COMPLIANCE", user_id=user.id, project_id=project.id,
                resource_type="government_query", resource_id=str(q.id), commit=True)
    return {"ok": True, "query": _query_payload(q), "translation": translation}


@router.post("/projects/{project_id}/queries/{query_id}/translate")
def translate_query(project_id: int, query_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """(Re-)run the Query Translator on a recorded query and store the result."""
    project = project_access(db, user, project_id)
    q = db.get(models.GovernmentQuery, query_id)
    if q is None or q.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Query not found.")
    translation = query_translator.translate(db, query=q, project=project)
    q.ai_explanation = translation["plain_language_explanation"]
    q.ai_suggested_steps = translation["response_preparation"]["steps"]
    q.translator = translation
    audit_event(db, action="QUERY_TRANSLATED", action_category="COMPLIANCE", user_id=user.id,
                project_id=project.id, resource_type="government_query", resource_id=str(q.id),
                details={"source_status": translation["source_status"]}, commit=True)
    db.commit()
    return {"ok": True, "query_id": q.id, "translation": translation}


@router.patch("/projects/{project_id}/queries/{query_id}")
def update_query(project_id: int, query_id: int, body: QueryUpdate, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    q = db.get(models.GovernmentQuery, query_id)
    if q is None or q.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Query not found.")
    if body.status is not None:
        q.status = body.status
    if body.required_documents is not None:
        q.required_documents = body.required_documents
    if body.deadline is not None:
        q.deadline = date.fromisoformat(body.deadline) if body.deadline else None
    if body.response_text is not None:
        if not body.response_confirmation:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Recording a response requires your confirmation that it was actually filed with the authority. NIECP-AI never transmits responses on your behalf.")
        q.response_text = body.response_text
        q.responded_at = datetime.utcnow()
        q.user_confirmed_response_at = datetime.utcnow()
        if q.status in (QueryStatus.OPEN, QueryStatus.IN_PROGRESS, QueryStatus.READY):
            q.status = QueryStatus.RESPONDED
        audit_confirmation(db, user, project.id, what="query.response.recorded", resource_type="government_query",
                           resource_id=str(q.id), confirmation_text="User confirmed the response was filed with the authority.",
                           request_id=request_id(request))
    if body.attachment_document_ids is not None:
        q.response_attachments = body.attachment_document_ids
    audit_event(db, action="query.update", action_category="COMPLIANCE", user_id=user.id, project_id=project.id,
                resource_type="government_query", resource_id=str(q.id), after={"status": q.status.value}, commit=True)
    return {"ok": True, "query": _query_payload(q)}


# ═══════════════════════════════════════════════════════ INSPECTIONS ══
class InspectionCreate(BaseModel):
    department: str | None = None
    inspection_date: str | None = None
    inspection_type: str = "GENERAL"
    officer_name: str | None = None
    officer_designation: str | None = None
    officer_details_officially_provided: bool = False
    application_id: int | None = None
    documents_to_keep_ready: list[str] | None = None


class InspectionUpdate(BaseModel):
    status: InspectionStatus | None = None
    findings: str | None = None
    checklist: list[dict[str, Any]] | None = None
    corrective_actions: list[dict[str, Any]] | None = None
    follow_up_date: str | None = None
    inspection_date: str | None = None


@router.get("/projects/{project_id}/inspections")
def list_inspections(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    rows = db.scalars(select(models.Inspection).where(models.Inspection.project_id == project.id).order_by(models.Inspection.inspection_date.desc().nullslast())).all()
    return {"inspections": [_inspection_payload(i) for i in rows]}


def _inspection_payload(i: models.Inspection) -> dict[str, Any]:
    return {
        "id": i.id, "application_id": i.application_id, "department": i.department,
        "inspection_type": i.inspection_type, "inspection_date": i.inspection_date.isoformat() if i.inspection_date else None,
        "officer_name": i.officer_name, "officer_designation": i.officer_designation,
        "officer_details_source": i.officer_details_source.value if i.officer_details_source else None,
        "status": i.status.value, "checklist": i.checklist or [], "documents_to_keep_ready": i.documents_to_keep_ready or [],
        "findings": i.findings, "corrective_actions": i.corrective_actions or [],
        "follow_up_date": i.follow_up_date.isoformat() if i.follow_up_date else None,
        "is_demo": i.is_demo,
    }


DEFAULT_CHECKLIST: list[dict[str, Any]] = [
    {"item": "Copies of the approval/licence and its conditions available at site", "done": False},
    {"item": "Approved layout/plans match the physical site", "done": False},
    {"item": "Statutory registers and records are up to date", "done": False},
    {"item": "Monitoring reports (effluent/emission) available", "done": False},
    {"item": "Waste storage, labelling and manifest records in order", "done": False},
    {"item": "Safety systems (fire, PPE, emergency) functional", "done": False},
    {"item": "Declared capacities match installed equipment", "done": False},
    {"item": "Responsible person available and briefed", "done": False},
]


@router.post("/projects/{project_id}/inspections", status_code=status.HTTP_201_CREATED)
def create_inspection(project_id: int, body: InspectionCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    inspection = models.Inspection(
        project_id=project.id, application_id=body.application_id, department=body.department,
        inspection_date=date.fromisoformat(body.inspection_date) if body.inspection_date else None,
        inspection_type=body.inspection_type,
        officer_name=body.officer_name if body.officer_details_officially_provided else None,
        officer_designation=body.officer_designation if body.officer_details_officially_provided else None,
        officer_details_source=SourceStatus.USER_PROVIDED if body.officer_details_officially_provided else SourceStatus.INFORMATION_UNAVAILABLE,
        checklist=[dict(item) for item in DEFAULT_CHECKLIST],
        documents_to_keep_ready=body.documents_to_keep_ready or [],
        source_status=SourceStatus.USER_PROVIDED,
    )
    db.add(inspection)
    db.flush()
    notification_service.notify(db, user_id=None, project_id=project.id,
                                notification_type=notification_service.NotificationType.DEADLINE_APPROACHING,
                                title=f"Inspection recorded: {inspection.department or 'department'}",
                                severity="WARNING", link="/projects/{pid}/inspections",
                                payload={"date": body.inspection_date}, commit=False)
    audit_event(db, action="inspection.create", action_category="COMPLIANCE", user_id=user.id, project_id=project.id,
                resource_type="inspection", resource_id=str(inspection.id), commit=True)
    return {"ok": True, "inspection": _inspection_payload(inspection)}


@router.patch("/projects/{project_id}/inspections/{inspection_id}")
def update_inspection(project_id: int, inspection_id: int, body: InspectionUpdate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    inspection = db.get(models.Inspection, inspection_id)
    if inspection is None or inspection.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inspection not found.")
    if body.status is not None:
        inspection.status = body.status
    if body.findings is not None:
        inspection.findings = body.findings
    if body.checklist is not None:
        inspection.checklist = body.checklist
    if body.corrective_actions is not None:
        inspection.corrective_actions = body.corrective_actions
    if body.inspection_date is not None:
        inspection.inspection_date = date.fromisoformat(body.inspection_date)
    if body.follow_up_date is not None:
        inspection.follow_up_date = date.fromisoformat(body.follow_up_date)
        if inspection.status == InspectionStatus.COMPLETED:
            inspection.status = InspectionStatus.FOLLOW_UP_REQUIRED
    audit_event(db, action="inspection.update", action_category="COMPLIANCE", user_id=user.id, project_id=project.id,
                resource_type="inspection", resource_id=str(inspection.id), after={"status": inspection.status.value}, commit=True)
    return {"ok": True, "inspection": _inspection_payload(inspection)}
