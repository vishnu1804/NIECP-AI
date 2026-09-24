"""MSME Regulatory Intelligence endpoints (MSME upgrade §1–§13).

All regulatory conclusions come from the deterministic msme_engine over the
project profile and the versioned MSMED knowledge layer. Nothing here claims
official verification, fabricates classifications, or gives legal advice.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..knowledge.data import msmed_data as M
from ..services import msme_engine
from ..services.audit import audit_event
from ..services.auth_service import get_current_user, project_access

router = APIRouter(tags=["msme"])


@router.get("/projects/{project_id}/msme/intelligence")
def msme_intelligence(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """The full MSME Regulatory Intelligence module for a project."""
    project = project_access(db, user, project_id)
    profile = project.profile
    payload = msme_engine.regulatory_profile(db, project)
    payload["law_versions"] = {
        "current_applied": M.CURRENT_VERSION_ID,
        "versions": M.LAW_VERSIONS,
        "warning": M.VERSION_WARNING,
    }
    audit_event(db, action="MSME_INTELLIGENCE_VIEWED", action_category="MSME", user_id=user.id,
                project_id=project.id, resource_type="project", commit=True)
    return payload


@router.get("/msme/law-versions")
def law_versions(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """§10 — version control for the law: full §7 criteria version table with
    the standing freshness warning."""
    return {"current_applied": M.CURRENT_VERSION_ID, "versions": M.LAW_VERSIONS, "warning": M.VERSION_WARNING}


@router.get("/projects/{project_id}/msme/classification")
def msme_classification(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    if project.profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Complete the project profile first.")
    result = msme_engine._classification_result(project.profile)
    result["registration"] = msme_engine._registration_check(db, project, project.profile, result)
    return result


class PaymentAssessment(BaseModel):
    supplier_enterprise_class: str = Field(min_length=2, max_length=40)
    invoice_date: str
    supply_date: str | None = None
    amount: float = Field(gt=0)
    buyer_type: str | None = Field(default=None, max_length=120)
    payment_terms_days: int | None = Field(default=None, ge=1, le=365)
    payment_date: str | None = None
    as_of: str | None = None


@router.post("/projects/{project_id}/msme/payment-assessment")
def payment_assessment(project_id: int, body: PaymentAssessment, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """§6 — MSME Payment Protection (informational regulatory assessment)."""
    project = project_access(db, user, project_id)
    result = msme_engine.payment_assessment(
        invoice_date=body.invoice_date, supply_date=body.supply_date, amount=body.amount,
        payment_terms_days=body.payment_terms_days, payment_date=body.payment_date,
        supplier_class=body.supplier_enterprise_class.upper(), as_of=body.as_of,
    )
    if result.get("ok"):
        result["buyer_type"] = body.buyer_type
        audit_event(db, action="MSME_PAYMENT_ASSESSMENT", action_category="MSME", user_id=user.id,
                    project_id=project.id, resource_type="msme_payment_assessment",
                    correlation_id="COR-MSME-" + body.invoice_date.replace("-", "") + "-" + str(abs(hash((body.amount, body.invoice_date, body.payment_date or ""))) % 10000),
                    integration_mode="OFFLINE_ANALYSIS", provider="msmed_act_knowledge",
                    details={"delayed": result.get("delayed_payment_flag"), "supplier_class": body.supplier_enterprise_class},
                    commit=True)
    return result


@router.get("/projects/{project_id}/msme/alerts")
def msme_alerts(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    return {"alerts": msme_engine.compliance_alerts(db, project),
            "note": "Alerts are computed from your project data and the authored MSMED digest — verify at the official sources."}


@router.get("/projects/{project_id}/msme/smart-action-guide")
def smart_action_guide(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    return {"guide": msme_engine.smart_action_guide(db, project),
            "note": "Generated dynamically from your project profile and regulatory state."}


@router.get("/projects/{project_id}/msme/maitri-services")
def maitri_services(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """§8 — Maharashtra MAITRI service layer (OFFICIAL_REDIRECT only)."""
    project = project_access(db, user, project_id)
    profile = project.profile
    state = (profile.state_code if profile else None) or ""
    services = M.maitri_for_state(state)
    # §9 — link the project's own identified approvals to the (generic) MAITRI
    # route. Authored guidance only; specific service-ID mappings are never invented.
    from ..enums import Applicability
    approval_links = []
    if services:
        active = db.scalars(
            select(models.ProjectApproval).where(
                models.ProjectApproval.project_id == project.id,
                models.ProjectApproval.applicability.in_([Applicability.APPLIES, Applicability.CONDITIONAL]),
                models.ProjectApproval.user_dismissed.is_(False),
            )
        ).all()
        for pa in active[:12]:
            route = M.maitri_route_for_approval(pa.category.value if pa.category else None, pa.authority)
            svc = next((s for s in services if s["code"] == route["maitri_service_code"]), None)
            approval_links.append({
                "approval": pa.name,
                "authority": pa.authority,
                "state": "Maharashtra",
                "maitri_service": {"code": svc["code"], "name": svc["name"]} if svc else None,
                "mapping_type": route["mapping_type"],
                "required_information": svc["required_info"] if svc else [],
                "dependency": svc["dependency"] if svc else None,
                "official_channel": M.SOURCE_MAITRI,
                "verification_status": route["verification_status"],
                "note": route["note"],
            })
    return {
        "state_code": state.upper(),
        "relevant": bool(services),
        "integration_mode": "OFFICIAL_REDIRECT",
        "notice": "MAITRI is the official Maharashtra facilitation portal. NIECP-AI shows why a service may apply and links the official portal — it never automates submission (no authorized API).",
        "services": [
            {
                "code": s["code"], "name": s["name"], "department": s["department"],
                "sub_department": s.get("sub_department"), "description": s.get("description"),
                "why": s["why"],
                "required_info": s["required_info"], "dependency": s["dependency"],
                "tat_days": s.get("tat_days"), "tat_note": s.get("tat_note"),
                "official_url": s["official_channel"],
                "official_channel": s["official_channel"], "verification_status": s["verification_status"],
                "approval_links": s.get("approval_links") or [],
                "application_status": "USER_TRACKED — record progress on the Applications/Compliance modules after filing on the portal",
            }
            for s in services
        ],
        "approval_links": approval_links,
        "hint": None if services else "MAITRI applies to Maharashtra projects — set the project state to MH in the profile.",
    }


@router.get("/msme/provisions/{section}/explain")
def explain_provision(section: str, project_id: int | None = None, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """§9 — document intelligence: 'What does this section mean for my project?'
    Deterministic explanation from the authored digest + the project context."""
    prov = M.PROVISIONS.get(section)
    if prov is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That section is not in the modelled MSMED knowledge base.")
    project = project_access(db, user, project_id) if project_id else None
    profile = project.profile if project else None

    if profile is not None:
        classification = msme_engine._classification_result(profile)
        cls = classification.get("potential_class")
        is_mse = cls in ("MICRO", "SMALL")
        if section == "7":
            applicable, plain = ("APPLICABLE", f"Your profile indicates class {cls} under the versioned §7 criteria. {classification['declaration']}")
        elif section == "8":
            has = bool(profile.udyam_number)
            applicable = "APPLICABLE" if is_mse else "CONDITIONAL"
            plain = (f"You classify as {cls}. " + ("Your profile records an Udyam number — keep it current."
                     if has else "No Udyam registration is recorded — registering (free, official portal) unlocks MSME protections.")
                     if is_mse else "The §8 registration framework primarily concerns Micro/Small enterprises; verify the current rules for your class.")
        elif section in ("15", "16", "17", "18"):
            applicable = "CONDITIONAL"
            plain = (f"For you as a {cls} supplier, these provisions protect against delayed payments — the interest is compound with monthly rests at 3× the RBI bank rate, and the MSEFC is the enforcement route."
                     if is_mse else "These provisions protect Micro & Small suppliers. If you BUY from MSME suppliers, they bind you as a buyer; if you sell as a larger entity, contractual remedies usually apply.")
        elif section == "22":
            buys = getattr(profile, "buys_from_msme_suppliers", None)
            applicable = "APPLICABLE" if buys else "CONDITIONAL"
            plain = ("You confirmed you procure from MSME suppliers: your annual accounts must disclose unpaid MSME principal + interest beyond the appointed day."
                     if buys else "This applies if you buy from Micro/Small suppliers — confirm the buyer-side flag in MSME Intelligence.")
        elif section == "23":
            applicable, plain = "CONDITIONAL", "If §15/§16 interest becomes payable by you as a buyer, that interest is not income-tax deductible — discuss the specifics with your tax advisor."
        else:
            applicable = "INFORMATIONAL" if M.PROVISIONS[section].get("summary") else "CONDITIONAL"
            plain = f"Informational provision: {M.PROVISIONS[section]['title'].lower()} — see the summary and official source."
    else:
        applicable = "CONDITIONAL"
        plain = "Select a project so NIECP-AI can contextualise this section with your profile (classification, registration, buyer/supplier role)."

    return {
        "section": prov["section"],
        "act": prov["act"],
        "title": prov["title"],
        "plain_language_explanation": plain,
        "applicable_condition": {"status": applicable, "conditions": prov["applicability_conditions"]},
        "required_inputs": prov["required_inputs"],
        "required_documents": prov["required_documents"],
        "required_action": prov["recommended_action"],
        "authority": prov["authority"],
        "official_source": prov["official_source"],
        "confidence": "MEDIUM",
        "verification_status": prov["verification_status"],
        "labels": ["REGULATORY DOCUMENT", "AI INFERENCE"],
        "authored_note": prov["authored_note"],
        "disclaimer": "Authored digest of the Act — not legal advice and not a substitute for the statutory text.",
    }
