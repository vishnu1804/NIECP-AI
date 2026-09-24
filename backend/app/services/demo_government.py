"""DemoGovernmentAdapter + demo status engine (Master Upgrade Prompt §5, §7, §8).

WHAT THIS IS
------------
An INTERNAL NIECP demonstration system. It exists so the complete government
workflow — submission → review → query → response → decision → renewal — can be
demonstrated end-to-end without any government API access.

WHAT THIS IS NOT
----------------
It is NOT a government API and never touches one. No call is made to NSWS,
API Setu, any state portal, or any other government system. Every transaction
is synthetic and every payload proclaims that:

    environment           = DEMO
    data_source           = SYNTHETIC
    government_api        = NOT_CONNECTED
    authorization_status  = NOT_AUTHORIZED
    live                  = False

Application IDs minted here look like ``NIECP-DEMO-2026-0001`` — visibly
synthetic NIECP demo identifiers, never passed off as government references.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..enums import (
    ApprovalNodeState,
    ApplicationStatus,
    AuthorizationStatus,
    IntegrationMode,
    QueryStatus,
    SourceStatus,
)
from ..models_mixins import utcnow
from .audit import audit_event
from .notifications import notify

# ---------------------------------------------------------------- metadata
PROVIDER_CODE = "niecp_demo_government"
PROVIDER_NAME = "NIECP Demo Government"
NOTICE = "Demonstration workflow only. Not connected to a live government system."
LABEL = "🟡 DEMO — SYNTHETIC DATA"

METADATA: dict[str, Any] = {
    "environment": "DEMO",
    "data_source": "SYNTHETIC",
    "government_api": "NOT_CONNECTED",
    "authorization_status": AuthorizationStatus.NOT_AUTHORIZED.value,
    "live": False,
    "provider_code": PROVIDER_CODE,
    "provider_name": PROVIDER_NAME,
    "label": LABEL,
    "notice": NOTICE,
}

# Category-keyed synthetic review asks. They reference the approval's own
# requirement list (our catalogue), are prefixed "[DEMO QUERY — SYNTHETIC]"
# and are never presented as real government communication.
_SYNTHETIC_ASKS: dict[str, list[str]] = {
    "ENVIRONMENT": [
        "Upload the {doc} cited in the application",
        "Provide a process-flow description of the plant showing the points where emissions or effluents arise",
    ],
    "SAFETY": [
        "Upload the {doc} listed in the requirement checklist",
        "Provide the signed safety-management undertaking from the applicant",
    ],
    "LABOUR": [
        "Upload the {doc} evidencing the declared workforce",
        "Clarify the working-hours and wage register details",
    ],
    "BUSINESS": [
        "Upload the {doc} so the registration details can be checked against the application",
    ],
    "LAND": ["Upload the {doc} evidencing site tenure", "Clarify the site layout and access details"],
    "TAX": ["Upload the {doc} evidencing registration", "Confirm the declared turnover figures"],
    "UTILITIES": ["Upload the {doc} for the water/power connection requested"],
    "TRADE": ["Upload the {doc} evidencing the trade activity declared"],
    "INDUSTRY_SPECIFIC": ["Upload the {doc} required for this licence category"],
}


def demo_available() -> tuple[bool, str | None]:
    """Demo workflows exist for demonstration deployments; production requires
    an explicit double opt-in."""
    if settings.environment == "production" and not settings.demo_allow_in_production:
        return False, "Demo workflows are disabled in production deployments."
    if not settings.allow_demo_workflows:
        return False, "Demo workflows are disabled in this deployment (NIECP_ALLOW_DEMO_WORKFLOWS=0)."
    return True, None


def correlation_id() -> str:
    return "COR-" + uuid.uuid4().hex[:12]


def _next_reference(db: Session) -> str:
    year = utcnow().year
    prefix = f"NIECP-DEMO-{year}-"
    count = db.scalar(
        select(func.count()).select_from(models.Application).where(
            models.Application.official_reference.like(prefix + "%")
        )
    ) or 0
    return f"{prefix}{count + 1:04d}"


def _meta() -> dict[str, Any]:
    return dict(METADATA)


def _missing_blockers(application: models.Application) -> list[str]:
    """Readiness blockers recorded on the preparation package."""
    summary = application.preparation_summary or {}
    blockers: list[str] = []
    for r in summary.get("requirements", []):
        if r.get("mandatory") and not r.get("satisfied"):
            blockers.append(f"Requirement not satisfied: {r.get('title')}")
    for doc in (summary.get("missing_documents") or [])[:6]:
        blockers.append(f"Document missing: {doc if isinstance(doc, str) else doc.get('title', 'document')}")
    for fact in summary.get("profile_facts_missing", [])[:6]:
        blockers.append(f"Information requires confirmation: {fact}")
    return blockers


# ---------------------------------------------------------------- submit
def submit(
    db: Session,
    *,
    application: models.Application,
    user: models.User,
    project: models.Project,
) -> dict[str, Any]:
    """Submit the application into the DEMO environment (synthetic).

    The caller (router) is responsible for the explicit user confirmation gate;
    this function performs the state transition and audit trail."""
    corr = correlation_id()
    reference = _next_reference(db)
    previous = application.status

    application.is_demo = True
    application.integration_mode = IntegrationMode.DEMO
    application.provider = PROVIDER_CODE
    application.correlation_id = corr
    application.official_reference = reference
    application.official_reference_source = SourceStatus.DEMO
    application.status = ApplicationStatus.SUBMITTED
    application.submitted_at = utcnow()
    application.submitted_by_user = False  # NOT submitted to any real authority
    data = dict(application.application_data or {})
    data["demo"] = _meta()
    application.application_data = data

    approval = application.project_approval
    application.status_is_self_reported = False  # demo engine, not the user

    for status_value, reason in (
        (ApplicationStatus.SUBMITTED, "Received by NIECP Demo Government (synthetic environment)"),
        (ApplicationStatus.UNDER_REVIEW, "Demo reviewing officer picked up the application (synthetic)"),
    ):
        db.add(models.ApplicationStatusHistory(
            application_id=application.id, status=status_value, previous_status=previous if status_value == ApplicationStatus.SUBMITTED else ApplicationStatus.SUBMITTED,
            changed_by=user.id, reason=reason, source_status=SourceStatus.DEMO, effective_at=utcnow(),
        ))

    # The demo officer raises a synthetic query immediately after pickup so the
    # full query→translate→respond→approve loop can be demonstrated.
    _raise_synthetic_query(db, application=application, user=user, approval=approval)

    notify(
        db, user_id=user.id, project_id=project.id, organization_id=project.organization_id,
        notification_type="APPLICATION_STATUS_CHANGE",
        title=f"{LABEL} Application {reference} submitted to the demo environment",
        body="This is a demonstration submission using synthetic data — no government authority received anything.",
        severity="INFO", link=f"/projects/{project.id}/applications",
        payload={"demo": True, "reference": reference}, commit=False,
    )
    audit_event(
        db, action="DEMO_SUBMITTED", action_category="GOVERNMENT_EXECUTION",
        user_id=user.id, project_id=project.id, organization_id=project.organization_id,
        resource_type="application", resource_id=str(application.id),
        before={"status": previous.value if previous else None},
        after={"status": ApplicationStatus.SUBMITTED.value, "reference": reference},
        correlation_id=corr, integration_mode=IntegrationMode.DEMO.value, provider=PROVIDER_CODE,
        details={"environment": "DEMO", "data_source": "SYNTHETIC"},
        commit=True,
    )
    return {
        "demo": _meta(),
        "application_reference": reference,
        "correlation_id": corr,
        "status": ApplicationStatus.UNDER_REVIEW.value,
        "notice": NOTICE,
    }


def _raise_synthetic_query(db: Session, *, application: models.Application, user: models.User, approval) -> None:
    category = (approval.category if approval else None) or "BUSINESS"
    template_code = application.approval_template_code or (approval.template_code if approval else None)
    asks: list[str] = []
    if approval is not None:
        for req in approval.requirements:
            if req.is_mandatory and not req.is_satisfied and len(asks) < 2:
                asks.append(f"Upload the “{req.title}” (currently missing from the application package)")
    doc_name = (application.preparation_summary or {}).get("missing_documents") or []
    for d in doc_name[:1]:
        asks.append(f"Upload the “{d if isinstance(d, str) else d.get('title', 'required document')}”")
    if not asks:
        for extra in _SYNTHETIC_ASKS.get(category, _SYNTHETIC_ASKS["BUSINESS"])[:1]:
            asks.append(extra.format(doc="primary supporting certificate"))
    text = (
        "[DEMO QUERY — SYNTHETIC] The demonstration reviewing officer requests the following "
        "before the synthetic review can proceed:\n"
        + "\n".join(f"{i+1}. {a}" for i, a in enumerate(asks[:3]))
        + "\n(This query was generated by the NIECP demo engine. It is not a real government communication.)"
    )
    db.add(models.GovernmentQuery(
        project_id=application.project_id, application_id=application.id,
        authority=f"{application.authority or 'Demo Authority'} — NIECP Demo Government",
        reference_number=f"DEMO-Q-{application.official_reference}-1",
        query_text=text, date_received=date.today(),
        deadline=date.today() + timedelta(days=7),
        status=QueryStatus.OPEN, required_documents=[], source_status=SourceStatus.DEMO, is_demo=True,
    ))
    application.status = ApplicationStatus.QUERY_RAISED
    db.add(models.ApplicationStatusHistory(
        application_id=application.id, status=ApplicationStatus.QUERY_RAISED,
        previous_status=ApplicationStatus.UNDER_REVIEW, changed_by=user.id,
        reason="Demo officer raised a synthetic query", source_status=SourceStatus.DEMO, effective_at=utcnow(),
    ))
    if approval is not None:
        approval.node_state = ApprovalNodeState.QUERY_RAISED
    notify(
        db, user_id=user.id, project_id=application.project_id, organization_id=application.organization_id,
        notification_type="APPLICATION_QUERY",
        title=f"{LABEL} Synthetic query raised on {application.official_reference}",
        body="The demo environment raised a query so the translation → response loop can be demonstrated.",
        severity="WARNING", link=f"/projects/{application.project_id}/queries",
        payload={"demo": True}, commit=False,
    )


# ---------------------------------------------------------------- status
def _auto_advance(db: Session, application: models.Application, user: models.User, now: datetime) -> bool:
    """Dwell-based progression of automatic stages. QUERY_RAISED deliberately
    waits for the user; everything else advances after the simulated dwell."""
    dwell = max(0, settings.demo_dwell_seconds)
    changed = False
    last_dt = application.updated_at or application.created_at or now
    elapsed = (now - last_dt).total_seconds()

    if application.status == ApplicationStatus.SUBMITTED and elapsed >= dwell:
        application.status = ApplicationStatus.UNDER_REVIEW
        db.add(models.ApplicationStatusHistory(
            application_id=application.id, status=ApplicationStatus.UNDER_REVIEW,
            previous_status=ApplicationStatus.SUBMITTED, changed_by=user.id,
            reason="Demo review in progress (synthetic)", source_status=SourceStatus.DEMO, effective_at=now,
        ))
        changed = True
    elif application.status == ApplicationStatus.USER_RESPONDED and elapsed >= dwell:
        _approve(db, application=application, user=user, now=now)
        changed = True
    return changed


def advance(db: Session, application: models.Application, user: models.User) -> str:
    """DEMO CONTROL — force the next automatic transition immediately
    (used by the demo driver and the test-suite; always audited)."""
    now = utcnow()
    if application.status == ApplicationStatus.SUBMITTED:
        application.status = ApplicationStatus.UNDER_REVIEW
        db.add(models.ApplicationStatusHistory(
            application_id=application.id, status=ApplicationStatus.UNDER_REVIEW,
            previous_status=ApplicationStatus.SUBMITTED, changed_by=user.id,
            reason="Demo control: advance to review (synthetic)", source_status=SourceStatus.DEMO, effective_at=now,
        ))
    elif application.status == ApplicationStatus.USER_RESPONDED:
        _approve(db, application=application, user=user, now=now)
    else:
        return application.status.value
    audit_event(
        db, action="DEMO_ADVANCED", action_category="GOVERNMENT_EXECUTION",
        user_id=user.id, project_id=application.project_id,
        resource_type="application", resource_id=str(application.id),
        after={"status": application.status.value},
        correlation_id=application.correlation_id, integration_mode=IntegrationMode.DEMO.value,
        provider=PROVIDER_CODE, commit=True,
    )
    return application.status.value


def _approve(db: Session, *, application: models.Application, user: models.User, now: datetime) -> None:
    previous = application.status
    application.status = ApplicationStatus.APPROVED
    application.decision_date = now.date()
    application.valid_until = now.date() + timedelta(days=365)
    data = dict(application.application_data or {})
    category = (application.project_approval.category if application.project_approval else "BUSINESS") or "BUSINESS"
    data["demo_approval_conditions"] = [
        "[SYNTHETIC DEMO CONDITION] Operate the unit as described in the synthetic application.",
        f"[SYNTHETIC DEMO CONDITION] Maintain records relevant to the {category.lower()} category for inspection demonstrations.",
        "[SYNTHETIC DEMO CONDITION] Renew before the synthetic validity expires — NIECP-AI tracks this as a renewal task.",
    ]
    application.application_data = data
    db.add(models.ApplicationStatusHistory(
        application_id=application.id, status=ApplicationStatus.APPROVED,
        previous_status=previous, changed_by=user.id,
        reason="Synthetic approval by NIECP Demo Government", source_status=SourceStatus.DEMO, effective_at=now,
    ))
    approval = application.project_approval
    if approval is not None:
        approval.node_state = ApprovalNodeState.APPROVED
    # Reuse the platform's renewal engine — same as a user-reported approval.
    db.add(models.Renewal(
        project_id=application.project_id, organization_id=application.organization_id,
        title=f"Renewal: {application.title}", renewal_type="APPLICATION",
        approval_code=application.approval_template_code, application_id=application.id,
        issued_date=now.date(), due_date=application.valid_until, status="UPCOMING",
        official_portal_url=application.official_portal_url, source_status=SourceStatus.DEMO, is_demo=True,
    ))
    notify(
        db, user_id=user.id, project_id=application.project_id, organization_id=application.organization_id,
        notification_type="APPLICATION_STATUS_CHANGE",
        title=f"{LABEL} {application.official_reference} approved in the demo environment",
        body="Synthetic decision — demonstrates the approval → conditions → compliance → renewal flow. No government authority was involved.",
        severity="SUCCESS", link=f"/projects/{application.project_id}/applications",
        payload={"demo": True}, commit=False,
    )
    audit_event(
        db, action="DEMO_DECISION_RECORDED", action_category="GOVERNMENT_EXECUTION",
        user_id=user.id, project_id=application.project_id,
        resource_type="application", resource_id=str(application.id),
        before={"status": previous.value if previous else None},
        after={"status": "APPROVED", "valid_until": application.valid_until.isoformat()},
        correlation_id=application.correlation_id, integration_mode=IntegrationMode.DEMO.value,
        provider=PROVIDER_CODE, details={"data_source": "SYNTHETIC"}, commit=False,
    )


# ---------------------------------------------------------------- response
def respond(
    db: Session,
    *,
    application: models.Application,
    query: models.GovernmentQuery,
    response_text: str,
    user: models.User,
) -> dict[str, Any]:
    previous = application.status
    query.response_text = response_text
    query.responded_at = utcnow()
    query.user_confirmed_response_at = utcnow()
    query.status = QueryStatus.RESPONDED
    application.status = ApplicationStatus.USER_RESPONDED
    db.add(models.ApplicationStatusHistory(
        application_id=application.id, status=ApplicationStatus.USER_RESPONDED,
        previous_status=previous, changed_by=user.id,
        reason="Response filed to the synthetic demo query", source_status=SourceStatus.DEMO, effective_at=utcnow(),
    ))
    audit_event(
        db, action="QUERY_RESPONSE_SUBMITTED", action_category="GOVERNMENT_EXECUTION",
        user_id=user.id, project_id=application.project_id,
        resource_type="government_query", resource_id=str(query.id),
        before={"status": previous.value if previous else None},
        after={"status": ApplicationStatus.USER_RESPONDED.value, "query_status": "RESPONDED"},
        correlation_id=application.correlation_id, integration_mode=IntegrationMode.DEMO.value,
        provider=PROVIDER_CODE, details={"environment": "DEMO", "data_source": "SYNTHETIC"},
        commit=True,
    )
    return {"demo": _meta(), "status": application.status.value, "notice": NOTICE}


# ---------------------------------------------------------------- payloads
def demo_payload(db: Session, application: models.Application) -> dict[str, Any]:
    """Full demo view of an application — always proclaims its synthetic nature."""
    queries = [
        {
            "id": q.id, "reference": q.reference_number, "status": q.status.value,
            "query_text": q.query_text, "deadline": q.deadline.isoformat() if q.deadline else None,
            "response_text": q.response_text, "responded_at": q.responded_at.isoformat() if q.responded_at else None,
            "is_demo": True,
        }
        for q in application.queries
    ]
    timeline = [
        {"status": h.status.value, "reason": h.reason, "at": (h.effective_at or h.created_at).isoformat() if (h.effective_at or h.created_at) else None}
        for h in application.history
    ]
    return {
        "demo": _meta(),
        "application_id": application.id,
        "application_reference": application.official_reference,
        "correlation_id": application.correlation_id,
        "title": application.title,
        "authority": application.authority,
        "approval_template_code": application.approval_template_code,
        "status": application.status.value,
        "submitted_at": application.submitted_at.isoformat() if application.submitted_at else None,
        "decision_date": application.decision_date.isoformat() if application.decision_date else None,
        "valid_until": application.valid_until.isoformat() if application.valid_until else None,
        "demo_approval_conditions": (application.application_data or {}).get("demo_approval_conditions", []),
        "queries": queries,
        "timeline": timeline,
        "workflow": "DEMO WORKFLOW SIMULATION",
        "notice": NOTICE,
    }
