"""MSME Regulatory Intelligence engine (MSME upgrade §1–§6, §11, §12).

Deterministic evaluation of the project profile against the MSMED Act
knowledge layer. Core honesty rules:

* Classification is NEVER claimed without the required inputs (investment +
  turnover) — the result is then "CANNOT_DETERMINE (information required)".
* Classification thresholds come from the VERSIONED law table (latest version
  applied), with a standing warning that the user must verify the current
  notification.
* Provision applicability is conditional on the actual legal conditions, not
  blanket-applied.
* Payment assessments are informational regulatory assessments — NOT legal
  advice — with clearly-labelled interest math and placeholder rate.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..enums import EnterpriseClass
from ..knowledge.data import msmed_data as M
from .readiness import profile_completeness

# --------------------------------------------------------------- helpers

def _cr(value: float | None) -> float | None:
    """₹ absolute → ₹ crore (tolerates Decimal from Numeric columns)."""
    return round(float(value) / 1e7, 4) if value is not None else None


def _engine_class(profile) -> tuple[str | None, list[str], dict[str, Any]]:
    """§7 classification per the current law version. Returns
    (class|None-with-None meaning cannot determine, missing inputs, detail)."""
    version = M.LAW_VERSIONS[0]
    table = version["classification"]
    missing: list[str] = []
    inv_cr = _cr(getattr(profile, "machinery_investment", None))
    to_cr = _cr(getattr(profile, "annual_turnover", None))
    if inv_cr is None:
        missing.append("investment in plant & machinery/equipment (profile: machinery_investment)")
    if to_cr is None:
        missing.append("annual turnover (profile: annual_turnover)")
    detail = {
        "law_version": version["version"],
        "law_version_note": version["status_note"],
        "inputs_used": {"machinery_investment_cr": inv_cr, "annual_turnover_cr": to_cr},
        "criteria": "Composite: investment in plant & machinery/equipment AND annual turnover (both within the class limits).",
        "warning": M.VERSION_WARNING,
    }
    if missing:
        return None, missing, detail
    cls = None
    for candidate in ("MICRO", "SMALL", "MEDIUM"):
        limits = table[candidate]
        if inv_cr <= limits["investment_max_cr"] and to_cr <= limits["turnover_max_cr"]:
            cls = candidate
            break
    if cls is None:
        cls = "LARGE_OR_ABOVE_LIMITS"  # exceeds medium limits — not an MSME
    return cls, [], detail


def _classification_result(profile) -> dict[str, Any]:
    cls, missing, detail = _engine_class(profile)
    return {
        "potential_class": cls,
        "enterprise_class_in_profile": getattr(profile, "enterprise_class", None) and (profile.enterprise_class.value if hasattr(profile.enterprise_class, "value") else str(profile.enterprise_class)),
        "missing_inputs": missing,
        "status": "DETERMINED_FROM_USER_INPUTS" if cls and not missing else "INFORMATION_REQUIRED",
        "status_icon": "⚠" if missing else "ℹ",
        "declaration": (
            "This is a data-driven classification per the versioned §7 criteria — not an official government classification. "
            "The official classification is what your Udyam registration records."
            if cls and not missing
            else "NIECP-AI cannot determine a classification without the required inputs — the law requires both investment and turnover figures."
        ),
        **detail,
    }


# ----------------------------------------------------- registration (§8)

def _registration_check(db: Session, project: models.Project, profile, classification: dict) -> dict[str, Any]:
    cls = classification.get("potential_class")
    has_udyam = bool(getattr(profile, "udyam_number", None))
    dataset_ref = db.scalars(
        select(models.GovDataReference).where(
            models.GovDataReference.project_id == project.id,
            models.GovDataReference.service.contains("UDYAM"),
        ).order_by(models.GovDataReference.created_at.desc())
    ).first()
    udyam_dataset_selected = dataset_ref is not None
    if cls in ("MICRO", "SMALL"):
        if has_udyam:
            status = "REGISTERED_AS_PER_PROFILE"
            icon = "⚠"
            note = f"Udyam number {profile.udyam_number} is USER-PROVIDED — NIECP-AI cannot verify registrations in real time."
            action = "Keep the certificate handy; it is required for MSEFC references and most MSME benefits."
        else:
            status = "REGISTRATION_MAY_BE_REQUIRED"
            icon = "❌"
            note = "The project appears to classify as Micro/Small but no Udyam registration number is recorded."
            action = "Register on the official Udyam portal (free) and record the number in the profile."
    elif cls in ("LARGE_OR_ABOVE_LIMITS", "MEDIUM"):
        status = "NOT_APPLICABLE_OR_CHECK_RULES"
        icon = "ℹ"
        note = "Medium enterprises and above: the §8 memorandum obligation and the delayed-payment benefit framework target Micro & Small suppliers — verify the current rules for your class."
        action = "Verify the current registration framework for your class on the Udyam portal."
    else:
        status = "INFORMATION_REQUIRED"
        icon = "⚠"
        note = "Complete the classification inputs first."
        action = "Provide investment and turnover in the profile."
    return {
        "section": "8",
        "status": status,
        "status_icon": icon,
        "udyam_number_recorded": profile.udyam_number or None,
        "provenance": "USER_PROVIDED" if has_udyam else ("DATASET" if udyam_dataset_selected else None),
        "udyam_dataset_reference": {"external_id": dataset_ref.external_id, "verification_status": dataset_ref.verification_status} if dataset_ref else None,
        "note": note,
        "recommended_action": action,
        "official_source": M.SOURCE_UDYAM,
    }


# ----------------------------------------------- provisions (§1, §4, §13)

def _provision_entry(section: str, *, applicable: str, why: str, icon: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    prov = M.PROVISIONS[section]
    return {
        "section": prov["section"],
        "title": prov["title"],
        "topic": prov["topic"],
        "summary": prov["summary"],
        "applicability": applicable,           # APPLICABLE / CONDITIONAL / NOT_APPLICABLE / INFORMATIONAL
        "why": why,
        "status_icon": icon,
        "required_inputs": prov["required_inputs"],
        "required_documents": prov["required_documents"],
        "recommended_action": prov["recommended_action"],
        "authority": prov["authority"],
        "official_source": prov["official_source"],
        "verification_status": prov["verification_status"],
        "label": "REGULATORY DOCUMENT — authored digest; verify at source",
        **(extra or {}),
    }


def applicable_provisions(db: Session, project: models.Project, profile, payment_hint: dict | None = None) -> list[dict[str, Any]]:
    """Evaluate every modelled section against the actual profile conditions."""
    classification = _classification_result(profile)
    cls = classification.get("potential_class")
    is_mse = cls in ("MICRO", "SMALL")
    out: list[dict[str, Any]] = []

    # §7 always evaluated (with honesty about inputs)
    out.append(_provision_entry(
        "7",
        applicable="APPLICABLE" if cls and not classification["missing_inputs"] else "CONDITIONAL",
        why="Every enterprise is classifiable once investment and turnover figures exist."
        if cls and not classification["missing_inputs"]
        else "Classification needs investment + turnover inputs.",
        icon="ℹ" if cls else "⚠",
        extra={"result": classification},
    ))
    # §8 registration
    out.append(_provision_entry("8", applicable="APPLICABLE" if cls in ("MICRO", "SMALL") else ("NOT_APPLICABLE" if cls in ("LARGE_OR_ABOVE_LIMITS", "MEDIUM") else "CONDITIONAL"),
                                why="Registration framework applies to Micro/Small enterprises; check current rules for other classes.",
                                icon="❌" if (is_mse and not profile.udyam_number) else ("⚠" if is_mse else "ℹ")))
    # §9, §10, §11 benefits — conditional on being MSE (+ supply-side confirmation for 11)
    for sec, why in (
        ("9", "Promotion/development measures target MSMEs."),
        ("10", "Credit-facility policies target MSMEs."),
        ("11", "Procurement preference targets Micro/Small suppliers to government buyers."),
    ):
        applicable = "APPLICABLE" if is_mse else ("CONDITIONAL" if cls == "MEDIUM" else "NOT_APPLICABLE")
        if sec == "11" and is_mse:
            applicable = "CONDITIONAL"  # only if selling to government buyers — needs confirmation
        out.append(_provision_entry(sec, applicable=applicable, why=why, icon="ℹ"))
    # §15–§18 delayed-payment chain — supplier scenario
    payment = payment_hint or {}
    if payment.get("delayed"):
        out.append(_provision_entry("15", applicable="APPLICABLE" if is_mse else "CONDITIONAL",
                                    why=f"Assessment on {payment.get('as_of')}: payment {payment.get('days_late')} days past the applicable period.",
                                    icon="❌" if is_mse else "⚠"))
        out.append(_provision_entry("16", applicable="APPLICABLE" if is_mse else "CONDITIONAL", why="Statutory interest follows §15.", icon="ℹ"))
        out.append(_provision_entry("17", applicable="CONDITIONAL", why="Recovery arises if the claim remains unpaid.", icon="ℹ"))
        out.append(_provision_entry("18", applicable="CONDITIONAL", why="MSEFC reference is the enforcement route for unpaid MSME dues.", icon="⚠"))
    else:
        out.append(_provision_entry("15", applicable="CONDITIONAL", why="Relevant when you supply as a Micro/Small enterprise and a payment runs late — run Payment Protection for a date-based assessment.", icon="ℹ"))
        out.append(_provision_entry("18", applicable="CONDITIONAL", why="The MSEFC route exists if an eligible payment stays unpaid.", icon="ℹ"))
    # §20/§21 informational MSEFC context
    out.append(_provision_entry("20", applicable="INFORMATIONAL", why="Council infrastructure context for §18.", icon="ℹ"))
    out.append(_provision_entry("21", applicable="INFORMATIONAL", why="Council composition context for §18.", icon="ℹ"))
    # §22/§23 buyer-side — conditional on buying from MSME suppliers (needs confirmation)
    buys_from_msme = getattr(profile, "buys_from_msme_suppliers", None)
    if buys_from_msme is True:
        out.append(_provision_entry("22", applicable="APPLICABLE", why="Profile confirms procurement from Micro/Small suppliers — annual-account disclosure applies.", icon="⚠"))
        out.append(_provision_entry("23", applicable="CONDITIONAL", why="Relevant if §15/§16 interest becomes payable.", icon="ℹ"))
    elif buys_from_msme is False:
        out.append(_provision_entry("22", applicable="NOT_APPLICABLE", why="Profile records no procurement from MSME suppliers.", icon="ℹ"))
    else:
        out.append(_provision_entry("22", applicable="CONDITIONAL", why="Confirm whether you procure from Micro/Small suppliers.", icon="⚠"))
        out.append(_provision_entry("23", applicable="CONDITIONAL", why="Relevant only in the buyer scenario.", icon="ℹ"))
    # §24, §27
    out.append(_provision_entry("24", applicable="INFORMATIONAL", why="Awareness: inconsistent contract terms may not override the Act.", icon="ℹ"))
    out.append(_provision_entry("27", applicable="CONDITIONAL", why="Penalties arise on contravention of registration obligations.", icon="ℹ"))
    return out


# ----------------------------------------------------- alerts (§5)

def compliance_alerts(db: Session, project: models.Project) -> list[dict[str, Any]]:
    profile = project.profile
    if profile is None:
        return []
    alerts: list[dict[str, Any]] = []
    classification = _classification_result(profile)
    cls = classification.get("potential_class")
    is_mse = cls in ("MICRO", "SMALL")

    if classification["missing_inputs"]:
        alerts.append({
            "alert": "MSME classification cannot be determined",
            "severity": "WARNING", "icon": "⚠", "section": "7",
            "why": "Required inputs are missing: " + "; ".join(classification["missing_inputs"]),
            "evidence": "Project profile fields",
            "recommended_action": "Enter machinery investment and annual turnover in the profile, then re-open MSME Intelligence.",
            "official_source": M.SOURCE_MSME, "label": "AI INFERENCE — from profile data",
        })
    elif is_mse and not profile.udyam_number:
        alerts.append({
            "alert": "MSME registration (Udyam) may be required",
            "severity": "INFO", "icon": "❌", "section": "8",
            "why": f"Profile data classifies the enterprise as {cls}, but no Udyam registration number is recorded.",
            "evidence": f"machinery_investment ₹{_cr(profile.machinery_investment)} Cr · annual_turnover ₹{_cr(profile.annual_turnover)} Cr",
            "recommended_action": "Register free on the official Udyam portal and record the number (registration unlocks delayed-payment protection and benefits).",
            "official_source": M.SOURCE_UDYAM, "label": "AI INFERENCE — verify registration status yourself",
        })
    if cls:
        alerts.append({
            "alert": f"Potential MSME category: {cls}" if is_mse or cls == "MEDIUM" else "Enterprise exceeds MSME limits",
            "severity": "INFO", "icon": "ℹ", "section": "7",
            "why": f"Versioned §7 criteria ({classification['law_version']}) applied to your profile inputs.",
            "evidence": str(classification["inputs_used"]),
            "recommended_action": "Confirm against your Udyam certificate / verify the current notification on the official portal.",
            "official_source": M.SOURCE_MSME, "label": "REGULATORY DOCUMENT — versioned criteria",
        })
    if is_mse:
        alerts.append({
            "alert": "Government support & procurement preference may be available",
            "severity": "INFO", "icon": "ℹ", "section": "9, 10, 11",
            "why": "Micro/Small classification opens MSME-oriented support, credit policies and (for government suppliers) procurement preference.",
            "evidence": f"classification {cls}",
            "recommended_action": "Review the Schemes module (criteria-based) and keep Udyam + empanelment current if you supply to government buyers.",
            "official_source": M.SOURCE_MSME, "label": "INFORMATIONAL",
        })
    buys = getattr(profile, "buys_from_msme_suppliers", None)
    if buys is None:
        alerts.append({
            "alert": "Confirm supplier relationships for §22 disclosure",
            "severity": "INFO", "icon": "⚠", "section": "22",
            "why": "The Act requires buyers to disclose unpaid MSME dues in annual accounts; NIECP-AI does not know if you buy from MSME suppliers.",
            "evidence": "Profile flag not set",
            "recommended_action": "Answer the buyer-side question in MSME Intelligence → Settings.",
            "official_source": M.SOURCE_INDIA_CODE, "label": "AI INFERENCE",
        })
    elif buys is True:
        alerts.append({
            "alert": "Annual-account disclosure for MSME dues",
            "severity": "WARNING", "icon": "⚠", "section": "22",
            "why": "You procure from Micro/Small suppliers — unpaid principal+interest beyond the appointed day must be disclosed in annual accounts.",
            "evidence": "buys_from_msme_suppliers = true (user-confirmed)",
            "recommended_action": "With your accountant, verify the §22 disclosure in your annual accounts.",
            "official_source": M.SOURCE_INDIA_CODE, "label": "REGULATORY DOCUMENT",
        })
    return alerts


# ------------------------------------------- payment protection (§6)

def payment_assessment(*, invoice_date: str, supply_date: str | None, amount: float,
                       payment_terms_days: int | None, payment_date: str | None,
                       supplier_class: str, as_of: str | None = None) -> dict[str, Any]:
    """Informational date math per §§15-16. NOT legal advice."""
    try:
        inv = date.fromisoformat(invoice_date)
    except ValueError:
        return {"ok": False, "message": "Invalid invoice date."}
    supply = None
    if supply_date:
        try:
            supply = date.fromisoformat(supply_date)
        except ValueError:
            return {"ok": False, "message": "Invalid supply date."}
    paid = None
    if payment_date:
        try:
            paid = date.fromisoformat(payment_date)
        except ValueError:
            return {"ok": False, "message": "Invalid payment date."}
    asof = date.fromisoformat(as_of) if as_of else date.today()

    # §15: agreed period applies; otherwise the default period (45 days — the
    # commonly-cited default; verify against the current text).
    DEFAULT_DAYS = 45
    terms = int(payment_terms_days) if payment_terms_days and int(payment_terms_days) > 0 else None
    basis_days = terms or DEFAULT_DAYS
    basis_note = (
        f"Agreed payment period of {terms} days (per §15, the agreed period applies)."
        if terms else
        f"No agreement recorded — the default period of {DEFAULT_DAYS} days is used (commonly cited under the Act; verify the current text)."
    )
    start = supply or inv
    due = start + timedelta(days=basis_days)
    reference = paid or asof
    days_late = (reference - due).days
    delayed = days_late > 0
    principal_remaining = 0.0 if paid else (amount if delayed else amount)

    # interest estimate: 3× RBI bank rate, compound with monthly rests —
    # computed as whole months compounded + pro-rata remainder, on a clearly
    # labelled placeholder rate (verify the prevailing RBI bank rate).
    rate = M.RBI_BANK_RATE_FALLBACK * 3
    days_late_pos = max(0, days_late)
    whole_months = days_late_pos // 30
    remainder_days = days_late_pos % 30
    growth = (1 + rate / 12) ** whole_months * (1 + rate * remainder_days / 365) if days_late_pos else 1.0
    interest = round(amount * (growth - 1), 2) if delayed else 0.0

    return {
        "ok": True,
        "assessment_type": "INFORMATIONAL REGULATORY ASSESSMENT — NOT LEGAL ADVICE",
        "supplier_class_declared": supplier_class,
        "msmed_relevant": supplier_class in ("MICRO", "SMALL"),
        "msmed_note": (
            "The delayed-payment provisions protect Micro & Small suppliers; the declared supplier class falls outside that scope — the MSEFC route may not be available."
            if supplier_class not in ("MICRO", "SMALL")
            else "The declared supplier class is within the Act's delayed-payment protection scope (subject to registration and the Act's conditions)."
        ),
        "inputs": {"invoice_date": inv.isoformat(), "supply_or_acceptance_date": (supply or inv).isoformat(),
                   "amount": amount, "payment_terms_days": terms, "payment_date": paid.isoformat() if paid else None,
                   "assessed_as_of": asof.isoformat()},
        "timeline": {"basis": basis_note, "period_days": basis_days,
                     "due_date": due.isoformat(), "payment_date": paid.isoformat() if paid else None,
                     "days_past_due": max(0, days_late)},
        "delayed_payment_flag": delayed,
        "flag_label": ("❌ DELAYED PAYMENT SITUATION INDICATED" if delayed else "ℹ No delay indicated as of the assessment date"),
        "applicable_sections": (["15", "16", "24"] + (["17", "18", "20", "21"] if delayed else [])),
        "interest_estimate": {
            "amount": interest,
            "formula": "≈ principal × (compound interest with monthly rests at 3 × RBI bank rate), as per §§15-16",
            "rate_note": M.RBI_BANK_RATE_NOTE,
            "status": "AI INFERENCE — indicative only; the exact computation follows the Act text and the prevailing RBI rate",
        },
        "amounts": {"principal": amount, "principal_remaining_claimable": principal_remaining,
                    "interest_indicative": interest, "total_indicative": round(amount + interest, 2) if delayed else None},
        "recommended_path": ([
            "1. Issue a written claim to the buyer citing §§15-16 (principal + statutory interest)",
            "2. If unpaid, file a reference with the MSE Facilitation Council (§18) for the buyer's State",
            "3. Track via the Samadhaan portal (official MSME delayed-payment monitoring)",
        ] if delayed and supplier_class in ("MICRO", "SMALL") else
            ["No statutory delayed-payment path indicated by the entered dates."]
            if not delayed else
            ["For non-Micro/Small suppliers, contractual remedies (not the MSMED chapter) generally apply — consult legal counsel."]),
        "official_routes": {"samadhaan": M.SOURCE_SAMADHAAN, "msefc_reference": "MSEFC of the State where the buyer is located (§18)",
                            "sources": {"act": M.SOURCE_INDIA_CODE, "msme": M.SOURCE_MSME}},
        "disclaimer": ("This computation is an informational regulatory assessment based on the dates and classifications you entered. "
                       "It is NOT legal advice and NOT a legal determination of liability. Interest math uses a placeholder bank rate — verify the current RBI rate and consult a professional."),
    }


# ------------------------------------------- digital twin additions (§4)

def digital_twin_msme_block(db: Session, project: models.Project) -> dict[str, Any]:
    profile = project.profile
    if profile is None:
        return {"status": "NO_PROFILE", "status_icon": "⚠", "sections": []}
    classification = _classification_result(profile)
    reg = _registration_check(db, project, profile, classification)
    entries: list[dict[str, Any]] = [
        {"item": "Enterprise type", "value": profile.organization_type.value if profile.organization_type else None, "icon": "ℹ", "label": "USER-PROVIDED INFORMATION"},
        {"item": "MSME status (potential)", "value": classification.get("potential_class") or "INFORMATION REQUIRED", "icon": classification.get("status_icon"), "label": "AI INFERENCE — versioned §7 criteria", "detail": classification["declaration"]},
        {"item": "Registration status", "value": reg["status"], "icon": reg["status_icon"], "label": reg["provenance"] or "AI INFERENCE", "detail": reg["note"]},
        {"item": "Investment (plant & machinery)", "value": _cr(profile.machinery_investment), "icon": "ℹ", "label": "USER-PROVIDED INFORMATION"},
        {"item": "Annual turnover", "value": _cr(profile.annual_turnover), "icon": "ℹ", "label": "USER-PROVIDED INFORMATION"},
        {"item": "Location", "value": f"{profile.district or '—'} / {profile.state_code or '—'}" + (f" · {profile.pincode}" if getattr(profile, 'pincode', None) else ""), "icon": "ℹ", "label": "USER-PROVIDED INFORMATION"},
        {"item": "Industry/activity", "value": profile.industry_code or profile.sub_industry or "—", "icon": "ℹ", "label": "USER-PROVIDED INFORMATION"},
    ]
    return {"status": classification.get("status"), "classification": classification, "registration": reg,
            "entries": entries, "law_warning": M.VERSION_WARNING}


# ----------------------------------------------- smart action guide (§12)

def smart_action_guide(db: Session, project: models.Project) -> list[dict[str, Any]]:
    profile = project.profile
    guide: list[dict[str, Any]] = []
    if profile is None:
        return [{"step": 1, "action": "Complete the master project profile", "why": "Every regulatory conclusion depends on your profile.", "link": "/projects/{pid}/profile"}]
    classification = _classification_result(profile)
    cls = classification.get("potential_class")
    step = 1
    def add(action, why, link, icon="→"):
        nonlocal step
        guide.append({"step": step, "action": action, "why": why, "link": link, "icon": icon})
        step += 1
    if classification["missing_inputs"]:
        add("Complete missing business information (investment in plant & machinery, annual turnover)",
            "MSMED §7 classification and most MSME benefits depend on these figures.",
            "/projects/{pid}/profile")
    if cls is None:
        return guide
    add("Check MSME classification", f"Profile indicates {cls} under the versioned §7 criteria — confirm against official records.", f"/projects/{{pid}}/msme", icon="§7")
    if cls in ("MICRO", "SMALL") and not profile.udyam_number:
        add("Confirm UDYAM status — register if not registered",
            "§8 memorandum (free, official Udyam portal) unlocks delayed-payment protection and MSME benefits.",
            "/projects/{pid}/msme", icon="§8")
    if (profile.state_code or "").upper() == "MH":
        add("Review applicable Maharashtra MAITRI services",
            "State single-window facilitation and incentives (OFFICIAL PORTAL route — no automated submission).",
            f"/projects/{{pid}}/msme", icon="MH")
    add("Prepare required documents", "Approval-wise document checklists are in your Documents module.", f"/projects/{{pid}}/documents", icon="📄")
    add("Complete prerequisite approvals", "Blocked approvals and dependencies are on the approval map.", f"/projects/{{pid}}/approvals", icon="🔗")
    add("Apply through the official government channel",
        "NIECP-AI prepares and routes you to the official portal — it never submits on your behalf.",
        f"/projects/{{pid}}/applications", icon="🚀")
    add("Track application status", "Record portal statuses (self-reported) so reminders keep working.", f"/projects/{{pid}}/applications", icon="📮")
    add("Monitor ongoing compliance", "Compliance calendar, renewals and MSME alerts stay current from your data.", f"/projects/{{pid}}/compliance", icon="✅")
    return guide


# ------------------------------------------- regulatory profile (§11)

def regulatory_profile(db: Session, project: models.Project) -> dict[str, Any]:
    profile = project.profile
    classification = _classification_result(profile) if profile else {"potential_class": None, "status": "NO_PROFILE", "missing_inputs": ["profile"]}
    approval_rows = db.scalars(select(models.ProjectApproval).where(models.ProjectApproval.project_id == project.id)).all()
    from ..enums import Applicability
    applicable = [a for a in approval_rows if a.applicability in (Applicability.APPLIES, Applicability.LIKELY, Applicability.CONDITIONAL)]
    alerts = compliance_alerts(db, project)
    maitri = M.maitri_for_state(profile.state_code if profile else None)
    return {
        "business_classification": classification,
        "msme_status": digital_twin_msme_block(db, project),
        "applicable_msme_provisions": applicable_provisions(db, project, profile) if profile else [],
        "maharashtra_approvals": {"relevant": bool(maitri), "services": maitri, "mode": "OFFICIAL_REDIRECT — official portal only, no automated submission"},
        "sector_specific_approvals": {"count": len(applicable), "see": "/projects/{pid}/approvals",
                                      "note": "Deterministic approval map — external data never makes legal conclusions."},
        "environmental_requirements": {"see": "/projects/{pid}/approvals",
                                       "note": "Environmental consents are part of the deterministic analysis (CPCB/SPCB adapters pending authorization)."},
        "required_documents": {"see": "/projects/{pid}/documents", "msme_documents": ["Udyam registration certificate", "Invoices/supply proof (delayed-payment cases)"]},
        "approval_dependencies": {"see": "/projects/{pid}/approvals", "note": "Dependency graph shows an approval only when profile conditions satisfy applicability."},
        "compliance_risks": alerts,
        "smart_action_guide": smart_action_guide(db, project),
        "trust_labels": ["OFFICIAL SOURCE", "DATASET", "REGULATORY DOCUMENT", "USER-PROVIDED INFORMATION", "AI INFERENCE", "PENDING VERIFICATION"],
        "disclaimer": "Regulatory intelligence from authored digests of the MSMED Act, 2006 with versioned classification criteria — verify every conclusion against the official sources. Not legal advice.",
    }
