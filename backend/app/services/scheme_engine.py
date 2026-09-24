"""
Scheme & incentive matching (spec §18, §19).

The Scheme Agent evaluates each scheme's documented criteria against the project
profile and reports, per criterion:
    MET            — the documented criterion is satisfied by user data
    NOT_MET        — the documented criterion is not satisfied by user data
    INFO_REQUIRED  — cannot be evaluated; the profile lacks the information

It never states "you are eligible" — only the authority can determine that. The
aggregate per-scheme verdict is:
    POSSIBLY_RELEVANT / NEEDS_MORE_INFO / LIKELY_NOT_APPLICABLE / UNABLE_TO_ASSESS
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..ai.rule_engine import RuleContext, evaluate_rule
from ..enums import Applicability, AuditResult, Confidence, SourceStatus
from ..knowledge.data.scheme_data import SCHEMES
from .audit import audit_event
from .profile_facts import build_context


def sync_schemes(db: Session) -> int:
    """Upsert the curated scheme catalogue into the database."""
    existing = {s.code: s for s in db.scalars(select(models.Scheme)).all()}
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    count = 0
    for entry in SCHEMES:
        scheme = existing.get(entry["code"])
        if scheme is None:
            scheme = models.Scheme(code=entry["code"])
            db.add(scheme)
        scheme.name = entry["name"]
        scheme.authority = entry["authority"]
        scheme.ministry = entry.get("ministry")
        scheme.level = entry["level"]
        scheme.state_code = entry.get("state_code")
        scheme.categories = entry.get("categories") or []
        scheme.short_description = entry.get("short_description")
        scheme.description = entry.get("description")
        scheme.benefits = entry.get("benefits") or []
        scheme.eligibility_summary = entry.get("eligibility_summary")
        scheme.required_documents = entry.get("required_documents") or []
        scheme.application_process = entry.get("application_process")
        scheme.application_mode = entry.get("application_mode")
        scheme.official_url = entry.get("official_url")
        scheme.official_source_name = entry.get("official_source_name")
        scheme.last_verified_at = None  # set only when an operator verifies
        scheme.verification_status = SourceStatus(entry.get("verification_status", "REQUIRES_VERIFICATION"))
        scheme.confidence = Confidence(entry.get("confidence", "REQUIRES_VERIFICATION"))
        scheme.is_active = True
        count += 1
        if scheme.id is None:
            db.flush()  # assign the id before eligibility rules reference it

        existing_rules = {r.criterion_key: r for r in db.scalars(
            select(models.SchemeEligibility).where(models.SchemeEligibility.scheme_id == scheme.id)
        ).all()} if scheme.id else {}
        seen_keys = set()
        for crit in entry.get("eligibility_criteria", []):
            key = crit["criterion_key"]
            seen_keys.add(key)
            rule = existing_rules.get(key)
            if rule is None:
                rule = models.SchemeEligibility(scheme_id=scheme.id, criterion_key=key)
                db.add(rule)
            rule.expression = crit["expression"]
            rule.human_text = crit["human_text"]
            rule.is_mandatory = True
            rule.data_gap_message = f"Add this information to your project profile so this criterion can be checked."
        for key, rule in existing_rules.items():
            if key not in seen_keys:
                db.delete(rule)
    db.flush()
    return count


def evaluate_scheme_criteria(db: Session, project: models.Project) -> list[dict[str, Any]]:
    """Evaluate every active scheme's criteria for the project."""
    ctx = build_context(project, project.profile)
    schemes = db.scalars(select(models.Scheme).where(models.Scheme.is_active.is_(True))).all()
    rules = db.scalars(select(models.SchemeEligibility)).all()
    rules_by_scheme: dict[int, list[models.SchemeEligibility]] = {}
    for r in rules:
        rules_by_scheme.setdefault(r.scheme_id, []).append(r)

    out: list[dict[str, Any]] = []
    for scheme in schemes:
        criteria: list[dict[str, Any]] = []
        for rule in rules_by_scheme.get(scheme.id, []):
            result = evaluate_rule(rule.expression, ctx, f"{scheme.code}.{rule.criterion_key}")
            if result.produced == "APPLIES":
                state = "MET"
            elif result.produced == "UNKNOWN":
                state = "INFO_REQUIRED"
            else:
                state = "NOT_MET"
            criteria.append(
                {
                    "key": rule.criterion_key,
                    "human_text": rule.human_text,
                    "state": state,
                    "facts_used": result.facts_used,
                    "missing": result.facts_missing,
                    "expression": rule.expression,
                }
            )
        if not criteria:
            continue
        met = sum(1 for c in criteria if c["state"] == "MET")
        not_met = sum(1 for c in criteria if c["state"] == "NOT_MET")
        info = sum(1 for c in criteria if c["state"] == "INFO_REQUIRED")
        if not_met > 0 and met == 0 and info == 0:
            verdict = "LIKELY_NOT_APPLICABLE"
        elif info > 0:
            verdict = "NEEDS_MORE_INFO"
        elif met == len(criteria):
            verdict = "POSSIBLY_RELEVANT"
        elif met > 0:
            verdict = "NEEDS_MORE_INFO"
        else:
            verdict = "UNABLE_TO_ASSESS"

        # hide schemes for other states unless central
        state_mismatch = (
            scheme.level == "STATE" and scheme.state_code and str(ctx.facts.get("state_code") or "").upper() != scheme.state_code
        )
        if state_mismatch:
            continue

        out.append(
            {
                "scheme_id": scheme.id,
                "code": scheme.code,
                "name": scheme.name,
                "authority": scheme.authority,
                "level": scheme.level,
                "state_code": scheme.state_code,
                "categories": scheme.categories,
                "short_description": scheme.short_description,
                "benefits": scheme.benefits,
                "official_url": scheme.official_url,
                "official_source_name": scheme.official_source_name,
                "verification_status": scheme.verification_status.value if scheme.verification_status else None,
                "verdict": verdict,
                "match_score": round(100 * met / len(criteria)),
                "criteria": criteria,
                "met": met,
                "not_met": not_met,
                "info_required": info,
                "why_this_may_apply": _why_text(scheme, criteria, verdict),
                "required_documents": scheme.required_documents or [],
                "application_process": scheme.application_process,
            }
        )
    out.sort(key=lambda x: (x["verdict"] != "POSSIBLY_RELEVANT", -x["match_score"]))
    return out


def _why_text(scheme: models.Scheme, criteria: list[dict[str, Any]], verdict: str) -> str:
    met = [c["human_text"] for c in criteria if c["state"] == "MET"]
    info = [c["human_text"] for c in criteria if c["state"] == "INFO_REQUIRED"]
    not_met = [c["human_text"] for c in criteria if c["state"] == "NOT_MET"]
    parts: list[str] = []
    if verdict == "POSSIBLY_RELEVANT":
        parts.append("Your project data satisfies the documented criteria checked below. Confirm with the authority before relying on this.")
    elif verdict == "NEEDS_MORE_INFO":
        parts.append("Some documented criteria match your project, but others cannot be checked yet.")
    elif verdict == "LIKELY_NOT_APPLICABLE":
        parts.append("Your project data does not satisfy the documented criteria for this scheme.")
    else:
        parts.append("This scheme could not be assessed against your project.")
    if met:
        parts.append("Matched: " + "; ".join(met[:3]) + ".")
    if info:
        parts.append("Still required: " + "; ".join(info[:3]) + ".")
    if not_met:
        parts.append("Not matched: " + "; ".join(not_met[:2]) + ".")
    return " ".join(parts)


def match_schemes(
    db: Session,
    project: models.Project,
    actor: models.User | None = None,
    request_id: str | None = None,
) -> list[dict[str, Any]]:
    results = evaluate_scheme_criteria(db, project)
    audit_event(
        db,
        action="ai.scheme_match.run",
        action_category="AI",
        user_id=actor.id if actor else None,
        user_email=actor.email if actor else None,
        project_id=project.id,
        resource_type="project",
        resource_id=str(project.id),
        details={"relevant": sum(1 for r in results if r["verdict"] == "POSSIBLY_RELEVANT")},
        agent="SCHEME",
        request_id=request_id,
    )
    db.commit()
    return results


def list_schemes(
    db: Session,
    *,
    q: str | None = None,
    level: str | None = None,
    state_code: str | None = None,
    category: str | None = None,
) -> list[models.Scheme]:
    stmt = select(models.Scheme).where(models.Scheme.is_active.is_(True))
    rows = db.scalars(stmt).all()
    out = []
    ql = (q or "").lower()
    for s in rows:
        if level and s.level != level:
            continue
        if state_code and (s.state_code or "").upper() != state_code.upper():
            continue
        if category and category not in (s.categories or []):
            continue
        if ql and ql not in (s.name or "").lower() and ql not in (s.short_description or "").lower() and ql not in " ".join(s.categories or []).lower():
            continue
        out.append(s)
    return out
