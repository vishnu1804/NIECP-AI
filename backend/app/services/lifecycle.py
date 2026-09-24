"""Lifecycle intelligence services (MVP §K/§M/§N/§Q/§R/§O).

All three engines are STATE-DRIVEN: they compute from actual database state
(project facts, approvals, dependencies, documents, queries, applications) and
never invent anything. SLA values are labelled CONFIGURED unless the authority
has verified them; bottlenecks come only from the dependency graph + states;
the application package is generated from real rows, never a hardcoded sample.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..enums import (
    Applicability,
    ApprovalNodeState,
    ApplicationStatus,
    DocumentStatus,
    QueryStatus,
    ValidationSeverity,
)


# ═══════════════════════════════════ APPLICATION PACKAGE (§M) ══
def application_package(db: Session, project: models.Project) -> dict[str, Any]:
    """Generate the submission package from ACTUAL database state: verified
    project facts, applicable approvals with checklists, documents with
    validation findings, missing items, dependencies, readiness, unresolved
    issues and official submission links."""
    profile = project.profile
    approvals = db.scalars(select(models.ProjectApproval).where(models.ProjectApproval.project_id == project.id)).all()
    active = [a for a in approvals if a.applicability in (Applicability.APPLIES, Applicability.CONDITIONAL) and not a.user_dismissed]
    order = {Applicability.APPLIES: 0, Applicability.CONDITIONAL: 1}
    active.sort(key=lambda a: (order.get(a.applicability, 2), a.graph_layer, a.name))

    docs = db.scalars(select(models.Document).where(models.Document.project_id == project.id)).all()
    unresolved_findings = []
    for d in docs:
        for v in d.validations:
            if v.resolved_at is None and v.severity in (ValidationSeverity.BLOCKING, ValidationSeverity.ERROR, ValidationSeverity.WARNING):
                unresolved_findings.append({
                    "document": d.title, "check": v.title, "detail": v.detail,
                    "expected": v.expected_value, "found": v.found_value,
                    "severity": v.severity.value, "action": v.auto_fix_hint or "Review and resolve in Documents.",
                })

    missing_items: list[dict[str, Any]] = []
    approval_rows = []
    for a in active:
        reqs = [{"title": r.title, "satisfied": r.is_satisfied, "mandatory": r.is_mandatory,
                 "category": r.document_category.value if r.document_category else None} for r in a.requirements]
        for r in a.requirements:
            if not r.is_satisfied:
                missing_items.append({"approval": a.name, "item": r.title, "kind": "DOCUMENT", "mandatory": r.is_mandatory})
        for f in (a.missing_information or []):
            missing_items.append({"approval": a.name, "item": f if isinstance(f, str) else f.get("field"), "kind": "FACT", "mandatory": True})
        approval_rows.append({
            "template_code": a.template_code, "approval": a.name, "authority": a.authority,
            "status": a.node_state.value if a.node_state else None,
            "applicability": a.applicability.value,
            "why_applicable": a.why_it_applies,
            "legal_basis": a.legal_basis or [],
            "documents": reqs,
            "prerequisites": a.dependencies or [],
            "dependents": a.dependents or [],
            "official_source": {"name": a.official_portal_name, "url": a.official_portal_url},
            "verification_status": a.source_status.value if a.source_status else None,
        })

    from . import readiness as readiness_service
    snap = project.readiness_snapshot or {}
    if not snap:
        try:
            snap = readiness_service.compute_readiness(db, project) or {}
        except Exception:
            snap = {}

    open_queries = db.scalars(select(models.GovernmentQuery).where(
        models.GovernmentQuery.project_id == project.id,
        models.GovernmentQuery.status.in_([QueryStatus.OPEN, QueryStatus.IN_PROGRESS]))).all()

    project_facts = _twin_facts(profile)

    state_portal = None
    if profile is not None and (profile.state_code or "").upper() == "MH":
        state_portal = {"name": "Maharashtra MAITRI", "url": "https://maitri.maharashtra.gov.in/", "mode": "MANUAL_HANDOFF"}

    return {
        "project": {"id": project.id, "name": project.name, "is_demo": project.is_demo,
                    "industry": profile.industry_code if profile else None,
                    "state_code": profile.state_code if profile else None},
        "project_facts": project_facts,
        "approvals": approval_rows,
        "documents": [{"id": d.id, "title": d.title, "status": d.status.value if d.status else None,
                       "expires_on": d.expiry_date.isoformat() if d.expiry_date else None} for d in docs[:40]],
        "validation_findings": unresolved_findings,
        "missing_items": missing_items,
        "dependencies": [{"from": dep, "to": a.template_code} for a in active for dep in (a.dependencies or [])],
        "readiness": {"overall": snap.get("overall"), "note": "APPLICATION PREPARATION READINESS — never a probability of approval.",
                      "components": snap.get("components", [])},
        "unresolved_issues": {
            "queries": [{"id": q.id, "authority": q.authority, "text": (q.query_text or "")[:200],
                         "deadline": q.deadline.isoformat() if q.deadline else None, "status": q.status.value} for q in open_queries],
            "validation_findings": len(unresolved_findings),
        },
        "official_submission": {
            "approval_portals": sorted({(a["official_source"]["url"], a["official_source"]["name"]) for a in approval_rows if a["official_source"]["url"]}, key=lambda x: x[0] or "")[:8],
            "nsws": {"name": "National Single Window System", "url": "https://www.nsws.gov.in/", "mode": "OFFICIAL_REDIRECT"},
            "state_route": state_portal,
        },
        "boundary": {
            "REAL": "Package contents are generated from your actual project records and deterministic rule results.",
            "SOURCE_BACKED": "Approval metadata comes from authored regulatory sources — confirm with the authority.",
            "MANUAL": "Submission happens on the official portal, by you. NIECP-AI never submits.",
            "NOT_CLAIMED": "No government response, submission id or approval decision is claimed or faked.",
        },
        "generated_at": datetime.utcnow().isoformat(),
    }


def _twin_facts(profile) -> list[dict[str, Any]]:
    """Project Twin core facts with provenance (MVP §C)."""
    if profile is None:
        return []
    def f(label, value, source="Project profile", source_type="USER_PROVIDED", verification="USER_PROVIDED"):
        return {"label": label, "value": value, "source": source, "source_type": source_type, "verification_state": verification}
    return [
        f("Company / organization type", profile.organization_type),
        f("PAN", profile.pan), f("GSTIN", profile.gstin), f("CIN", profile.cin),
        f("Udyam number (declared)", profile.udyam_number),
        f("Project type", profile.project_type.value if profile.project_type else None),
        f("Industry (NIC)", profile.industry_code),
        f("State", profile.state_code), f("District", profile.district),
        f("PIN code", profile.pincode),
        f("Total investment (₹)", profile.total_investment),
        f("Machinery investment (₹)", profile.machinery_investment),
        f("Annual turnover (₹)", getattr(profile, "annual_turnover", None)),
        f("Employment generated", profile.employment_generated),
        f("Land tenure", profile.land_tenure.value if profile.land_tenure else None),
        f("Land area (sqm)", profile.land_area_sqm),
        f("Built-up area (sqm)", profile.built_up_area_sqm),
        f("Project stage", profile.project_stage.value if profile.project_stage else None),
        f("Production capacity", profile.production_capacity),
        f("Power load (kW)", profile.electrical_load_kw),
        f("Water consumption (KLD)", profile.water_consumption_kld),
        f("Wastewater generated (KLD)", profile.wastewater_generated_kld),
        f("Hazardous waste generated", profile.hazardous_waste_generated),
        f("Chemicals used", ", ".join(profile.chemicals_used or []) or None),
        f("Boiler", f"{profile.boiler_capacity_tph} TPH" if profile.boiler_capacity_tph else None),
        f("DG set", f"{profile.dg_set_kva} kVA" if profile.dg_set_kva else None),
    ]


# ═══════════════════════════════════════ SLA ENGINE (§Q) ══
def sla_for_application(db: Session, app: models.Application) -> dict[str, Any]:
    """State-driven SLA tracking. Base days come from the catalogue
    (estimated_timeline_days) and are labelled CONFIGURED — never VERIFIED —
    until the authority confirms them. Demo applications are labelled DEMO."""
    base_days: int | None = None
    if app.approval_template_code:
        tpl = db.scalars(select(models.ApprovalTemplate).where(models.ApprovalTemplate.code == app.approval_template_code)).first()
        if tpl is not None and tpl.estimated_timeline_days:
            base_days = int(tpl.estimated_timeline_days)
    sla_label = "DEMO" if app.is_demo else "CONFIGURED"

    if app.status == ApplicationStatus.APPROVED:
        return {"application_id": app.id, "status": "COMPLETED", "base_days": base_days, "base_label": sla_label,
                "note": "Decision recorded" + (" (demo)" if app.is_demo else "") + "."}
    if app.status in (ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN, ApplicationStatus.CANCELLED):
        return {"application_id": app.id, "status": "COMPLETED", "base_days": base_days, "base_label": sla_label,
                "note": f"Closed as {app.status.value}."}
    if app.submitted_at is None:
        return {"application_id": app.id, "status": "NOT_STARTED", "base_days": base_days, "base_label": sla_label,
                "note": "Not submitted yet — SLA clock starts on submission (record it when it happens)."}

    now = datetime.utcnow()
    queries = db.scalars(select(models.GovernmentQuery).where(models.GovernmentQuery.application_id == app.id)).all()
    paused_days = 0.0
    paused_now = False
    for q in queries:
        start = q.date_received or (q.created_at.date() if q.created_at else None)
        if start is None:
            continue
        end = (q.responded_at.date() if q.responded_at else (q.user_confirmed_response_at.date() if q.user_confirmed_response_at else None))
        if end is None and q.status in (QueryStatus.OPEN, QueryStatus.IN_PROGRESS):
            paused_now = True
            end = now.date()
        if end is not None:
            paused_days += max(0, (end - start).days)

    elapsed = (now - app.submitted_at).days
    running = max(0, elapsed - int(paused_days))
    if base_days is None:
        status = "PAUSED" if paused_now else "RUNNING_UNCONFIGURED"
        return {"application_id": app.id, "status": status, "base_days": None, "base_label": sla_label,
                "elapsed_days": elapsed, "paused_days": int(paused_days), "running_days": running,
                "note": ("Paused while an authority query is open." if paused_now else
                         "No verified/catalogue SLA for this approval — record the authority's acknowledged timeline."),
                "queries_pausing": [q.id for q in queries if q.status in (QueryStatus.OPEN, QueryStatus.IN_PROGRESS)]}

    remaining = base_days - running
    pct = running / max(1, base_days)
    if paused_now:
        status = "PAUSED"
    elif remaining < 0:
        status = "BREACHED"
    elif pct >= 0.7:
        status = "APPROACHING"
    else:
        status = "ON_TRACK"
    return {
        "application_id": app.id, "status": status, "base_days": base_days, "base_label": sla_label,
        "elapsed_days": elapsed, "paused_days": int(paused_days), "running_days": running,
        "remaining_days": remaining, "escalation": status == "BREACHED",
        "queries_pausing": [q.id for q in queries if q.status in (QueryStatus.OPEN, QueryStatus.IN_PROGRESS)],
        "note": ("Authority elapsed vs applicant-response time; paused days exclude open-query waiting periods." if status != "PAUSED"
                 else "Paused while an authority query is open — SLA clock excluded for the waiting period."),
        "disclaimer": "SLA base value is CONFIGURED from the authored catalogue — confirm the binding timeline with the authority.",
    }


def project_sla(db: Session, project: models.Project) -> dict[str, Any]:
    apps = db.scalars(select(models.Application).where(models.Application.project_id == project.id)).all()
    rows = [sla_for_application(db, a) for a in apps]
    breached = [r for r in rows if r["status"] == "BREACHED"]
    return {"applications": rows,
            "summary": {"total": len(rows),
                        "breached": len(breached), "approaching": sum(1 for r in rows if r["status"] == "APPROACHING"),
                        "paused": sum(1 for r in rows if r["status"] == "PAUSED"), "on_track": sum(1 for r in rows if r["status"] == "ON_TRACK")},
            "labels": ["CONFIGURED — not authority-verified", "DEMO where the application is a demo journey"]}


# ═══════════════════════════════════ BOTTLENECK ENGINE (§R) ══
def project_bottlenecks(db: Session, project: models.Project) -> dict[str, Any]:
    """Causal, project-specific bottlenecks: approval state + dependency graph +
    queries + SLA + missing documents. No generic AI risk score."""
    approvals = db.scalars(select(models.ProjectApproval).where(models.ProjectApproval.project_id == project.id)).all()
    by_code = {a.template_code: a for a in approvals}
    active = [a for a in approvals if a.applicability in (Applicability.APPLIES, Applicability.CONDITIONAL) and not a.user_dismissed]

    def downstream(code: str) -> list[str]:
        seen: set[str] = set()
        stack = [code]
        while stack:
            cur = stack.pop()
            a = by_code.get(cur)
            for dep in (a.dependents if a else []) or []:
                if dep not in seen and dep in by_code:
                    seen.add(dep)
                    stack.append(dep)
        names = []
        for c in sorted(seen):
            d = by_code.get(c)
            if d is not None and d.applicability in (Applicability.APPLIES, Applicability.CONDITIONAL) and not d.user_dismissed:
                names.append(d.name)
        return names

    out: list[dict[str, Any]] = []
    for a in active:
        causes: list[str] = []
        if a.node_state == ApprovalNodeState.BLOCKED:
            unmet = [by_code[d].name for d in (a.dependencies or []) if d in by_code and by_code[d].node_state not in (ApprovalNodeState.COMPLETED, ApprovalNodeState.APPROVED)]
            if unmet:
                causes.append("waiting on prerequisite: " + "; ".join(unmet[:3]))
        unsatisfied = [r.title for r in a.requirements if not r.is_satisfied]
        if unsatisfied and a.node_state in (ApprovalNodeState.BLOCKED, ApprovalNodeState.WAITING, ApprovalNodeState.NOT_STARTED):
            causes.append(f"missing documents: {unsatisfied[0]}" + (f" (+{len(unsatisfied)-1} more)" if len(unsatisfied) > 1 else ""))
        open_q = db.scalars(select(models.GovernmentQuery).where(
            models.GovernmentQuery.project_id == project.id,
            models.GovernmentQuery.application_id.in_([ap.id for ap in db.scalars(select(models.Application).where(models.Application.project_id == project.id)).all()]),
            models.GovernmentQuery.status.in_([QueryStatus.OPEN, QueryStatus.IN_PROGRESS]))).all() if True else []
        if a.node_state == ApprovalNodeState.QUERY_RAISED:
            causes.append("authority query open — respond to resume the clock")
        if a.applicability == Applicability.CONDITIONAL and (a.missing_information or []):
            causes.append("information required: " + ", ".join(str(f.get('field') if isinstance(f, dict) else f) for f in a.missing_information[:3]))
        if not causes:
            continue
        impact = downstream(a.template_code)
        sla_row = None
        app_row = db.scalars(select(models.Application).where(
            models.Application.project_id == project.id, models.Application.approval_template_code == a.template_code)).first()
        if app_row is not None:
            sla_row = sla_for_application(db, app_row)
            if sla_row.get("status") == "BREACHED":
                causes.append("SLA breached — escalate with the authority")
        severity = "HIGH" if (a.is_on_critical_path or len(impact) >= 2 or (sla_row or {}).get("status") == "BREACHED") else ("MEDIUM" if impact else "LOW")
        out.append({
            "bottleneck": a.name,
            "template_code": a.template_code,
            "authority": a.authority,
            "state": a.node_state.value if a.node_state else None,
            "causes": causes,
            "downstream_impact": impact,
            "project_impact": (f"Blocks {len(impact)} downstream approval(s)" + (" — on the critical path" if a.is_on_critical_path else "")) if impact else "No downstream approvals blocked",
            "sla": sla_row,
            "severity": severity,
            "is_demo": bool(project.is_demo),
        })
    out.sort(key=lambda b: {"HIGH": 0, "MEDIUM": 1, "LOW": 2}[b["severity"]])
    return {
        "bottlenecks": out,
        "summary": {"total": len(out), "high": sum(1 for b in out if b["severity"] == "HIGH")},
        "note": "Derived only from approval states, the dependency graph, open queries, SLA and missing documents — no AI risk score.",
    }


# ═══════════════════════ LIFECYCLE DERIVATION (§O) ══
_LIFECYCLE_MAP = {
    ApplicationStatus.DRAFT: "DRAFT",
    ApplicationStatus.READY_TO_APPLY: "READY",
    ApplicationStatus.USER_CONFIRMED: "READY",
    ApplicationStatus.SUBMITTED: "SUBMITTED",
    ApplicationStatus.UNDER_REVIEW: "UNDER_SCRUTINY",
    ApplicationStatus.QUERY_RAISED: "QUERY_RAISED",
    ApplicationStatus.USER_RESPONDED: "APPLICANT_RESPONDED",
    ApplicationStatus.INSPECTION: "UNDER_SCRUTINY",
    ApplicationStatus.APPROVED: "APPROVED",
    ApplicationStatus.REJECTED: "REJECTED",
    ApplicationStatus.WITHDRAWN: "CLOSED",
    ApplicationStatus.EXPIRED: "CLOSED",
    ApplicationStatus.RENEWAL_DUE: "SLA_RUNNING",
    ApplicationStatus.CANCELLED: "CLOSED",
}


def lifecycle_for_application(db: Session, app: models.Application) -> dict[str, Any]:
    """State-driven lifecycle view over the real ApplicationStatus + queries +
    SLA. Simulated/demo events stay labelled; nothing is claimed as a real
    government event."""
    stage = _LIFECYCLE_MAP.get(app.status, app.status.value if app.status else "DRAFT")
    open_query = db.scalars(select(models.GovernmentQuery).where(
        models.GovernmentQuery.application_id == app.id,
        models.GovernmentQuery.status.in_([QueryStatus.OPEN, QueryStatus.IN_PROGRESS]))).first()
    if open_query is not None:
        stage = "APPLICANT_RESPONSE_REQUIRED"
    sla = sla_for_application(db, app)
    if stage in ("SUBMITTED", "UNDER_SCRUTINY", "QUERY_RAISED", "APPLICANT_RESPONDED", "SLA_RUNNING"):
        stage = stage  # keep; SLA surfaces separately
    simulated = bool(app.is_demo)
    return {
        "application_id": app.id,
        "stage": stage,
        "stored_status": app.status.value if app.status else None,
        "sla_status": sla.get("status"),
        "simulated": simulated,
        "label": "SIMULATED — internal demo journey, not a real government event" if simulated else "SELF-REPORTED / SOURCE-BACKED — record real events with references",
        "query": {"id": open_query.id, "deadline": open_query.deadline.isoformat() if open_query and open_query.deadline else None,
                  "overdue": bool(open_query and open_query.deadline and open_query.deadline < date.today())} if open_query else None,
    }
