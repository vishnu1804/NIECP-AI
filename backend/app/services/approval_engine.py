"""
Approval Discovery Engine (spec §7, §11, §12, §13).

Responsibilities:
  * load the curated catalogue into the database (templates, rules, edges);
  * run discovery for a project: evaluate every active rule against the
    project's fact map and persist ProjectApproval rows with full provenance;
  * derive dependency-graph node states from upstream approvals, documents and
    applications;
  * compute the critical path and the next-best-action list.

The rule engine's verdicts are never overridden here or anywhere else. An LLM
may only *explain* them.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..ai.rule_engine import (
    RuleContext,
    evaluate_rule,
    explain_rule,
    missing_facts_for,
    required_fact_names,
)
from ..enums import (
    Applicability,
    ApprovalCategory,
    ApprovalNodeState,
    AuditResult,
    Confidence,
    Jurisdiction,
    SourceStatus,
    TaskPriority,
    TaskStatus,
)
from ..knowledge.data.approval_data import APPROVALS, DEPENDENCY_EDGES
from ..knowledge.data.states import state_name
from .audit import audit_event
from .profile_facts import build_context, label_for

log = logging.getLogger("niecp.approvals")


# ═════════════════════════════════════════════════════ CATALOGUE LOADER ══
def sync_catalogue(db: Session, source_status: SourceStatus = SourceStatus.REQUIRES_VERIFICATION) -> dict[str, int]:
    """Upsert templates, rules and dependency edges from the curated data."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    counts = {"templates": 0, "rules": 0, "edges": 0}

    existing = {t.code: t for t in db.scalars(select(models.ApprovalTemplate)).all()}
    for entry in APPROVALS:
        tpl = existing.get(entry["code"])
        if tpl is None:
            tpl = models.ApprovalTemplate(code=entry["code"])
            db.add(tpl)
        tpl.name = entry["name"]
        tpl.name_ta = entry.get("name_ta")
        tpl.name_hi = entry.get("name_hi")
        tpl.category = ApprovalCategory(entry["category"])
        tpl.authority = entry["authority"]
        tpl.jurisdiction = Jurisdiction(entry["jurisdiction"])
        tpl.description = entry.get("description")
        tpl.why_it_may_apply = entry.get("why_it_may_apply")
        tpl.applicability_conditions = entry.get("applicability_conditions") or []
        tpl.required_documents = entry.get("required_documents") or []
        tpl.process_summary = entry.get("process_summary")
        tpl.estimated_timeline_days = entry.get("estimated_timeline_days")
        tpl.statutory_timeline_text = entry.get("statutory_timeline_text")
        tpl.fee_information = entry.get("fee_information")
        tpl.validity_text = entry.get("validity_text")
        tpl.renewal_period_months = entry.get("renewal_period_months")
        tpl.official_portal_name = entry.get("official_portal_name")
        tpl.official_portal_url = entry.get("official_portal_url")
        tpl.legal_basis = entry.get("legal_basis") or []
        tpl.graph_layer = entry.get("graph_layer", 1)
        tpl.source_status = SourceStatus(entry.get("source_status", source_status.value))
        tpl.confidence = Confidence(entry.get("confidence", Confidence.REQUIRES_VERIFICATION.value))
        tpl.verification_note = entry.get("verification_note")
        counts["templates"] += 1
        if tpl.id is None:
            db.flush()  # assign the id before rules reference it

        rule_entry = {
            "rule_key": f"{entry['code']}.primary",
            "condition": entry["rule"],
            "explanation_template": entry.get("why_it_may_apply"),
            "produces_applicability": Applicability.APPLIES,
        }
        rule = db.scalars(
            select(models.ApprovalRule).where(models.ApprovalRule.rule_key == rule_entry["rule_key"])
        ).first()
        if rule is None:
            rule = models.ApprovalRule(template_id=tpl.id, rule_key=rule_entry["rule_key"])
            db.add(rule)
        rule.condition = rule_entry["condition"]
        rule.explanation_template = rule_entry["explanation_template"]
        rule.produces_applicability = rule_entry["produces_applicability"]
        rule.required_question_keys = required_fact_names(rule_entry["condition"])
        rule.is_active = True
        counts["rules"] += 1
    db.flush()

    edge_pairs = {(e["parent"], e["child"]) for e in DEPENDENCY_EDGES}
    existing_edges = {
        (e.parent_code, e.child_code): e for e in db.scalars(select(models.ApprovalDependencyTemplate)).all()
    }
    for edge in DEPENDENCY_EDGES:
        key = (edge["parent"], edge["child"])
        obj = existing_edges.get(key)
        if obj is None:
            obj = models.ApprovalDependencyTemplate(parent_code=key[0], child_code=key[1])
            db.add(obj)
        obj.dependency_type = edge.get("dependency_type", "PREREQUISITE")
        counts["edges"] += 1
    # deactivate edges removed from the catalogue
    for key, obj in existing_edges.items():
        if key not in edge_pairs:
            db.delete(obj)
    db.flush()
    return counts


# ═══════════════════════════════════════════════════════ DISCOVERY RUN ══
# ═══════════════════════════════════════════ DECISION TRAIL (§G) ══
def _record_decision_trail(db: Session, *, project, tpl, rule, result, applicability, produced, ctx, is_demo: bool) -> None:
    """Immutable WHY-record for every evaluated approval rule (MVP §G):
    project, rule, approval, input facts, result, missing info, evidence,
    source, rule version, timestamp, engine version."""
    from ..config import settings as _settings
    trail = models.DecisionTrail(
        project_id=project.id,
        approval_template_code=tpl.code,
        approval_name=tpl.name,
        authority=tpl.authority,
        rule_key=rule.rule_key if rule else None,
        rule_expression=rule.condition if rule else (result.expression if result else None),
        result=applicability.value if hasattr(applicability, "value") else str(applicability),
        triggering_facts=dict(result.facts_used or {}) if result else {},
        missing_facts=list(result.facts_missing or []) if result else [],
        explanation=explain_rule(result, ctx, rule.explanation_template if rule else None) if result else None,
        legal_basis=list(tpl.legal_basis or []),
        source_url=tpl.official_portal_url,
        source_status=(rule.source_status.value if rule is not None and getattr(rule, "source_status", None) else (tpl.source_status.value if tpl.source_status else None)),
        rule_version=(f"rule:{rule.rule_key}" if rule else None),
        engine_version=f"niecp-rules/{_settings.version}",
        is_demo=is_demo,
    )
    db.add(trail)


def _applicability_from_rule(produced: str) -> Applicability:
    return {
        "APPLIES": Applicability.APPLIES,
        "NOT_APPLICABLE": Applicability.NOT_APPLICABLE,
        "UNKNOWN": Applicability.CONDITIONAL,
    }.get(produced, Applicability.UNKNOWN)


def _node_state_for(pa: models.ProjectApproval, db: Session) -> ApprovalNodeState:
    """Derive the dependency-graph node state (spec §11) from real project state."""
    # an explicit outcome recorded by the user (or verified API) wins
    app = db.scalars(
        select(models.Application).where(
            models.Application.project_approval_id == pa.id,
            models.Application.status.in_(
                [models.ApplicationStatus.APPROVED, models.ApplicationStatus.REJECTED]
            ),
        )
    ).first()
    if app is not None:
        return ApprovalNodeState.APPROVED if app.status == models.ApplicationStatus.APPROVED else ApprovalNodeState.REJECTED

    live = db.scalars(
        select(models.Application).where(
            models.Application.project_approval_id == pa.id,
            models.Application.status.in_(
                [
                    models.ApplicationStatus.SUBMITTED,
                    models.ApplicationStatus.UNDER_REVIEW,
                    models.ApplicationStatus.INSPECTION,
                ]
            ),
        )
    ).first()
    if live is not None:
        return ApprovalNodeState.SUBMITTED

    open_query = db.scalars(
        select(models.GovernmentQuery).where(
            models.GovernmentQuery.project_id == pa.project_id,
            models.GovernmentQuery.status.in_([models.QueryStatus.OPEN, models.QueryStatus.IN_PROGRESS]),
        )
    ).first()
    if open_query is not None and pa.node_state in (ApprovalNodeState.SUBMITTED, ApprovalNodeState.QUERY_RAISED):
        return ApprovalNodeState.QUERY_RAISED

    if pa.user_dismissed:
        return ApprovalNodeState.COMPLETED

    if pa.applicability == Applicability.NOT_APPLICABLE:
        return ApprovalNodeState.COMPLETED

    # blocked when any unresolved prerequisite approval is not complete
    for dep_code in pa.dependencies or []:
        dep = db.scalars(
            select(models.ProjectApproval).where(
                models.ProjectApproval.project_id == pa.project_id,
                models.ProjectApproval.template_code == dep_code,
            )
        ).first()
        if dep is not None and dep.applicability == Applicability.APPLIES and dep.node_state not in (
            ApprovalNodeState.COMPLETED,
            ApprovalNodeState.APPROVED,
        ):
            return ApprovalNodeState.BLOCKED

    if pa.applicability == Applicability.APPLIES and not pa.user_dismissed:
        return ApprovalNodeState.READY

    return ApprovalNodeState.WAITING


def run_discovery(
    db: Session,
    project: models.Project,
    actor: models.User | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Evaluate all active catalogue rules for the project and persist results."""
    profile = project.profile
    ctx = build_context(project, profile)

    templates = db.scalars(
        select(models.ApprovalTemplate).where(models.ApprovalTemplate.is_active.is_(True))
    ).all()
    rules_by_template: dict[int, list[models.ApprovalRule]] = {}
    for rule in db.scalars(select(models.ApprovalRule).where(models.ApprovalRule.is_active.is_(True))):
        rules_by_template.setdefault(rule.template_id, []).append(rule)

    existing = {
        pa.template_code: pa
        for pa in db.scalars(
            select(models.ProjectApproval).where(models.ProjectApproval.project_id == project.id)
        )
    }

    summary = {
        "applies": 0,
        "conditional": 0,
        "not_applicable": 0,
        "created": 0,
        "updated": 0,
        "missing_information": [],
    }
    seen_codes: set[str] = set()
    missing_union: set[str] = set()

    for tpl in templates:
        seen_codes.add(tpl.code)
        rules = rules_by_template.get(tpl.id, [])
        if not rules:
            continue

        best: dict[str, Any] = {"produced": "NOT_APPLICABLE", "result": None, "rule": None}
        order = {"APPLIES": 0, "UNKNOWN": 1, "NOT_APPLICABLE": 2}
        for rule in sorted(rules, key=lambda r: (r.priority, r.id)):
            result = evaluate_rule(rule.condition, ctx, rule.rule_key)
            if result.produced == "APPLIES":
                best = {"produced": "APPLIES", "result": result, "rule": rule}
                break
            if order[result.produced] < order[best["produced"]]:
                best = {"produced": result.produced, "result": result, "rule": rule}

        result = best["result"]
        rule = best["rule"]
        produced = best["produced"]
        applicability = _applicability_from_rule(produced)

        pa = existing.get(tpl.code)
        if pa is None:
            pa = models.ProjectApproval(
                project_id=project.id,
                template_id=tpl.id,
                template_code=tpl.code,
            )
            db.add(pa)
            summary["created"] += 1

        pa.name = tpl.name
        pa.category = tpl.category
        pa.authority = tpl.authority
        pa.jurisdiction = tpl.jurisdiction
        pa.graph_layer = tpl.graph_layer

        if result is not None:
            pa.applicability = applicability
            pa.source_status = (
                SourceStatus.REQUIRES_VERIFICATION
                if applicability in (Applicability.APPLIES, Applicability.CONDITIONAL)
                else SourceStatus.AI_INTERPRETATION
            )
            pa.confidence = (
                Confidence.HIGH
                if applicability == Applicability.APPLIES and not result.facts_missing
                else (Confidence.MEDIUM if applicability == Applicability.APPLIES else Confidence.REQUIRES_VERIFICATION)
            )
            pa.matched_rule_keys = [rule.rule_key] if rule else []
            pa.why_it_applies = (
                explain_rule(result, ctx, rule.explanation_template if rule else None)
                if applicability != Applicability.NOT_APPLICABLE
                else explain_rule(result, ctx)
            )
            pa.matched_facts = [
                {"field": k, "label": label_for(k), "value": v} for k, v in (result.facts_used or {}).items()
            ]
            pa.missing_information = [
                {"field": f, "label": label_for(f)} for f in (result.facts_missing or [])
            ]
            _record_decision_trail(db, project=project, tpl=tpl, rule=rule, result=result,
                                   applicability=applicability, produced=produced, ctx=ctx, is_demo=bool(project.is_demo))
            for m in result.facts_missing or []:
                missing_union.add(m)

        pa.official_portal_name = tpl.official_portal_name
        pa.official_portal_url = tpl.official_portal_url
        pa.legal_basis = tpl.legal_basis or []
        pa.verification_note = tpl.verification_note
        pa.last_verified_at = tpl.last_verified_at
        pa.estimated_timeline_days = tpl.estimated_timeline_days
        summary["updated"] += 1

        counts = {"APPLIES": "applies", "UNKNOWN": "conditional", "NOT_APPLICABLE": "not_applicable"}
        summary[counts.get(produced, "updated")] = summary.get(counts.get(produced, "updated"), 0) + 1

    db.flush()

    # requirements checklist per approval (documents the authority will ask for)
    for pa in db.scalars(
        select(models.ProjectApproval).where(models.ProjectApproval.project_id == project.id)
    ):
        tpl = pa.template
        if tpl is None:
            continue
        existing_reqs = {r.title for r in pa.requirements}
        for idx, doc in enumerate(tpl.required_documents or []):
            if doc not in existing_reqs:
                db.add(
                    models.ProjectApprovalRequirement(
                        project_approval_id=pa.id,
                        project_id=project.id,
                        requirement_type="DOCUMENT",
                        title=doc,
                        document_category=_guess_doc_category(pa.category, doc),
                        is_mandatory=True,
                        source_status=SourceStatus.REQUIRES_VERIFICATION,
                        order_index=idx,
                    )
                )

    # dependencies / dependents from catalogue edges
    edges = db.scalars(select(models.ApprovalDependencyTemplate)).all()
    deps_by_child: dict[str, list[str]] = {}
    deps_by_parent: dict[str, list[str]] = {}
    for e in edges:
        deps_by_child.setdefault(e.child_code, []).append(e.parent_code)
        deps_by_parent.setdefault(e.parent_code, []).append(e.child_code)

    for pa in db.scalars(
        select(models.ProjectApproval).where(models.ProjectApproval.project_id == project.id)
    ):
        pa.dependencies = sorted(set(deps_by_child.get(pa.template_code, [])) & seen_codes)
        pa.dependents = sorted(set(deps_by_parent.get(pa.template_code, [])) & seen_codes)
        pa.node_state = _node_state_for(pa, db)
    db.flush()

    mark_critical_path(db, project)

    project.last_ai_analysis_at = datetime.now(timezone.utc).replace(tzinfo=None)
    summary["missing_information"] = sorted(missing_union)
    audit_event(
        db,
        user_id=actor.id if actor else None,
        user_email=actor.email if actor else None,
        action="ai.analysis.run",
        action_category="AI",
        project_id=project.id,
        resource_type="project",
        resource_id=str(project.id),
        result=AuditResult.SUCCESS,
        details={"applies": summary["applies"], "conditional": summary["conditional"]},
        agent="APPROVAL",
        request_id=request_id,
        user_agent=user_agent,
    )
    db.commit()
    return summary


def _guess_doc_category(category: ApprovalCategory, doc_title: str) -> models.DocumentCategory | None:
    text = doc_title.lower()
    if any(k in text for k in ("land", "lease", "allotment", "patta", "title", "survey")):
        return models.DocumentCategory.LAND
    if any(k in text for k in ("pan", "aadhaar", "identity", "identity proof", "kyc")):
        return models.DocumentCategory.IDENTITY
    if any(k in text for k in ("certificate of incorporation", "moa", "aoa", "llp", "udyam", "gstin", "entity")):
        return models.DocumentCategory.BUSINESS
    if any(k in text for k in ("financial", "bank", "statement", "balance sheet", "audit")):
        return models.DocumentCategory.FINANCIAL
    if any(k in text for k in ("effluent", "emission", "waste", "environment", "consent", "water balance")):
        return models.DocumentCategory.ENVIRONMENTAL
    if any(k in text for k in ("fire", "safety", "stability", "emergency")):
        return models.DocumentCategory.SAFETY
    if any(k in text for k in ("labour", "employee", "worker", "wage")):
        return models.DocumentCategory.LABOUR
    if any(k in text for k in ("plan", "drawing", "layout", "technical", "process flow")):
        return models.DocumentCategory.TECHNICAL
    if category == ApprovalCategory.ENVIRONMENT:
        return models.DocumentCategory.ENVIRONMENTAL
    if category == ApprovalCategory.SAFETY:
        return models.DocumentCategory.SAFETY
    if category == ApprovalCategory.LAND:
        return models.DocumentCategory.LAND
    if category == ApprovalCategory.BUSINESS:
        return models.DocumentCategory.BUSINESS
    return models.DocumentCategory.OTHER


def mark_critical_path(db: Session, project: models.Project) -> list[str]:
    """Spec §12 — the ordered chain of open items on the dependency backbone."""
    approvals = db.scalars(
        select(models.ProjectApproval).where(models.ProjectApproval.project_id == project.id)
    ).all()
    by_code = {pa.template_code: pa for pa in approvals}

    # topological order over applies/conditional nodes
    order: list[str] = []
    visited: set[str] = set()

    def visit(code: str, stack: set[str]) -> None:
        if code in visited or code in stack:
            return
        stack.add(code)
        for parent in by_code.get(code, models.ProjectApproval()).dependencies or []:
            if parent in by_code:
                visit(parent, stack)
        stack.discard(code)
        visited.add(code)
        order.append(code)

    for code in list(by_code):
        visit(code, set())

    path: list[str] = []
    for code in order:
        pa = by_code[code]
        active = pa.applicability in (Applicability.APPLIES, Applicability.CONDITIONAL) and not pa.user_dismissed
        done = pa.node_state in (ApprovalNodeState.COMPLETED, ApprovalNodeState.APPROVED)
        pa.is_on_critical_path = bool(active and not done)
        if active and not done:
            path.append(code)
    db.flush()
    return path


# convenience for routers -----------------------------------------------------
def get_critical_path(db: Session, project: models.Project) -> list[dict[str, Any]]:
    mark_critical_path(db, project)
    db.commit()
    approvals = db.scalars(
        select(models.ProjectApproval)
        .where(models.ProjectApproval.project_id == project.id)
        .order_by(models.ProjectApproval.graph_layer, models.ProjectApproval.order_index)
    ).all()
    path: list[dict[str, Any]] = []
    for pa in approvals:
        if pa.is_on_critical_path:
            path.append(
                {
                    "step": len(path) + 1,
                    "template_code": pa.template_code,
                    "name": pa.name,
                    "category": pa.category.value if pa.category else None,
                    "node_state": pa.node_state.value if pa.node_state else None,
                    "authority": pa.authority,
                    "portal_url": pa.official_portal_url,
                }
            )
    return path


def graph_payload(db: Session, project: models.Project) -> dict[str, Any]:
    """Spec §11 — nodes + edges for the visual dependency graph."""
    approvals = db.scalars(
        select(models.ProjectApproval)
        .where(models.ProjectApproval.project_id == project.id)
        .order_by(models.ProjectApproval.graph_layer)
    ).all()
    nodes = []
    edges = []
    templates_by_code = {t.code: t for t in db.scalars(select(models.ApprovalTemplate)).all()}
    for pa in approvals:
        if pa.applicability == Applicability.NOT_APPLICABLE and pa.node_state == ApprovalNodeState.NOT_STARTED:
            continue
        tpl = templates_by_code.get(pa.template_code)
        missing = pa.missing_information or []
        nodes.append(
            {
                "id": pa.template_code,
                "db_id": pa.id,
                "name": pa.name,
                "category": pa.category.value if pa.category else None,
                "layer": pa.graph_layer,
                "state": pa.node_state.value if pa.node_state else ApprovalNodeState.NOT_STARTED.value,
                "applicability": pa.applicability.value if pa.applicability else None,
                "authority": pa.authority,
                "jurisdiction": pa.jurisdiction.value if pa.jurisdiction else None,
                "portal_url": pa.official_portal_url,
                "portal_name": pa.official_portal_name,
                "official_channel": {"name": pa.official_portal_name, "url": pa.official_portal_url} if pa.official_portal_url else None,
                "is_on_critical_path": pa.is_on_critical_path,
                "documents_ready": sum(1 for r in pa.requirements if r.is_satisfied),
                "documents_total": len(pa.requirements),
                "why_it_applies": pa.why_it_applies,
                "facts_used": pa.matched_facts or [],
                "missing_facts": missing,
                "information_required": bool(missing),
                "requires_verification": (pa.source_status == SourceStatus.REQUIRES_VERIFICATION),
                "verification_status": pa.source_status.value if pa.source_status else None,
                "legal_basis": (tpl.legal_basis if tpl is not None else None) or pa.legal_basis or [],
                "rule_keys": pa.matched_rule_keys or [],
                "estimated_timeline_days": tpl.estimated_timeline_days if tpl is not None else None,
            }
        )
        for dep in pa.dependencies or []:
            edges.append({"from": dep, "to": pa.template_code})
    return {"nodes": nodes, "edges": edges}
