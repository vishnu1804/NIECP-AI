"""Government data services (integration upgrade §3–§8, §11, §20, §21).

Every external call goes: endpoint → gov_manager.dispatch → provider adapter.
Credentials stay in server-side settings; payloads carry statuses and results
only. Dataset matches are USER-SELECTED, stored with provenance and used as
inputs to the regulatory digital twin — never as legal conclusions.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..enums import Applicability
from ..services import gov_manager
from ..services import next_action as next_action_service
from ..services import readiness as readiness_service
from ..services.audit import audit_event
from ..services.auth_service import get_current_user, project_access

router = APIRouter(tags=["gov-data"])


# ═══════════════════════════════════════════ service cards (§21) ══
@router.get("/gov/services")
def gov_services(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    cards = gov_manager.service_cards(db)
    active = sum(1 for c in cards if c["authorization_status"] == "AUTHORIZED")
    pending = sum(1 for c in cards if c["authorization_status"] in ("PENDING", "PENDING_AUTHORIZATION"))
    demo = sum(1 for c in cards if c["environment"] == "DEMO")
    return {
        "services": cards,
        "summary": {"active": active, "pending": pending, "demo": demo, "total": len(cards),
                    "declaration": "No government API is connected in this deployment until a real successful authenticated response is received. Dataset services are labelled as dataset matches, not verifications."},
    }


class TestRequest(BaseModel):
    probe: dict[str, str] | None = None  # e.g. {"pincode": "600001"} for the pincode probe


@router.post("/gov/services/{code}/test")
def gov_service_test(code: str, body: TestRequest | None = None, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """Test connection — performs a real, minimal call where the adapter is
    provisioned; otherwise returns the honest PENDING/diiabled state."""
    probe = (body.probe if body else None) or {}
    if code == "pincode":
        return gov_manager.dispatch(db, adapter_code="pincode", operation="lookup", user=user, pincode=probe.get("pincode") or "600001")
    if code == "udyam_dataset":
        return gov_manager.dispatch(db, adapter_code="udyam_dataset", operation="search", user=user, query=probe.get("query") or "demo", state_code=None)
    if code == "mca":
        return gov_manager.dispatch(db, adapter_code="mca", operation="search", user=user, query=probe.get("query") or "demo")
    if code == "digilocker":
        return gov_manager.dispatch(db, adapter_code="digilocker", operation="authorize_url", user=user, state="test")
    # adapters without a runtime operation: report their static honest state
    card = next((c for c in gov_manager.service_cards(db) if c["code"] == code), None)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown government service.")
    return {"ok": False, "provider": card["provider"], "service": card["service"], "mode": card["mode_label"],
            "authorization_status": card["authorization_status"],
            "message": card["notice"] or "No programmatic API is authorized for this service. Continue through the official portal.",
            "fallback": {"mode": card["fallback_mode"], "official_portal_url": card["official_portal_url"]}}


# ═══════════════════════════════════════ pincode / location (§5) ══
class PincodeLookup(BaseModel):
    pincode: str
    project_id: int | None = None
    apply_to_profile: bool = False


@router.post("/gov/pincode-lookup")
def pincode_lookup(body: PincodeLookup, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, body.project_id) if body.project_id else None
    result = gov_manager.dispatch(db, adapter_code="pincode", operation="lookup", user=user, project=project, pincode=body.pincode)
    if result["ok"] and body.apply_to_profile and project is not None:
        data = result["data"]
        state_code = data.get("state_code")
        precise = result.get("verification_status") == "GOVERNMENT_DATASET_MATCH"
        applied: dict[str, Any] = {"pincode": body.pincode, "state_applied": bool(state_code), "precise": precise}
        project.profile.pincode = body.pincode
        if state_code and not data.get("state_requires_confirmation"):
            project.profile.state_code = state_code
            applied["state_code"] = state_code
        db.commit()
        audit_event(db, action="PROFILE_ENRICHED_PINCODE", action_category="DIGITAL_TWIN", user_id=user.id,
                    project_id=project.id, resource_type="project_profile", resource_id=str(project.profile.id if project.profile else None),
                    after=applied, details={"source": result["provider"], "correlation_id": result["correlation_id"]}, commit=True)
        result["applied_to_profile"] = applied
        result["analysis_note"] = "Location factors changed — re-run the analysis to refresh the regulatory digital twin."
    return result


# ═════════════════════════════════ UDYAM dataset search (§3) ══
class DatasetSearch(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    state_code: str | None = None
    project_id: int | None = None


@router.post("/gov/udyaam/search")
def udyaam_search(body: DatasetSearch, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, body.project_id) if body.project_id else None
    return gov_manager.dispatch(db, adapter_code="udyam_dataset", operation="search", user=user, project=project,
                                query=body.query, state_code=body.state_code)


class DatasetSelect(BaseModel):
    project_id: int
    record: dict[str, Any]
    apply_state: bool = True
    apply_district: bool = True
    apply_activity_hint: bool = True
    confirmation: bool = Field(description="User confirms this is their organization's record (or that they intend to reference it).")


@router.post("/gov/udyaam/select")
def udyaam_select(body: DatasetSelect, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """§3 steps 3–6: user selects the matching enterprise, NIECP stores the
    government-data reference, uses activity info as digital-twin input and
    asks for a regulatory re-analysis. Nothing is auto-applied without the
    explicit confirmation flag."""
    project = project_access(db, user, body.project_id)
    if not body.confirmation:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Please confirm this record belongs to your organization before NIECP-AI uses it to enrich the project.")
    record = body.record
    name = record.get("enterprise_name") or record.get("name") or "Selected dataset record"
    external_id = record.get("udyam_reference") or record.get("udyam") or record.get("id") or ""
    ref = models.GovDataReference(
        project_id=project.id, organization_id=project.organization_id,
        provider="Ministry of Micro, Small and Medium Enterprises (via data.gov.in)",
        service="UDYAM/MSME registration dataset match",
        external_id=str(external_id)[:160] or None, display_name=str(name)[:300],
        verification_status="GOVERNMENT_DATASET_MATCH",
        match_payload=record, integration_mode=record.get("_mode", "MANUAL"),
        selected_by=user.id, matched_at=gov_manager.utcnow(),
        is_demo=bool(record.get("is_demo")),
        notes="Dataset match selected by the user — NOT a verification of the registration.",
    )
    db.add(ref)
    db.flush()
    # digital-twin enrichment (only what the user allows)
    applied: dict[str, Any] = {}
    profile = project.profile
    if profile is not None:
        if body.apply_state and record.get("state"):
            state_name = str(record["state"]).lower()
            from ..knowledge.data.states import STATES
            match = next((s for s in STATES if s["name"].lower() == state_name or s["name"].lower() in state_name), None)
            if match:
                profile.state_code = match["code"]
                applied["state_code"] = match["code"]
        if body.apply_district and record.get("district"):
            profile.district = str(record["district"])[:120]
            applied["district"] = profile.district
        if body.apply_activity_hint and record.get("nic_activity"):
            hint = str(record["nic_activity"])[:400]
            profile.sub_industry = hint if not profile.sub_industry else profile.sub_industry
            applied["activity_hint"] = hint
    ref.enrichment = applied
    audit_event(db, action="GOV_DATASET_MATCH_SELECTED", action_category="DIGITAL_TWIN", user_id=user.id,
                project_id=project.id, resource_type="gov_data_reference", resource_id=str(ref.id),
                after={"external_id": ref.external_id, "verification_status": ref.verification_status, "applied": applied},
                integration_mode=ref.integration_mode, provider=ref.provider, commit=True)
    db.commit()
    return {
        "ok": True,
        "reference": {
            "id": ref.id, "provider": ref.provider, "service": ref.service, "external_id": ref.external_id,
            "display_name": ref.display_name, "verification_status": ref.verification_status,
            "verification_label": "GOVERNMENT_DATASET_MATCH — dataset entry selected by you. NOT a real-time verification of the registration.",
            "integration_mode": ref.integration_mode, "is_demo": ref.is_demo, "applied": applied,
        },
        "analysis_note": "Re-run the AI analysis so the regulatory digital twin picks up the enriched profile.",
        "disclaimer": "This is government DATASET information used as supporting input — NIECP-AI does not verify registrations in real time.",
    }


# ═══════════════════════════════════════ MCA company data (§4) ══
@router.post("/gov/mca/search")
def mca_search(body: DatasetSearch, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, body.project_id) if body.project_id else None
    return gov_manager.dispatch(db, adapter_code="mca", operation="search", user=user, project=project, query=body.query)


# ═══════════════════════════════════════ DigiLocker + consent (§6, §7) ══
@router.get("/gov/digilocker/status")
def digilocker_status(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    return gov_manager.dispatch(db, adapter_code="digilocker", operation="authorize_url", user=user, state="status")


class ConsentCreate(BaseModel):
    project_id: int | None = None
    provider: str = Field(min_length=2, max_length=64)
    service: str = Field(min_length=2, max_length=240)
    purpose: str = Field(min_length=4, max_length=2000)
    data_categories: list[str] = []
    documents_requested: list[str] = []
    integration_mode: str = "PENDING_AUTHORIZATION"
    accepted: bool


@router.post("/gov/consent", status_code=status.HTTP_201_CREATED)
def create_consent(body: ConsentCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, body.project_id) if body.project_id else None
    return gov_manager.create_consent(db, user=user, project=project, provider=body.provider, service=body.service,
                                      purpose=body.purpose, data_categories=body.data_categories,
                                      documents_requested=body.documents_requested,
                                      integration_mode=body.integration_mode, accepted=body.accepted)


@router.get("/gov/consent")
def list_consents(project_id: int | None = None, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    stmt = select(models.ConsentRecord).where(models.ConsentRecord.user_id == user.id).order_by(models.ConsentRecord.created_at.desc())
    if project_id:
        project = project_access(db, user, project_id)
        stmt = stmt.where(models.ConsentRecord.project_id == project.id)
    rows = db.scalars(stmt.limit(50)).all()
    return {"consents": [gov_manager.consent_payload(c) for c in rows]}


@router.post("/gov/consent/{consent_id}/revoke")
def revoke_consent(consent_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    return gov_manager.revoke_consent(db, user, consent_id)


class DocumentRequest(BaseModel):
    project_id: int
    consent_id: int
    document_type: str = Field(min_length=2, max_length=240)


@router.post("/gov/digilocker/request-document")
def digilocker_request_document(body: DocumentRequest, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """The retrieval step. Honest by construction: requires a GRANTED consent
    row AND provisioned credentials; otherwise PENDING_AUTHORIZATION with the
    official redirect — never a fake document."""
    project = project_access(db, user, body.project_id)
    consent = db.get(models.ConsentRecord, body.consent_id)
    if consent is None or consent.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Consent record not found.")
    if consent.status and getattr(consent.status, "value", str(consent.status)) != "GRANTED":
        raise HTTPException(status.HTTP_409_CONFLICT, "That consent is not active (revoked/denied/expired). Record fresh consent first.")
    # even with consent: the provider integration must be authorized
    result = gov_manager.dispatch(db, adapter_code="digilocker", operation="authorize_url", user=user, project=project, state=f"consent:{consent.id}")
    db.commit()
    result["consent_id"] = consent.id
    result["document_type"] = body.document_type
    if not result["ok"]:
        result["message"] = result.get("message") or "DigiLocker integration is awaiting official partner authorization."
        result["fallback"] = {
            "mode": "OFFICIAL_REDIRECT",
            "official_portal_url": "https://www.digilocker.gov.in/",
            "manual_steps": [
                "Open DigiLocker and download the issued document",
                "Upload it under Documents — the AI pipeline classifies it and checks it against your approvals",
                "NIECP-AI marks it USER_UPLOADED — a DigiLocker-retrieved copy can be attached once the requester integration is authorized",
            ],
        }
    return result


# ═══════════════════════════════ project gov references ══
@router.get("/projects/{project_id}/gov-references")
def project_gov_references(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    rows = db.scalars(select(models.GovDataReference).where(models.GovDataReference.project_id == project.id).order_by(models.GovDataReference.created_at.desc())).all()
    return {"references": [
        {"id": r.id, "provider": r.provider, "service": r.service, "external_id": r.external_id,
         "display_name": r.display_name, "verification_status": r.verification_status,
         "integration_mode": r.integration_mode, "is_demo": r.is_demo,
         "applied": r.enrichment or {}, "matched_at": r.matched_at.isoformat() if r.matched_at else None,
         "notes": r.notes}
        for r in rows
    ]}


# ═══════════════════════════════════ command center (§20) ══
@router.get("/projects/{project_id}/command-center")
def command_center(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    rd = readiness_service.compute_readiness(db, project, persist=False)
    docs = readiness_service.documents_readiness(db, project)
    approvals = db.scalars(select(models.ProjectApproval).where(models.ProjectApproval.project_id == project.id)).all()
    applicable = [a for a in approvals if a.applicability in (Applicability.APPLIES, Applicability.LIKELY, Applicability.CONDITIONAL)]
    blockers = [a for a in applicable if a.node_state == "BLOCKED"]
    apps = db.scalars(select(models.Application).where(models.Application.project_id == project.id)).all()
    cards = gov_manager.service_cards(db)
    active = sum(1 for c in cards if c["authorization_status"] == "AUTHORIZED")
    pending = sum(1 for c in cards if c["authorization_status"] in ("PENDING", "PENDING_AUTHORIZATION"))
    demo_count = sum(1 for c in cards if c["environment"] == "DEMO")
    actions = next_action_service.next_best_actions(db, project, limit=3)
    return {
        "readiness": {"overall": rd["overall"], "disclaimer": rd["disclaimer"]},
        "approvals_identified": len(applicable),
        "documents_ready": f"{docs.get('satisfied_count', 0)}/{docs.get('required_count', 0)}",
        "critical_blockers": len(blockers),
        "blocker_titles": [b.name for b in blockers[:3]],
        "integrations": {"active": active, "pending": pending, "demo": demo_count,
                         "note": "'Active' counts only provider-authorized integrations — none are connected in this deployment."},
        "applications": {"total": len(apps),
                         "open": sum(1 for a in apps if a.status and a.status.value not in ("APPROVED", "REJECTED", "WITHDRAWN", "CANCELLED")),
                         "approved": sum(1 for a in apps if a.status and a.status.value == "APPROVED")},
        "next_best_actions": actions,
        "label": "COMMAND CENTER",
    }

# ══════════════════════ GOVERNMENT DATA STATUS (§10/§11/§28) ══
@router.get("/gov/data-status")
def gov_data_status(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """Honest, per-dataset configuration status — booleans only, never values."""
    from ..config import settings as S

    def ds(name: str, resource_id: str) -> dict[str, Any]:
        configured = bool(S.data_gov_api_key and resource_id)
        return {
            "dataset": name,
            "resource_id_configured": bool(resource_id),
            "api_key_configured": bool(S.data_gov_api_key),
            "connection_state": ("CONFIGURED" if (configured and S.enable_outbound_gov_calls)
                                 else "CONFIGURED_BUT_OUTBOUND_DISABLED" if configured
                                 else "PENDING_AUTHORIZATION"),
        }

    return {
        "outbound_calls_enabled": S.enable_outbound_gov_calls,
        "cache_ttl_seconds": S.data_gov_cache_ttl_seconds,
        "cache_scope": "PUBLIC dataset responses only (pincode/UDYAM/MCA/CPCB) — never credentials or private payloads",
        "datasets": [
            ds("UDYAM/MSME registration dataset", S.data_gov_udyaam_resource_id),
            ds("India Post pincode dataset", S.data_gov_pincode_resource_id),
            ds("MCA Company Master Data (public)", S.data_gov_mca_resource_id),
            ds("CPCB real-time air quality", S.data_gov_cpcb_air_resource_id),
            ds("CPCB surface water quality (historical)", S.data_gov_surface_water_resource_id),
            ds("Annual Survey of Industries", S.data_gov_asi_resource_id),
        ],
        "note": "States are honest about configuration only — a CONFIGURED dataset is not CONNECTED until a real authorized call has succeeded.",
    }


# ══════════════════════ ENVIRONMENTAL / INDUSTRIAL CONTEXT (§5, §6, §7, §20) ══
class ContextLookup(BaseModel):
    project_id: int | None = None
    city: str | None = Field(default=None, max_length=120)
    state_code: str | None = Field(default=None, max_length=8)
    location: str | None = Field(default=None, max_length=160)
    industry: str | None = Field(default=None, max_length=160)
    limit: int = Field(default=25, ge=1, le=100)
    save_to_project: bool = False  # explicit user action — stores a provenance-labelled reference


def _save_context_reference(db: Session, user: models.User, project: models.Project | None, payload: dict[str, Any], *, provider: str, service: str, display_name: str, external_id: str | None) -> None:
    """Store an environmental/industrial CONTEXT result as a GovDataReference
    (explicit user action). Provenance travels in match_payload/enrichment."""
    from datetime import datetime
    meta = payload.get("meta") or {}
    db.add(models.GovDataReference(
        project_id=project.id, organization_id=project.organization_id,
        provider=provider[:64], service=service[:240], external_id=(external_id or "")[:160] or None,
        display_name=display_name[:300],
        verification_status=payload.get("verification_status") or "NOT_VERIFIED",
        match_payload={"records": (payload.get("data") or {}).get("records", [])[:10], "meta": meta},
        enrichment={"context_label": meta.get("context_label"), "note": meta.get("note")},
        integration_mode=payload.get("mode") or "NOT_AVAILABLE",
        selected_by=user.id, matched_at=datetime.utcnow(), is_demo=False,
        notes="Saved from an explicit user context lookup — CONTEXT data, never an approval determination.",
    ))
    db.commit()


def _context_response(payload: dict[str, Any], *, context_label: str) -> dict[str, Any]:
    payload["context_label"] = context_label
    payload["usage_rule"] = (
        "This is CONTEXT data. It is combined with project facts, industry, capacity, waste/chemicals and location, "
        "and evaluated by the deterministic rule engine — the data itself never creates or removes an approval requirement."
    )
    return payload


@router.post("/gov/cpcb/air-quality")
def cpcb_air_quality(body: ContextLookup, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """Real-time air quality — ENVIRONMENTAL CONTEXT / REGULATORY FACTOR only."""
    project = project_access(db, user, body.project_id) if body.project_id else None
    state = body.state_code or (project.profile.state_code if project and project.profile else None)
    payload = gov_manager.dispatch(db, adapter_code="cpcb", operation="air_quality_context", user=user, project=project,
                                   city=body.city, state=state, limit=body.limit)
    payload = _context_response(payload, context_label="ENVIRONMENTAL_CONTEXT")
    if payload.get("ok") and body.save_to_project and project is not None:
        _save_context_reference(db, user, project, payload, provider="Central Pollution Control Board",
                                service="Real-time air quality (data.gov.in) — ENVIRONMENTAL CONTEXT",
                                display_name=f"Air quality — {body.city or state or 'area'}",
                                external_id=(payload.get("meta") or {}).get("resource_id"))
    return payload


@router.post("/gov/cpcb/surface-water")
def cpcb_surface_water(body: ContextLookup, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """Surface water quality — HISTORICAL / SUPPORTING DATA only."""
    project = project_access(db, user, body.project_id) if body.project_id else None
    state = body.state_code or (project.profile.state_code if project and project.profile else None)
    payload = gov_manager.dispatch(db, adapter_code="cpcb_surface_water", operation="water_quality_context", user=user, project=project,
                                   state=state, location=body.location, limit=body.limit)
    payload = _context_response(payload, context_label="HISTORICAL_SUPPORTING_DATA")
    if payload.get("ok") and body.save_to_project and project is not None:
        _save_context_reference(db, user, project, payload, provider="CPCB (via data.gov.in)",
                                service="Surface water quality — HISTORICAL / SUPPORTING observations",
                                display_name=f"Surface water — {body.location or state or 'area'}",
                                external_id=(payload.get("meta") or {}).get("resource_id"))
    return payload


@router.post("/gov/asi/industry-stats")
def asi_industry_stats(body: ContextLookup, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """Annual Survey of Industries — INDUSTRIAL STATISTICAL DATA for context."""
    project = project_access(db, user, body.project_id) if body.project_id else None
    state = body.state_code or (project.profile.state_code if project and project.profile else None)
    industry = body.industry or (project.profile.industry_code if project and project.profile else None)
    payload = gov_manager.dispatch(db, adapter_code="asi_industrial", operation="industry_statistics_context", user=user, project=project,
                                   industry=industry, state=state, limit=body.limit)
    payload = _context_response(payload, context_label="INDUSTRIAL_STATISTICAL_DATA")
    if payload.get("ok") and body.save_to_project and project is not None:
        _save_context_reference(db, user, project, payload, provider="MoSPI (via data.gov.in)",
                                service="Annual Survey of Industries — INDUSTRIAL STATISTICAL DATA",
                                display_name=f"Industry statistics — {industry or state or 'sector'}",
                                external_id=(payload.get("meta") or {}).get("resource_id"))
    return payload


# ══════════════════════ STATE ROUTING (§31) ══
@router.get("/gov/state-integration")
def state_integration(state_code: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """Dynamic national-vs-state routing: MH → MAITRI (primary), TN → TN single window."""
    from ..services.gov_providers import primary_state_integration
    primary = primary_state_integration(state_code)
    return {
        "state_code": (state_code or "").upper(),
        "primary_state_integration": primary,
        "national_layer": {"nsws": "OFFICIAL_REDIRECT", "apisetu_digilocker": "PENDING_AUTHORIZATION"},
        "note": "National integrations stay available for every state; the state layer is selected dynamically from the project state.",
    }


# ══════════════════════ REGULATORY DIGITAL TWIN ENRICHMENT (§13/§14) ══
@router.get("/projects/{project_id}/gov/enrichment")
def project_gov_enrichment(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """Combined digital-twin blocks (BUSINESS / COMPANY / MSME / LOCATION /
    ENVIRONMENT / INDUSTRY / APPROVALS / DOCUMENTS / COMPLIANCE) with per-item
    provenance. Every value shows where it came from and its verification state."""
    from ..services.msme_engine import _classification_result

    project = project_access(db, user, project_id)
    profile = project.profile
    refs = db.scalars(select(models.GovDataReference).where(models.GovDataReference.project_id == project.id).order_by(models.GovDataReference.matched_at.desc())).all()

    def item(value: Any, *, source: str, source_type: str, verification: str, updated: Any = None, label: str | None = None) -> dict[str, Any]:
        return {"label": label, "value": value, "source": source, "source_type": source_type,
                "last_updated": updated.isoformat() if hasattr(updated, "isoformat") and updated else updated,
                "verification_state": verification}

    def ref_items(provider_contains: str) -> list[models.GovDataReference]:
        return [r for r in refs if provider_contains.lower() in (r.provider or "").lower()]

    blocks: dict[str, list[dict[str, Any]]] = {"BUSINESS": [], "COMPANY": [], "MSME": [], "LOCATION": [], "ENVIRONMENT": [], "INDUSTRY": [], "APPROVALS": [], "DOCUMENTS": [], "COMPLIANCE": []}

    if profile is not None:
        blocks["BUSINESS"] = [
            item(profile.organization_type, source="Project profile", source_type="USER_PROVIDED", verification="USER_PROVIDED", label="Organization type"),
            item(profile.pan, source="Project profile", source_type="USER_PROVIDED", verification="USER_PROVIDED", label="PAN"),
            item(profile.gstin, source="Project profile", source_type="USER_PROVIDED", verification="USER_PROVIDED", label="GSTIN"),
        ]
        cls = _classification_result(profile)
        blocks["MSME"] = [
            item(cls.get("potential_class") or "INFORMATION REQUIRED", source="MSMED rule engine (versioned §7 criteria)", source_type="AI_INTERPRETATION", verification="REQUIRES_VERIFICATION", label="Potential MSME class"),
            item(profile.udyam_number, source="Project profile", source_type="USER_PROVIDED", verification="USER_PROVIDED", label="Udyam number (declared)"),
        ]
        blocks["LOCATION"] = [
            item(profile.pincode, source="Project profile", source_type="USER_PROVIDED", verification="USER_PROVIDED", label="PIN code"),
            item(profile.state_code, source="Project profile", source_type="USER_PROVIDED", verification="USER_PROVIDED", label="State"),
            item(profile.district, source="Project profile", source_type="USER_PROVIDED", verification="USER_PROVIDED", label="District"),
        ]
        blocks["INDUSTRY"].append(item(profile.industry_code, source="Project profile", source_type="USER_PROVIDED", verification="USER_PROVIDED", label="Industry (NIC)"))

    udyam_refs = ref_items("Micro, Small") + [r for r in refs if "UDYAM" in (r.service or "").upper() or "udyam" in (r.provider or "").lower()]
    for r in udyam_refs[:3]:
        blocks["BUSINESS"].append(item(r.display_name, source=f"{r.provider} — {r.service}", source_type="DATASET",
                                       verification=r.verification_status, updated=r.matched_at, label="Enterprise (dataset match)"))
        if (r.match_payload or {}).get("nic_activity"):
            blocks["BUSINESS"].append(item(r.match_payload["nic_activity"], source=f"{r.provider}", source_type="DATASET",
                                           verification=r.verification_status, updated=r.matched_at, label="NIC activity"))
    for r in [x for x in refs if "MCA" in (x.service or "").upper() or "mca" in (x.provider or "").lower()][:3]:
        p = r.match_payload or {}
        blocks["COMPANY"] += [
            item(r.display_name, source=f"{r.provider} — {r.service}", source_type="DATASET", verification=r.verification_status, updated=r.matched_at, label="Company (dataset match)"),
            item(p.get("company_status") or p.get("cin"), source=r.provider, source_type="DATASET", verification=r.verification_status, updated=r.matched_at, label="Company status / CIN"),
        ]
    for r in [x for x in refs if (x.enrichment or {}).get("context_label") in ("ENVIRONMENTAL_CONTEXT", "HISTORICAL_SUPPORTING_DATA")][:6]:
        blocks["ENVIRONMENT"].append(item(r.display_name, source=f"{r.provider} — {r.service}", source_type="DATASET",
                                          verification=r.verification_status, updated=r.matched_at,
                                          label=(r.enrichment or {}).get("context_label")))
    for r in [x for x in refs if (x.enrichment or {}).get("context_label") == "INDUSTRIAL_STATISTICAL_DATA"][:4]:
        blocks["INDUSTRY"].append(item(r.display_name, source=f"{r.provider} — {r.service}", source_type="DATASET",
                                       verification=r.verification_status, updated=r.matched_at, label="Industry statistics"))
    for pin_ref in [x for x in refs if "India Post" in (x.provider or "")][:3]:
        blocks["LOCATION"].append(item(pin_ref.display_name, source=f"{pin_ref.provider} — {pin_ref.service}", source_type="DATASET",
                                       verification=pin_ref.verification_status, updated=pin_ref.matched_at, label="Location (dataset lookup)"))

    approvals = db.scalars(select(models.ProjectApproval).where(models.ProjectApproval.project_id == project.id)).all()
    from ..enums import Applicability
    active = [a for a in approvals if a.applicability in (Applicability.APPLIES, Applicability.CONDITIONAL) and not a.user_dismissed]
    blocks["APPROVALS"] = [
        {"label": "Identified approval", "value": f"{a.name} ({a.applicability.value})", "source": "Deterministic rule engine over project profile",
         "source_type": "AI_INTERPRETATION", "last_updated": None, "verification_state": a.source_status.value if a.source_status else "REQUIRES_VERIFICATION"}
        for a in active[:8]
    ]
    docs = db.scalars(select(models.Document).where(models.Document.project_id == project.id)).all()
    blocks["DOCUMENTS"] = [
        {"label": "Document", "value": d.title, "source": "User upload", "source_type": "USER_PROVIDED",
         "last_updated": d.created_at.isoformat() if getattr(d, "created_at", None) else None,
         "verification_state": (d.verification_status.value if getattr(d, "verification_status", None) else "USER_PROVIDED")}
        for d in docs[:8]
    ]
    blocks["COMPLIANCE"] = [
        {"label": "Compliance status", "value": "See Compliance module for tasks/renewals/queries", "source": "NIECP-AI modules",
         "source_type": "AI_INTERPRETATION", "last_updated": None, "verification_state": "REQUIRES_VERIFICATION"},
    ]

    # Project Twin core facts (MVP §C) — every fact with provenance
    from ..services.lifecycle import _twin_facts
    facts = _twin_facts(profile)
    blocks_out = {"PROJECT": facts, **blocks}
    ver_counts: dict[str, int] = {}
    for entries in blocks_out.values():
        for e in entries:
            ver_counts[e.get("verification_state") or "UNKNOWN"] = ver_counts.get(e.get("verification_state") or "UNKNOWN", 0) + 1
    return {
        "project_id": project.id,
        "twin": {
            "name": "Project Twin",
            "statement": "The central, provenance-labelled source of project facts. Other modules read these facts — they are never duplicated.",
            "verification_counts": ver_counts,
            "provenance_vocabulary": ["USER_PROVIDED", "VERIFIED_GOV_SOURCE", "OFFICIAL_API", "AI_INTERPRETATION", "REQUIRES_VERIFICATION", "INFORMATION_UNAVAILABLE", "DEMO"],
        },
        "blocks": blocks_out,
        "flow": "Project → Business information → UDYAM → MCA → Pincode → Environment → Industrial context → Regulatory Digital Twin → Rule engine → Approval engine → Documents/Dependencies → Readiness → Smart Action Guide → Government route",
        "disclaimer": ("Every value carries provenance. DATASET rows come from public government datasets (not verifications); "
                       "USER_PROVIDED rows are your own declarations; AI_INTERPRETATION rows are deterministic computations over your data. "
                       "Nothing here is an official government verification."),
    }

# ══════════════════════ DECISION TRAIL (§G) ══
@router.get("/projects/{project_id}/decision-trail")
def decision_trail(project_id: int, template_code: str | None = None, limit: int = 100, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """WHY / WHAT EVIDENCE / WHICH RULE / WHAT IS MISSING — for every
    deterministic rule evaluation recorded by the approval engine."""
    project = project_access(db, user, project_id)
    q = select(models.DecisionTrail).where(models.DecisionTrail.project_id == project.id)
    if template_code:
        q = q.where(models.DecisionTrail.approval_template_code == template_code)
    rows = db.scalars(q.order_by(models.DecisionTrail.id.desc()).limit(max(1, min(limit, 500)))).all()
    return {
        "trail": [
            {"id": r.id, "approval": r.approval_name, "template_code": r.approval_template_code,
             "authority": r.authority, "rule_key": r.rule_key, "rule_expression": r.rule_expression,
             "result": r.result, "triggering_facts": r.triggering_facts or {}, "missing_facts": r.missing_facts or [],
             "explanation": r.explanation, "legal_basis": r.legal_basis or [], "source_url": r.source_url,
             "source_status": r.source_status, "rule_version": r.rule_version, "engine_version": r.engine_version,
             "recorded_at": r.created_at.isoformat() if r.created_at else None, "is_demo": r.is_demo}
            for r in rows
        ],
        "declaration": "Every row is an immutable record of a deterministic rule evaluation. The LLM may explain these results — it never decides them.",
    }


# ══════════════════════ APPLICATION PACKAGE (§M) ══
@router.get("/projects/{project_id}/application-package")
def get_application_package(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    from ..services.lifecycle import application_package
    project = project_access(db, user, project_id)
    return application_package(db, project)


# ══════════════════════ MAITRI HANDOFF (§N) ══
@router.post("/projects/{project_id}/maitri-handoff")
def maitri_handoff(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """MANUAL handoff to the official Maharashtra MAITRI portal: NIECP-AI
    prepares the package, the user files on the portal. No submission is
    automated and no government response is ever claimed."""
    from ..services.lifecycle import application_package
    project = project_access(db, user, project_id)
    profile = project.profile
    state = (profile.state_code if profile else "") or ""
    if state.upper() != "MH":
        return {
            "ok": False,
            "status": "PENDING_AUTHORIZATION",
            "message": "MAITRI handoff applies to Maharashtra projects. Use the portal directory for your state's official single window.",
            "official_directory": "/government-portals",
            "note": "No state portal is claimed or opened automatically.",
        }
    package = application_package(db, project)
    audit_event(db, action="MAITRI_HANDOFF_PREPARED", action_category="GOVERNMENT_DATA", user_id=user.id,
                project_id=project.id, resource_type="maitri_handoff", integration_mode="OFFICIAL_REDIRECT",
                provider="Maharashtra MAITRI", commit=True)
    return {
        "ok": True,
        "status": "MANUAL_HANDOFF",
        "integration_mode": "OFFICIAL_REDIRECT",
        "portal": {"name": "Maharashtra MAITRI", "url": "https://maitri.maharashtra.gov.in/"},
        "package_summary": {
            "approvals": len(package["approvals"]),
            "missing_items": len(package["missing_items"]),
            "validation_findings": package["unresolved_issues"]["validation_findings"],
            "readiness": package["readiness"]["overall"],
            "open_queries": len(package["unresolved_issues"]["queries"]),
        },
        "review_checklist": [
            "Review the application package and every validation finding",
            "Resolve missing items before filing",
            "Open the official MAITRI portal and file there — NIECP-AI never submits",
            "Record the official acknowledgement/reference here afterwards (self-reported)",
        ],
        "labels": ["MANUAL", "OFFICIAL_REDIRECT", "NOT CLAIMED: submission, officer response, submission ID, approval status"],
        "notice": "MANUAL HANDOFF — NIECP-AI prepares the package; you file on the official MAITRI portal. No application is submitted and no government response is claimed by this action.",
    }


# ══════════════════════ SLA ENGINE (§Q) ══
@router.get("/projects/{project_id}/sla")
def project_sla_endpoint(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    from ..services.lifecycle import project_sla
    project = project_access(db, user, project_id)
    return project_sla(db, project)


# ══════════════════════ BOTTLENECK ENGINE (§R) ══
@router.get("/projects/{project_id}/bottlenecks")
def project_bottlenecks_endpoint(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    from ..services.lifecycle import project_bottlenecks
    project = project_access(db, user, project_id)
    return project_bottlenecks(db, project)
