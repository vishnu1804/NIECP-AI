"""
Next-Best-Action engine (spec §13) and critical-path presentation (spec §12).

Actions are derived exclusively from actual project state: unresolved profile
gaps, missing documents, blocking dependencies, open queries, due renewals and
staged applications. The LLM never invents actions — it may only rephrase the
ones produced here.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select as _select, select
from sqlalchemy.orm import Session

from .. import models
from ..enums import (
    Applicability,
    ApprovalNodeState,
    ApplicationStatus,
    DocumentStatus,
    QueryStatus,
    RenewalStatus,
    TaskPriority,
    TaskStatus,
    ValidationSeverity,
)
from .profile_facts import label_for


def _act(
    priority: int,
    action_type: str,
    title: str,
    detail: str,
    link: str | None = None,
    cta: str | None = None,
    source_status: str = "AI_INTERPRETATION",
    **extra: Any,
) -> dict[str, Any]:
    out = {
        "priority": priority,
        "type": action_type,
        "title": title,
        "action": title,                 # Smart Action Guide field name
        "detail": detail,
        "reason": detail,                # why this action is suggested
        "link": link,
        "cta": cta,
        "source_status": source_status,
        "verification_status": source_status,
        "blocked_by": extra.get("blocked_by"),
        "required_documents": extra.get("required_documents") or [],
        "official_channel": extra.get("official_channel"),
        "source": extra.get("source"),
    }
    out.update(extra)
    return out


def next_best_actions(db: Session, project: models.Project, limit: int = 6) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    today = date.today()

    # 1. government queries — highest urgency when open
    queries = db.scalars(
        select(models.GovernmentQuery).where(
            models.GovernmentQuery.project_id == project.id,
            models.GovernmentQuery.status.in_([QueryStatus.OPEN, QueryStatus.IN_PROGRESS]),
        )
    ).all()
    for qy in queries:
        overdue = qy.deadline is not None and qy.deadline < today
        actions.append(
            _act(
                0 if overdue else 1,
                "QUERY",
                "Respond to the government query" + (f" on “{qy.reference_number}”" if qy.reference_number else ""),
                (
                    f"Authority: {qy.authority or 'recorded'}. "
                    + ("The deadline has passed — respond and record the outcome as soon as possible." if overdue
                       else f"Deadline: {qy.deadline.isoformat()}.")
                ),
                link="/projects/{pid}/queries",
                cta="Open queries",
                source_status="USER_PROVIDED",
                query_id=qy.id,
                overdue=overdue,
            )
        )

    # 2. overdue / imminent renewals
    renewals = db.scalars(
        select(models.Renewal).where(
            models.Renewal.project_id == project.id,
            models.Renewal.status.in_([RenewalStatus.OVERDUE, RenewalStatus.DUE_SOON, RenewalStatus.UPCOMING]),
        )
    ).all()
    for r in renewals:
        if r.due_date is None:
            continue
        days = (r.due_date - today).days
        if days < 0:
            actions.append(_act(0, "RENEWAL", f"Renewal overdue: {r.title}",
                                f"Due date {r.due_date.isoformat()} has passed. Operating on an expired approval is treated as operating without it.",
                                link="/projects/{pid}/calendar", cta="Open calendar", source_status="USER_PROVIDED", renewal_id=r.id))
        elif days <= 30:
            actions.append(_act(1, "RENEWAL", f"Renew {r.title} soon",
                                f"Expires in {days} day(s) ({r.due_date.isoformat()}). Renewals often need fresh test reports — start early.",
                                link="/projects/{pid}/calendar", cta="Open calendar", source_status="USER_PROVIDED", renewal_id=r.id))

    # 3. blocking document validation findings
    docs = db.scalars(select(models.Document).where(models.Document.project_id == project.id)).all()
    for d in docs:
        if d.expiry_date is not None and d.expiry_date < today and d.status != DocumentStatus.EXPIRED:
            actions.append(_act(1, "DOCUMENT_EXPIRED", f"Document expired: {d.title}",
                                f"Expiry date {d.expiry_date.isoformat()} has passed. Upload a renewed copy or record the renewal.",
                                link="/projects/{pid}/documents", cta="Open documents", source_status="USER_PROVIDED", document_id=d.id))
        blocking = [v for v in d.validations if v.severity in (ValidationSeverity.BLOCKING, ValidationSeverity.ERROR) and v.resolved_at is None]
        if blocking:
            v = blocking[0]
            actions.append(_act(2, "VALIDATION", f"Resolve: {v.title}",
                                v.detail or "A document validation finding needs your attention.",
                                link="/projects/{pid}/documents", cta="Review document", source_status="AI_INTERPRETATION", document_id=d.id))

    # 4. profile gaps that the analysis flagged as required
    profile = project.profile
    if profile is not None and project.last_ai_analysis_at is not None:
        snapshot = project.readiness_snapshot or {}
        for comp in snapshot.get("components", []):
            if comp.get("key") == "profile":
                missing = comp.get("missing", [])
                if missing:
                    labels = ", ".join(m["label"] for m in missing[:3])
                    more = f" and {len(missing) - 3} more" if len(missing) > 3 else ""
                    actions.append(_act(3, "PROFILE", "Complete missing project information",
                                        f"The approval analysis needs: {labels}{more}. Adding these improves the accuracy of your approval map.",
                                        link="/projects/{pid}/profile", cta="Complete profile", source_status="AI_INTERPRETATION"))
                break

    # 5. blocked approvals — tell the user what unblocks them
    approvals = db.scalars(
        select(models.ProjectApproval).where(models.ProjectApproval.project_id == project.id)
    ).all()
    active = [pa for pa in approvals if pa.applicability in (Applicability.APPLIES, Applicability.CONDITIONAL) and not pa.user_dismissed]
    for pa in active:
        if pa.node_state == ApprovalNodeState.BLOCKED:
            deps_names = []
            for dep in pa.dependencies or []:
                d = next((x for x in approvals if x.template_code == dep), None)
                if d is not None and d.node_state not in (ApprovalNodeState.COMPLETED, ApprovalNodeState.APPROVED):
                    deps_names.append(d.name)
            if deps_names:
                actions.append(_act(4, "BLOCKED", f"{pa.name} is waiting on a prerequisite",
                                    f"Complete first: {'; '.join(deps_names[:2])}.",
                                    link="/projects/{pid}/approvals", cta="View approvals", source_status="AI_INTERPRETATION",
                                    blocked_by=deps_names,
                                    official_channel={"name": pa.official_portal_name, "url": pa.official_portal_url} if pa.official_portal_url else None,
                                    source={"name": pa.official_portal_name, "url": pa.official_portal_url} if pa.official_portal_url else None))
        elif pa.node_state == ApprovalNodeState.READY and pa.applicability == Applicability.APPLIES:
            unsatisfied = [r for r in pa.requirements if not r.is_satisfied]
            if unsatisfied and len(actions) < 9:
                actions.append(_act(5, "DOCUMENT", f"Prepare documents for {pa.name}",
                                    f"Next document: {unsatisfied[0].title}.",
                                    link=f"/projects/{{pid}}/approvals?approval={pa.template_code}", cta="View checklist",
                                    source_status="REQUIRES_VERIFICATION",
                                    required_documents=[r.title for r in unsatisfied[:4]],
                                    official_channel={"name": pa.official_portal_name, "url": pa.official_portal_url} if pa.official_portal_url else None))
            else:
                actions.append(_act(5, "APPLY", f"{pa.name} is ready to apply",
                                    "Preparation is complete. Review the application package before opening the official portal.",
                                    link=f"/projects/{{pid}}/approvals?approval={pa.template_code}", cta="Review application",
                                    source_status="REQUIRES_VERIFICATION"))

    # 5b. bottlenecks — causal downstream impact (MVP §R/§T)
    try:
        from .lifecycle import project_bottlenecks
        bn = project_bottlenecks(db, project)
        for b in bn["bottlenecks"][:2]:
            if b["severity"] == "HIGH":
                actions.append(_act(3, "BOTTLENECK", f"Unblock bottleneck: {b['bottleneck']}",
                                    f"{'; '.join(b['causes'][:2])}. Downstream impact: {'; '.join(b['downstream_impact'][:2]) or 'none'}.",
                                    link="/projects/{pid}/approvals", cta="Open approvals",
                                    source_status="AI_INTERPRETATION", blocked_by=b["causes"],
                                    official_channel={"name": b["authority"], "url": None}))
    except Exception:
        pass

    # 5c. SLA breaches / approaching limits (MVP §Q/§T)
    try:
        from .lifecycle import project_sla
        sla = project_sla(db, project)
        for row in sla["applications"]:
            if row.get("status") == "BREACHED":
                actions.append(_act(2, "SLA_BREACHED", "SLA breached — escalate with the authority",
                                    f"Application #{row['application_id']} exceeded its configured timeline ({row.get('running_days')} running days vs {row.get('base_days')} configured; {row.get('paused_days')} paused). Follow up with the authority and record the response.",
                                    link="/projects/{pid}/applications", cta="Open applications",
                                    source_status="REQUIRES_VERIFICATION"))
            elif row.get("status") == "APPROACHING":
                actions.append(_act(4, "SLA_APPROACHING", "SLA approaching — prepare follow-up",
                                    f"Application #{row['application_id']} is at {row.get('running_days')}/{row.get('base_days')} configured days. Timeline is CONFIGURED, not authority-verified.",
                                    link="/projects/{pid}/applications", cta="Open applications",
                                    source_status="REQUIRES_VERIFICATION"))
    except Exception:
        pass

    # 6. run analysis if stale or never run
    if project.profile is not None and project.last_ai_analysis_at is None:
        actions.append(_act(2, "ANALYSIS", "Run the AI project analysis",
                            "Your profile has information that has not been analysed yet. The analysis maps your potential approvals and generates the document checklist.",
                            link="/projects/{pid}/analysis", cta="Run analysis", source_status="AI_INTERPRETATION"))

    # 7. open tasks
    tasks = db.scalars(
        select(models.ComplianceTask).where(
            models.ComplianceTask.project_id == project.id,
            models.ComplianceTask.status.in_([TaskStatus.OPEN, TaskStatus.BLOCKED]),
        ).order_by(models.ComplianceTask.due_date.asc().nullslast())
    ).all()
    for t in tasks[:2]:
        due = f", due {t.due_date.isoformat()}" if t.due_date else ""
        actions.append(_act(6 if t.priority != TaskPriority.CRITICAL else 1, "TASK", f"Task: {t.title}",
                            (t.description or f"Priority: {t.priority.value}.{due}"),
                            link="/projects/{pid}/compliance", cta="Open tasks", source_status="AI_INTERPRETATION", task_id=t.id))

    # 8. government data services (integration-driven actions, computed from real state)
    profile = project.profile
    if profile is not None:
        from sqlalchemy import func as _func
        from ..services.gov_providers import DataGovUdyamAdapter, PincodeAdapter

        if not getattr(profile, "pincode", None) and not profile.district:
            actions.append(_act(
                5, "PROFILE",
                "Validate the project location (PIN code)",
                "A validated PIN/state/district sharpens state-specific regulatory factors. Uses the India Post dataset (data.gov.in) when provisioned, or the offline circle index.",
                link="/projects/{pid}/profile", cta="Enrich location",
                source_status="AI_INTERPRETATION", gov_data=True,
            ))
        gov_refs = db.scalar(_select(_func.count()).select_from(models.GovDataReference).where(models.GovDataReference.project_id == project.id))
        if not gov_refs and profile.udyam_number is None:
            adapter = DataGovUdyamAdapter()
            if adapter.meta.authorization_status == "AUTHORIZED":
                actions.append(_act(
                    5, "PROFILE", "Search the UDYAM/MSME dataset for your enterprise",
                    "Pick your enterprise from the government dataset to enrich the regulatory digital twin with your NIC activity.",
                    link="/projects/{pid}/profile", cta="Search UDYAM dataset",
                    source_status="AI_INTERPRETATION", gov_data=True,
                ))
            else:
                actions.append(_act(
                    6, "INTEGRATION", "Connect government data services",
                    "UDYAM dataset search and DigiLocker document retrieval are awaiting official authorization (data.gov.in / DigiLocker partner access). Meanwhile you can continue through the official portals.",
                    link="/settings/integrations", cta="View integrations",
                    source_status="REQUIRES_VERIFICATION", gov_data=True,
                ))

    actions.sort(key=lambda a: a["priority"])
    return actions[:limit]


def todays_tasks(db: Session, project: models.Project) -> list[dict[str, Any]]:
    today = date.today()
    horizon = today + timedelta(days=7)
    out: list[dict[str, Any]] = []
    tasks = db.scalars(
        select(models.ComplianceTask).where(models.ComplianceTask.project_id == project.id)
    ).all()
    for t in tasks:
        if t.status in (TaskStatus.DONE, TaskStatus.SKIPPED):
            continue
        if t.due_date is not None and t.due_date <= horizon:
            out.append({"kind": "task", "id": t.id, "title": t.title, "due_date": t.due_date.isoformat(), "priority": t.priority.value, "status": t.status.value})
    renewals = db.scalars(select(models.Renewal).where(models.Renewal.project_id == project.id)).all()
    for r in renewals:
        if r.due_date is not None and r.status != RenewalStatus.RENEWED and r.due_date <= horizon:
            out.append({"kind": "renewal", "id": r.id, "title": f"Renew: {r.title}", "due_date": r.due_date.isoformat(), "priority": "HIGH", "status": r.status.value})
    queries = db.scalars(
        select(models.GovernmentQuery).where(
            models.GovernmentQuery.project_id == project.id,
            models.GovernmentQuery.status.in_([QueryStatus.OPEN, QueryStatus.IN_PROGRESS, QueryStatus.READY]),
        )
    ).all()
    for qy in queries:
        if qy.deadline is not None and qy.deadline <= horizon:
            out.append({"kind": "query", "id": qy.id, "title": f"Respond to query: {(qy.reference_number or qy.authority or 'Government query')}", "due_date": qy.deadline.isoformat(), "priority": "CRITICAL", "status": qy.status.value})
    inspections = db.scalars(select(models.Inspection).where(models.Inspection.project_id == project.id)).all()
    for i in inspections:
        if i.inspection_date is not None and today <= i.inspection_date <= horizon and i.status != models.InspectionStatus.CLOSED:
            out.append({"kind": "inspection", "id": i.id, "title": f"Inspection: {i.department or 'Scheduled'}", "due_date": i.inspection_date.isoformat(), "priority": "HIGH", "status": i.status.value})
    out.sort(key=lambda x: x["due_date"])
    return out
