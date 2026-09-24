"""
Application Readiness score (spec §8).

TRANSPARENT BY CONSTRUCTION
---------------------------
The score is a preparation measure — never a probability of approval (no honest
system can promise that, and we say so in the UI). Every component lists the
individual checks that produced it, and the caller returns the full breakdown so
the UI can explain the arithmetic.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..ai.rule_engine import RuleContext
from ..enums import (
    Applicability,
    ApprovalNodeState,
    ApplicationStatus,
    DocumentStatus,
    SourceStatus,
    TaskStatus,
    ValidationSeverity,
)
from ..services.profile_facts import build_context, label_for

# fields the rule engine most often needs, weighted by how many catalogue rules
# reference them (computed once at import from the catalogue itself)
_CORE_FIELDS: tuple[str, ...] = (
    "organization_name",
    "organization_type",
    "state_code",
    "district",
    "industry_code",
    "project_type",
    "total_investment",
    "land_tenure",
    "number_of_employees",
    "production_type",
)


def _rule_referenced_fields(db: Session) -> set[str]:
    fields: set[str] = set()
    for rule in db.scalars(select(models.ApprovalRule).where(models.ApprovalRule.is_active.is_(True))):
        try:
            fields.update(_names(rule.condition))
        except Exception:  # noqa: SIM105
            continue
    return fields


def _names(condition: str) -> set[str]:
    from ..ai.rule_engine import required_fact_names

    return set(required_fact_names(condition))


def profile_completeness(db: Session, project: models.Project) -> dict[str, Any]:
    """How many rule-relevant facts exist, with the missing ones enumerated."""
    profile = project.profile
    ctx = build_context(project, profile)
    referenced = _rule_referenced_fields(db)

    # always include the core identity fields even if no rule references them
    check_fields = sorted(referenced | set(_CORE_FIELDS))
    # exclude derived/internal facts
    check_fields = [f for f in check_fields if not f.startswith("_")]

    present: list[str] = []
    missing: list[str] = []
    for field_name in check_fields:
        val = ctx.facts.get(field_name)
        if val is None or val == "" or val == []:
            missing.append(field_name)
        else:
            present.append(field_name)

    total = max(1, len(check_fields))
    pct = round(100 * len(present) / total)
    return {
        "key": "profile",
        "label": "Profile completeness",
        "score": pct,
        "weight": 0.25,
        "present": [label_for(f) for f in present],
        "missing": [{"field": f, "label": label_for(f)} for f in missing],
        "explanation": (
            f"{len(present)} of {total} profile facts that approval rules and application forms depend on are filled in. "
            "Missing facts are listed; they reduce both this score and the certainty of the approval analysis."
        ),
    }


def documents_readiness(db: Session, project: models.Project) -> dict[str, Any]:
    """Documents required by applicable approvals vs documents actually present."""
    approvals = db.scalars(
        select(models.ProjectApproval).where(models.ProjectApproval.project_id == project.id)
    ).all()
    active = [
        pa
        for pa in approvals
        if pa.applicability in (Applicability.APPLIES, Applicability.CONDITIONAL) and not pa.user_dismissed
    ]
    required: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for pa in active:
        for req in pa.requirements:
            if req.requirement_type != "DOCUMENT" or req.title in seen_titles:
                continue
            seen_titles.add(req.title)
            required.append(
                {
                    "title": req.title,
                    "approval": pa.name,
                    "satisfied": req.is_satisfied,
                    "document_id": req.satisfied_by_document_id,
                }
            )
    docs = db.scalars(select(models.Document).where(models.Document.project_id == project.id)).all()
    healthy_docs = [
        d
        for d in docs
        if d.status
        not in (DocumentStatus.FAILED, DocumentStatus.EXPIRED)
    ]
    satisfied = sum(1 for r in required if r["satisfied"])
    total_docs = len(required) or 1
    coverage = round(100 * satisfied / total_docs)
    # a repository with zero documents at all also drags the score
    if not docs and required:
        coverage = min(coverage, 5)
    upload_score = min(100, round(100 * len(healthy_docs) / max(1, len(required)))) if required else (100 if docs else 0)
    score = round(0.7 * coverage + 0.3 * upload_score)
    missing = [r for r in required if not r["satisfied"]]
    return {
        "key": "documents",
        "label": "Documents",
        "score": score,
        "weight": 0.25,
        "required_count": len(required),
        "satisfied_count": satisfied,
        "uploaded_count": len(docs),
        "missing": [{"title": m["title"], "approval": m["approval"]} for m in missing[:40]],
        "explanation": (
            f"{satisfied} of {len(required)} documents required by your potentially applicable approvals are on file "
            f"and linked. {len(missing)} are still outstanding."
            if required
            else "Run the approval analysis to generate your document checklist."
        ),
    }


def eligibility_information(db: Session, project: models.Project) -> dict[str, Any]:
    """Share of scheme/approval criteria that can actually be evaluated."""
    from ..services.scheme_engine import evaluate_scheme_criteria

    results = evaluate_scheme_criteria(db, project)
    total = 0
    evaluable = 0
    unevaluable: list[str] = []
    for item in results:
        for crit in item["criteria"]:
            total += 1
            if crit["state"] in ("MET", "NOT_MET"):
                evaluable += 1
            else:
                unevaluable.append(crit["human_text"])
    pct = round(100 * evaluable / total) if total else 100
    return {
        "key": "eligibility",
        "label": "Eligibility information",
        "score": pct,
        "weight": 0.15,
        "criteria_total": total,
        "criteria_evaluable": evaluable,
        "unevaluable": unevaluable[:15],
        "explanation": (
            f"{evaluable} of {total} documented eligibility criteria (schemes and approvals you are pursuing) can be "
            "checked against your profile. The rest need more information — they are listed."
            if total
            else "No eligibility criteria to evaluate yet."
        ),
    }


def prerequisites_readiness(db: Session, project: models.Project) -> dict[str, Any]:
    approvals = db.scalars(
        select(models.ProjectApproval).where(models.ProjectApproval.project_id == project.id)
    ).all()
    active = [
        pa
        for pa in approvals
        if pa.applicability in (Applicability.APPLIES, Applicability.CONDITIONAL) and not pa.user_dismissed
    ]
    done_states = (ApprovalNodeState.COMPLETED, ApprovalNodeState.APPROVED)
    done = sum(1 for pa in active if pa.node_state in done_states)
    total = len(active) or 1
    pct = round(100 * done / total)
    blockers = [
        {"approval": pa.name, "state": pa.node_state.value if pa.node_state else None}
        for pa in active
        if pa.node_state == ApprovalNodeState.BLOCKED
    ]
    return {
        "key": "prerequisites",
        "label": "Prerequisites",
        "score": pct,
        "weight": 0.15,
        "approvals_total": len(active),
        "approvals_done": done,
        "blocked": blockers,
        "explanation": (
            f"{done} of {len(active)} potentially applicable approvals/registrations are recorded as complete. "
            "This is your own recorded status — the authority's decision is the official one."
        ),
    }


def application_readiness(db: Session, project: models.Project) -> dict[str, Any]:
    apps = db.scalars(select(models.Application).where(models.Application.project_id == project.id)).all()
    if not apps:
        return {
            "key": "applications",
            "label": "Application readiness",
            "score": 0,
            "weight": 0.10,
            "applications": 0,
            "explanation": "No applications have been prepared yet. After the approval analysis you can prepare one in the Get Approval workflow.",
        }
    prepared = [a for a in apps if a.prepared_at is not None]
    confirmed = [a for a in apps if a.user_confirmed_at is not None]
    moving = [a for a in apps if a.status not in (ApplicationStatus.DRAFT, ApplicationStatus.READY_TO_APPLY)]
    score = round(
        100 * (0.4 * len(prepared) + 0.3 * len(confirmed) + 0.3 * len(moving)) / max(1, len(apps))
    )
    return {
        "key": "applications",
        "label": "Application readiness",
        "score": min(100, score),
        "weight": 0.10,
        "applications": len(apps),
        "prepared": len(prepared),
        "user_confirmed": len(confirmed),
        "in_flight": len(moving),
        "explanation": (
            f"{len(prepared)} of {len(apps)} applications have a complete preparation package and "
            f"{len(confirmed)} have your explicit confirmation recorded."
        ),
    }


def compliance_readiness(db: Session, project: models.Project) -> dict[str, Any]:
    tasks = db.scalars(select(models.ComplianceTask).where(models.ComplianceTask.project_id == project.id)).all()
    open_tasks = [t for t in tasks if t.status in (TaskStatus.OPEN, TaskStatus.BLOCKED)]
    overdue = [t for t in open_tasks if t.due_date is not None and t.due_date < date.today()]
    from ..models import Renewal
    from ..enums import RenewalStatus

    renewals = db.scalars(select(Renewal).where(Renewal.project_id == project.id)).all()
    due_renewals = [r for r in renewals if r.status in (RenewalStatus.OVERDUE, RenewalStatus.DUE_SOON)]
    score = 100
    if tasks:
        penalty = round(100 * len(open_tasks) / len(tasks))
        score -= penalty
    score -= 5 * len(overdue)
    score -= 5 * len(due_renewals)
    return {
        "key": "compliance",
        "label": "Compliance readiness",
        "score": max(0, min(100, score)),
        "weight": 0.10,
        "open_tasks": len(open_tasks),
        "overdue_tasks": len(overdue),
        "renewals_due": len(due_renewals),
        "explanation": (
            f"{len(open_tasks)} open compliance tasks ({len(overdue)} overdue) and {len(due_renewals)} renewals due soon."
        ),
    }


def compute_readiness(db: Session, project: models.Project, persist: bool = True) -> dict[str, Any]:
    """Full readiness payload with per-component explanations (spec §8)."""
    components = [
        profile_completeness(db, project),
        documents_readiness(db, project),
        eligibility_information(db, project),
        prerequisites_readiness(db, project),
        application_readiness(db, project),
        compliance_readiness(db, project),
    ]
    total_weight = sum(c["weight"] for c in components) or 1
    overall = round(sum(c["score"] * c["weight"] for c in components) / total_weight)
    payload = {
        "overall": overall,
        "overall_label": "Overall preparation",
        "components": components,
        "disclaimer": (
            "This is a preparation score, not a probability of approval. It measures how complete your own "
            "information, documents and prerequisites are. Whether an authority grants an approval is decided "
            "only by that authority."
        ),
        "computed_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
    }
    if persist:
        project.readiness_snapshot = payload
        project.last_readiness_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
    return payload
