"""Government Integration Manager — execution channel layer (Prompt §3, §9, §10, §12, §24).

Architecture required by the spec:

                         NIECP-AI
                            |
                  Government Integration
                         Manager  ← (this module + gov_integrations)
                            |
       +--------------------+--------------------+
       ↓                    ↓                    ↓
 DEMO ADAPTER        OFFICIAL REDIRECT      MANUAL ADAPTER
 (demo_government)   (this module)          (this module + existing
       |                                     application PATCH/status gates)
       ↓
 Future authorized APIs (NSWS / TN SWS / API Setu) — architecturally supported,
 NOT ACTIVATED: every registry row ships with live=False until a real,
 provider-approved, credentialed connection exists.

The rest of NIECP-AI communicates ONLY through this manager (or the existing
gov_integrations service) — never directly with a government provider.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..enums import (
    ApplicationStatus,
    AuditResult,
    AuthorizationStatus,
    IntegrationMode,
    SourceStatus,
)
from ..models_mixins import utcnow
from . import demo_government
from .audit import audit_event

PROVIDER_NIECP_DEMO = demo_government.PROVIDER_CODE


# ═══════════════════════════════════════════ APPLY DECISION LOGIC (§24) ══
def decide_execution_channels(
    db: Session, *, project: models.Project, application: models.Application
) -> dict[str, Any]:
    """Which execution channels are honestly available for this application?

    1. Authorized LIVE API   → only when a real verified connection exists
                               (never in the current deployment).
    2. Official portal       → when the approval/portal registry stores a URL.
    3. Manual                → always available.
    + Demo                   → demonstration deployments only, clearly labelled.
    """
    portal_url = _verified_portal_url(db, application)
    demo_ok, demo_reason = demo_government.demo_available()

    authorized_api = None
    if application.provider and application.provider != PROVIDER_NIECP_DEMO:
        integ = db.scalars(
            select(models.Integration).where(models.Integration.code == application.provider)
        ).first()
        if integ is not None and integ.status == "CONNECTED":  # only after a real authenticated success
            authorized_api = integ.code

    demo_channel = {
        "channel": IntegrationMode.DEMO.value,
        "available": bool(demo_ok),
        "reason": None if demo_ok else demo_reason,
        "label": demo_government.LABEL,
        "notice": demo_government.NOTICE,
        "requires_confirmation": True,
        "confirmation_text": "You are about to submit this application to the NIECP demonstration environment using synthetic data.",
        "confirm_label": "RUN DEMO",
    }
    redirect_channel = {
        "channel": IntegrationMode.OFFICIAL_REDIRECT.value,
        "available": portal_url is not None,
        "portal_url": portal_url,
        "reason": None if portal_url is not None else "No verified official portal URL is stored for this approval — ask NIECP-AI or check with the authority; NIECP-AI will not guess one.",
        "requires_confirmation": False,
        "confirm_label": "OPEN OFFICIAL GOVERNMENT PORTAL",
        "notice": "NIECP-AI opens the official portal in a new tab. You file the application there; NIECP-AI never submits on your behalf.",
    }
    manual_channel = {
        "channel": IntegrationMode.MANUAL.value,
        "available": True,
        "notice": "Record what the authority communicated (reference, dates, status) yourself. Manual entries are stored as USER_ENTERED.",
        "confirm_label": "RECORD MANUALLY",
    }

    if authorized_api:
        recommended = IntegrationMode.LIVE.value
    elif portal_url:
        recommended = IntegrationMode.OFFICIAL_REDIRECT.value
    else:
        recommended = IntegrationMode.MANUAL.value

    return {
        "application_id": application.id,
        "recommended": recommended,
        "channels": {
            "AUTHORIZED_API": {"available": authorized_api is not None, "provider": authorized_api},
            "DEMO": demo_channel,
            "OFFICIAL_REDIRECT": redirect_channel,
            "MANUAL": manual_channel,
        },
        "declaration": (
            "NIECP-AI never submits applications to a government authority on its own. "
            "Execution happens through the official portal (by you), manual record-keeping, "
            "or the clearly-labelled internal demo environment."
        ),
    }


def _verified_portal_url(db: Session, application: models.Application) -> str | None:
    """Only stored URLs — never invented. Preference: the application's own
    (copied from the approval at creation), else the approval, else a matching
    GovernmentPortal registry row."""
    for candidate in (application.official_portal_url,):
        if candidate:
            return candidate
    approval = application.project_approval
    if approval is not None and approval.official_portal_url:
        return approval.official_portal_url
    if application.authority:
        row = db.scalars(
            select(models.GovernmentPortal).where(
                models.GovernmentPortal.is_active.is_(True),
                models.GovernmentPortal.official_url.isnot(None),
                models.GovernmentPortal.department.contains(application.authority[:60]),
            )
        ).first()
        if row is not None:
            return row.official_url
    return None


# ═════════════════════════════════ OFFICIAL REDIRECT ADAPTER (§9) ══
def official_redirect(
    db: Session, *, project: models.Project, application: models.Application,
    user: models.User, request_id: str | None = None,
) -> dict[str, Any]:
    """APPLICATION PREPARATION COMPLETE → [ OPEN OFFICIAL GOVERNMENT PORTAL ].

    NIECP-AI has no API authorization anywhere, so this is the primary real
    channel: analysis, why, documents, dependencies, readiness, preparation and
    confirmation all happen here; the actual filing happens on the official
    portal, opened from a URL stored in NIECP's registry (never guessed)."""
    portal_url = _verified_portal_url(db, application)
    if not portal_url:
        return {
            "ok": False,
            "error": "No verified official portal URL is stored for this approval. NIECP-AI does not guess government URLs — check the Government Portals page or ask the assistant.",
        }
    corr = demo_government.correlation_id()
    packet = {
        "application_reference": application.official_reference,
        "title": application.title,
        "authority": application.authority,
        "preparation_summary": application.preparation_summary or {},
        "ready": application.status in (ApplicationStatus.READY_TO_APPLY, ApplicationStatus.USER_CONFIRMED, ApplicationStatus.SUBMITTED),
        "prepared_at": application.prepared_at.isoformat() if application.prepared_at else None,
        "user_confirmed": application.user_confirmed_at is not None,
        "portal_url": portal_url,
        "notice": "You are leaving NIECP-AI for the official government portal. NIECP-AI does not transfer your data there; you enter it yourself. Record the outcome back here (Manual mode) afterwards.",
        "disclaimer": "NIECP-AI is not a government portal and does not file applications.",
    }
    audit_event(
        db, action="OFFICIAL_REDIRECT_OPENED", action_category="GOVERNMENT_EXECUTION",
        user_id=user.id, project_id=project.id, resource_type="application",
        resource_id=str(application.id), after={"portal_url": portal_url},
        request_id=request_id, correlation_id=corr,
        integration_mode=IntegrationMode.OFFICIAL_REDIRECT.value,
        provider="official_portal", commit=True,
    )
    return {"ok": True, "redirect": packet, "correlation_id": corr}


# ═════════════════════════════════ MANUAL APPLICATION ADAPTER (§10) ══
MANUAL_STATUSES = [
    ApplicationStatus.DRAFT, ApplicationStatus.SUBMITTED, ApplicationStatus.UNDER_REVIEW,
    ApplicationStatus.QUERY_RAISED, ApplicationStatus.USER_RESPONDED, ApplicationStatus.APPROVED,
    ApplicationStatus.REJECTED,
]


def manual_packet(db: Session, *, project: models.Project, application: models.Application) -> dict[str, Any]:
    """Copy/download packet for offline filing + a checklist of everything to
    record back. The recording itself reuses the existing manual gates
    (PATCH official_reference with confirmation, POST status with
    self-reported confirmation) — no duplicate system."""
    summary = application.preparation_summary or {}
    docs_comp = summary.get("missing_documents") or []
    checklist = [
        "Carry/print this packet and the listed documents",
        "File the application through the authority's channel (online portal or office)",
        "Pay the official fee, if any, only through the authority's own channel",
        "Obtain the acknowledgement / application number",
        "Record it here: Applications → the application → Record official reference (requires your confirmation)",
        "Keep updating the status here as the authority communicates (self-reported, with evidence)",
    ]
    return {
        "mode": IntegrationMode.MANUAL.value,
        "source_status": SourceStatus.USER_PROVIDED.value,
        "application": {
            "id": application.id,
            "title": application.title,
            "authority": application.authority,
            "status": application.status.value,
            "official_portal_url": application.official_portal_url,
            "official_reference": application.official_reference,
            "readiness_score": application.readiness_score,
        },
        "requirements": summary.get("requirements", []),
        "profile_snapshot": summary.get("profile_snapshot", {}),
        "missing_documents": docs_comp,
        "record_fields": [
            {"field": "official_reference", "label": "Application / acknowledgement number", "gate": "explicit confirmation required"},
            {"field": "submitted_at", "label": "Submission date"},
            {"field": "authority", "label": "Authority / office filed with"},
            {"field": "official_portal_url", "label": "Official portal used"},
            {"field": "status", "label": "Current status", "allowed": [s.value for s in MANUAL_STATUSES], "gate": "self-reported confirmation required"},
            {"field": "query", "label": "Government query received", "where": "Queries page"},
            {"field": "decision", "label": "Approval / rejection + valid until"},
            {"field": "notes", "label": "Notes / government communication reference"},
        ],
        "checklist": checklist,
        "notice": "All manual entries are stored as USER_ENTERED and shown as self-reported. NIECP-AI never generates references, decisions or government responses.",
    }


def render_manual_text(packet: dict[str, Any]) -> str:
    """Plain-text rendering of the manual packet for download/printing."""
    app = packet["application"]
    lines = [
        "NIECP-AI — MANUAL APPLICATION PACKET",
        "=" * 46,
        f"Application: {app['title']}",
        f"Authority:   {app['authority'] or '—'}",
        f"Status:      {app['status']}",
        f"Readiness:   {app['readiness_score'] if app['readiness_score'] is not None else '—'}",
        "",
        "PROFILE SNAPSHOT",
        *(f"  {k}: {v}" for k, v in (packet.get("profile_snapshot") or {}).items()),
        "",
        "REQUIREMENTS",
        *(f"  [{'x' if r.get('satisfied') else ' '}] {r.get('title')}{' (mandatory)' if r.get('mandatory') else ''}"
          for r in packet.get("requirements", [])),
        "",
        "MISSING DOCUMENTS",
        *(f"  - {d}" for d in (packet.get("missing_documents") or ["(none recorded)"])),
        "",
        "AFTER FILING — RECORD BACK IN NIECP-AI",
        *(f"  {i+1}. {step}" for i, step in enumerate(packet.get("checklist", []))),
        "",
        packet.get("notice", ""),
    ]
    return "\n".join(lines)


# ═════════════════════════════ GOVERNMENT REGISTRY (§12, §23) ══
REGISTRY_SEED: list[dict[str, Any]] = [
    {
        "provider_code": "nsws",
        "provider_name": "National Single Window System (NSWS)",
        "service_name": "Common application route for central & state approvals",
        "jurisdiction": "CENTRAL",
        "authority": "DPIIT, Ministry of Commerce & Industry",
        "official_portal_url": "https://www.nsws.gov.in/",
        "api_directory_url": None,
        "api_specification_url": None,
        "authorization_status": AuthorizationStatus.PENDING,
        "authentication_method": "Provider onboarding required (not provisioned)",
        "fallback_mode": IntegrationMode.OFFICIAL_REDIRECT,
        "data_categories": ["Business profile", "Application details"],
        "source_type": "NOT_VERIFIED",
        "notes": "Authorization PENDING — no API activated. Continue through the official portal.",
    },
    {
        "provider_code": "tn_single_window",
        "provider_name": "Tamil Nadu Single Window (Guidance Tamil Nadu)",
        "service_name": "State approvals facilitation and single window",
        "jurisdiction": "STATE:TN",
        "authority": "Government of Tamil Nadu — Industries & Commerce Department",
        "official_portal_url": "https://www.guidancetamilnadu.in/",
        "authorization_status": AuthorizationStatus.PENDING,
        "authentication_method": "Provider onboarding required (not provisioned)",
        "fallback_mode": IntegrationMode.OFFICIAL_REDIRECT,
        "data_categories": ["Business profile", "Application details"],
        "source_type": "NOT_VERIFIED",
        "notes": "Authorization PENDING — no API activated. Continue through the official portal.",
    },
    {
        "provider_code": "apisetu",
        "provider_name": "API Setu",
        "service_name": "Document verification and consent-based profile services",
        "jurisdiction": "CENTRAL",
        "authority": "Digital India Corporation / MeitY",
        "official_portal_url": "https://www.apisetu.gov.in/",
        "api_directory_url": "https://apisetu.gov.in/apis",
        "authorization_status": AuthorizationStatus.NOT_AUTHORIZED,
        "authentication_method": "OAuth2 client credentials (credentials not provisioned)",
        "fallback_mode": IntegrationMode.OFFICIAL_REDIRECT,
        "data_categories": ["Identity documents (consent-based)"],
        "consent_required": True,
        "source_type": "NOT_VERIFIED",
        "notes": "NOT_AUTHORIZED — credentials are not provisioned server-side.",
    },
    {
        "provider_code": PROVIDER_NIECP_DEMO,
        "provider_name": "NIECP Demo Government",
        "service_name": "Internal demonstration workflow (synthetic)",
        "jurisdiction": None,
        "authority": "NIECP-AI (internal demonstration system — not a government entity)",
        "official_portal_url": None,
        "environment": "DEMO",
        "authorization_status": AuthorizationStatus.NOT_AUTHORIZED,
        "authentication_method": "None — internal sandbox",
        "fallback_mode": IntegrationMode.DEMO,
        "supported_operations": ["submit", "status", "queries", "respond", "documents", "approvals"],
        "data_categories": ["Synthetic demonstration data"],
        "source_type": "DEMO",
        "is_demo": True,
        "notes": "INTERNAL NIECP DEMO. Synthetic data only; never a government API.",
    },
    {
        "provider_code": "udyam_dataset",
        "provider_name": "Ministry of MSME — UDYAM dataset (data.gov.in)",
        "service_name": "UDYAM/MSME registration dataset search",
        "jurisdiction": "CENTRAL",
        "authority": "Ministry of Micro, Small and Medium Enterprises",
        "official_portal_url": "https://udyamregistration.gov.in/",
        "api_directory_url": "https://data.gov.in/",
        "authorization_status": AuthorizationStatus.PENDING,
        "authentication_method": "data.gov.in API key (server-side; not provisioned)",
        "fallback_mode": IntegrationMode.MANUAL,
        "data_categories": ["Enterprise name", "State", "District", "NIC activity"],
        "source_type": "NOT_VERIFIED",
        "notes": "Dataset search (GOVERNMENT_DATASET_MATCH), not a verification API. Awaiting data.gov.in API key provisioning.",
    },
    {
        "provider_code": "mca",
        "provider_name": "Ministry of Corporate Affairs",
        "service_name": "Company/LLP identity dataset (CIN)",
        "jurisdiction": "CENTRAL",
        "authority": "Ministry of Corporate Affairs",
        "official_portal_url": "https://www.mca.gov.in/",
        "authorization_status": AuthorizationStatus.PENDING,
        "authentication_method": "OAuth2 client credentials (not provisioned)",
        "fallback_mode": IntegrationMode.OFFICIAL_REDIRECT,
        "data_categories": ["Company name", "CIN", "Registration status"],
        "source_type": "NOT_VERIFIED",
        "notes": "MCA_DATA_MATCH only from an authorized MCA API. Until then: official portal + manual CIN entry.",
    },
    {
        "provider_code": "pincode",
        "provider_name": "India Post — pincode dataset (data.gov.in)",
        "service_name": "PIN → state / district / post office lookup",
        "jurisdiction": "CENTRAL",
        "authority": "Department of Posts",
        "official_portal_url": "https://www.indiapost.gov.in/",
        "api_directory_url": "https://data.gov.in/",
        "authorization_status": AuthorizationStatus.PENDING,
        "authentication_method": "data.gov.in API key (server-side; not provisioned — offline coarse index used meanwhile)",
        "fallback_mode": IntegrationMode.MANUAL,
        "data_categories": ["Pincode", "State", "District", "Post office"],
        "source_type": "NOT_VERIFIED",
        "notes": "Authoritative lookups need the data.gov.in key; the offline postal-circle index is coarse and requires user confirmation.",
    },
    {
        "provider_code": "cpcb",
        "provider_name": "Central Pollution Control Board (CPCB)",
        "service_name": "Environmental context — real-time air quality (data.gov.in) & consent portal redirection",
        "jurisdiction": "CENTRAL",
        "authority": "CPCB, Ministry of Environment, Forest and Climate Change",
        "official_portal_url": "https://cpcb.nic.in/",
        "authorization_status": AuthorizationStatus.PENDING,
        "authentication_method": "Not provisioned",
        "fallback_mode": IntegrationMode.OFFICIAL_REDIRECT,
        "data_categories": ["Standards", "Monitoring data (where published)"],
        "source_type": "NOT_VERIFIED",
        "notes": "Consents remain with SPCB/PCC portals (portal directory). Applicability stays deterministic in NIECP's own rule engine.",
    },
    {
        "provider_code": "maitri",
        "provider_name": "Maharashtra MAITRI",
        "service_name": "State single-window facilitation & incentives (Maharashtra)",
        "jurisdiction": "STATE:MH",
        "authority": "Government of Maharashtra (industries)",
        "official_portal_url": "https://maitri.maharashtra.gov.in/",
        "authorization_status": AuthorizationStatus.PENDING,
        "authentication_method": "Portal accounts (user's own) — no API provisioned",
        "fallback_mode": IntegrationMode.OFFICIAL_REDIRECT,
        "data_categories": ["Project details (user-entered on the portal)"],
        "source_type": "NOT_VERIFIED",
        "notes": "OFFICIAL PORTAL route. NIECP-AI surfaces the relevant service catalogue and links the official portal; submission is never automated.",
    },
    {
        "provider_code": "cpcb_surface_water",
        "provider_name": "CPCB Surface Water Quality (via data.gov.in)",
        "service_name": "Surface water quality — HISTORICAL / SUPPORTING observations",
        "jurisdiction": "CENTRAL",
        "authority": "CPCB, Ministry of Environment, Forest and Climate Change",
        "official_portal_url": "https://cpcb.nic.in/",
        "authorization_status": AuthorizationStatus.PENDING,
        "authentication_method": "data.gov.in API key (server-side) — dataset not provisioned yet",
        "fallback_mode": IntegrationMode.OFFICIAL_REDIRECT,
        "data_categories": ["pH", "BOD", "COD", "Dissolved oxygen", "TDS", "Turbidity", "Nitrate", "Phosphate"],
        "source_type": "NOT_VERIFIED",
        "notes": "HISTORICAL / SUPPORTING DATA only — never shown as current water quality, never an approval determination.",
    },
    {
        "provider_code": "asi_industrial",
        "provider_name": "Annual Survey of Industries (via data.gov.in)",
        "service_name": "Factory-sector statistical context (INDUSTRIAL STATISTICAL DATA)",
        "jurisdiction": "CENTRAL",
        "authority": "MoSPI, Government of India",
        "official_portal_url": "https://mospi.gov.in/",
        "authorization_status": AuthorizationStatus.PENDING,
        "authentication_method": "data.gov.in API key (server-side) — dataset not provisioned yet",
        "fallback_mode": IntegrationMode.OFFICIAL_REDIRECT,
        "data_categories": ["Sector statistics", "Factory-sector benchmarks"],
        "source_type": "NOT_VERIFIED",
        "notes": "INDUSTRIAL STATISTICAL DATA — benchmarking/analytics context only; never determines a specific company's approval requirements.",
    },
]




def sync_registry(db: Session) -> int:
    """Idempotent seed of the integration registry (called at startup)."""
    n = 0
    existing = {r.provider_code: r for r in db.scalars(select(models.GovernmentIntegrationRegistry)).all()}
    for entry in REGISTRY_SEED:
        row = existing.get(entry["provider_code"])
        if row is None:
            row = models.GovernmentIntegrationRegistry(provider_code=entry["provider_code"])
            db.add(row)
        for key, value in entry.items():
            setattr(row, key, value)
        row.environment = entry.get("environment", "OFFICIAL_REDIRECT")
        row.schema_version = entry.get("schema_version", "1.0")
        row.last_verified_at = None  # honest: URLs authored, not re-verified live
        row.live = False             # never faked
        row.consent_required = entry.get("consent_required", True)
        row.supported_operations = entry.get("supported_operations", [])
        n += 1
    db.commit()
    return n


def registry_payload(db: Session) -> list[dict[str, Any]]:
    rows = db.scalars(select(models.GovernmentIntegrationRegistry).order_by(models.GovernmentIntegrationRegistry.id)).all()
    return [
        {
            "provider_code": r.provider_code,
            "provider_name": r.provider_name,
            "service_name": r.service_name,
            "jurisdiction": r.jurisdiction,
            "authority": r.authority,
            "official_portal_url": r.official_portal_url,
            "api_directory_url": r.api_directory_url,
            "api_specification_url": r.api_specification_url,
            "environment": r.environment,
            "authorization_status": r.authorization_status.value if hasattr(r.authorization_status, "value") else r.authorization_status,
            "supported_operations": r.supported_operations or [],
            "authentication_method": r.authentication_method,
            "schema_version": r.schema_version,
            "last_verified_at": r.last_verified_at.isoformat() if r.last_verified_at else None,
            "fallback_mode": r.fallback_mode.value if hasattr(r.fallback_mode, "value") else r.fallback_mode,
            "data_categories": r.data_categories or [],
            "consent_required": r.consent_required,
            "live": r.live,
            "source_type": r.source_type,
            "is_demo": r.is_demo,
            "notes": r.notes,
        }
        for r in rows
    ]


# ═══════════════════ SHARED CONNECTION-STATE RESOLVER (§10/§11) ══
# ONE vocabulary used by BOTH gov_manager.service_cards AND
# gov_integrations.integration_status_payload so the two integration surfaces
# can never contradict each other:
#   CONNECTED                        real authorized provider connection with a successful authenticated call
#   CONFIGURED                       credentials present, outbound enabled, no successful call yet
#   CONFIGURED_BUT_OUTBOUND_DISABLED credentials present but NIECP_ENABLE_OUTBOUND_GOV_CALLS=false
#   PENDING_AUTHORIZATION            provider authorization/onboarding missing
#   OFFICIAL_REDIRECT                no credentials — official portal route offered
#   MANUAL                           no portal URL known — record manually
#   DEMO                             internal synthetic demonstration system
#   FAILED                           last call failed (never converted into success; shown alongside the base state)


def connection_state(
    *,
    provider_code: str,
    credentials: dict[str, bool] | None = None,
    integration_row: "models.Integration | None" = None,
    last_live_success_at: Any = None,
    is_demo: bool = False,
    official_portal_url: str | None = None,
    environment: str | None = None,
) -> dict[str, Any]:
    """Resolve one honest connection state from REAL conditions only."""
    creds = credentials or {}
    has_creds = bool(creds) and all(creds.values())
    outbound = bool(settings.enable_outbound_gov_calls)
    row_status = (integration_row.status.value if integration_row is not None and integration_row.status else None)
    real_connected = (integration_row is not None and row_status == "CONNECTED" and has_creds and outbound) or (
        last_live_success_at is not None and has_creds and outbound)
    failed = integration_row is not None and integration_row.last_failed_request_at is not None and (
        integration_row.last_successful_request_at is None or integration_row.last_failed_request_at > integration_row.last_successful_request_at)

    if is_demo or provider_code == "niecp_demo_government":
        state = "DEMO"
    elif real_connected:
        state = "CONNECTED"
    elif has_creds and not outbound:
        state = "CONFIGURED_BUT_OUTBOUND_DISABLED"
    elif has_creds:
        state = "CONFIGURED"
    elif "PENDING" in (environment or "") and not official_portal_url:
        state = "PENDING_AUTHORIZATION"
    elif (environment or "") == "OFFICIAL_REDIRECT" or official_portal_url:
        state = "OFFICIAL_REDIRECT"
    else:
        state = "MANUAL"
    return {
        "connection_state": state,
        "credentials_configured": has_creds,
        "outbound_enabled": outbound,
        "last_call_failed": bool(failed),
        "note": (
            "Connected after a real, successful authorized call." if state == "CONNECTED" else
            "Credentials are configured server-side, but a successful authorized call has not been recorded yet." if state == "CONFIGURED" else
            "Credentials are configured, but NIECP_ENABLE_OUTBOUND_GOV_CALLS is disabled in this deployment — no outbound call will be attempted." if state == "CONFIGURED_BUT_OUTBOUND_DISABLED" else
            "Awaiting provider authorization/onboarding. The official portal route remains available." if state == "PENDING_AUTHORIZATION" else
            "No API credentials — NIECP-AI offers the official government portal route." if state == "OFFICIAL_REDIRECT" else
            "Internal demonstration system — synthetic data only, never a government connection." if state == "DEMO" else
            "No API and no verified portal URL — record outcomes manually."
        ),
    }


# ═══════════════════════════ PROVIDER ADAPTER LAYER (data-services upgrade) ══

def record_provider_call(
    db: Session,
    *,
    result,  # gov_providers.AdapterResult
    user_id: int | None = None,
    organization_id: int | None = None,
    project_id: int | None = None,
    consent_id: int | None = None,
) -> None:
    """§16 — audit every external API interaction. Secrets and raw payloads are
    never logged: only status, codes, latency and the correlation id."""
    from . import gov_providers
    from ..enums import IntegrationCallResult

    call_result = (
        IntegrationCallResult.SUCCESS if result.ok
        else IntegrationCallResult.SKIPPED_NO_CREDENTIALS if result.error_code == gov_providers.AdapterErrorCode.NOT_PROVISIONED
        else IntegrationCallResult.FAILURE
    )
    db.add(models.IntegrationLog(
        integration_code=(getattr(result, "provider_code", "") or result.provider)[:64],
        operation=f"{result.operation}"[:120],
        result=call_result,
        http_status=result.http_status,
        latency_ms=result.latency_ms,
        error_message=result.error_code,
        request_ref=result.correlation_id,
        initiated_by=user_id,
        project_id=project_id,
        metadata_={"service": result.service, "mode": result.mode, "consent_id": consent_id, "verification_status": result.verification_status},
    ))
    audit_event(
        db,
        action=f"GOV_DATA_{result.operation.upper()}"[:96],
        action_category="GOVERNMENT_DATA",
        user_id=user_id, organization_id=organization_id, project_id=project_id,
        resource_type="gov_provider_call", resource_id=result.provider[:64],
        correlation_id=result.correlation_id, integration_mode=result.mode, provider=result.provider[:96],
        details={"service": result.service, "error_code": result.error_code, "http_status": result.http_status,
                 "verification_status": result.verification_status, "consent_id": consent_id},
        result=AuditResult.SUCCESS if result.ok else AuditResult.FAILURE,
        commit=False,
    )


def dispatch(
    db: Session,
    *,
    adapter_code: str,
    operation: str,
    user: models.User,
    project: models.Project | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """The ONLY path from the rest of NIECP to a government data provider.
    Runs the adapter operation, records the audit trail, returns a labelled
    payload. Frontend code never sees credentials — only this result."""
    from . import gov_providers

    adapter = gov_providers.get_adapter(adapter_code)
    if adapter is None:
        return {"ok": False, "error_code": "UNKNOWN_PROVIDER", "message": "Unknown government service."}
    fn = getattr(adapter, operation, None)
    if fn is None or not callable(fn):
        return {"ok": False, "error_code": "UNSUPPORTED_OPERATION", "message": "That operation is not supported for this service."}
    result: gov_providers.AdapterResult = fn(**kwargs)
    record_provider_call(db, result=result, user_id=user.id,
                         organization_id=project.organization_id if project else None,
                         project_id=project.id if project else None)
    db.commit()
    return result.to_payload()


def service_cards(db: Session) -> list[dict[str, Any]]:
    """§21 — Government Integrations page cards, merged from the adapter
    registry + the integration health store. Booleans about credentials, never
    their values."""
    from . import gov_providers
    from ..enums import IntegrationCallResult, IntegrationStatus
    from sqlalchemy import select as _select

    integ_rows = {i.code: i for i in db.scalars(_select(models.Integration)).all()}
    # last successful/failed call per provider from the integration log (keyed by CODE)
    last_ok: dict[str, Any] = {}
    last_fail: dict[str, Any] = {}
    logs = db.scalars(_select(models.IntegrationLog).order_by(models.IntegrationLog.created_at.desc()).limit(300)).all()
    for lg in logs:
        key = lg.integration_code
        if key not in last_ok and lg.result == IntegrationCallResult.SUCCESS:
            last_ok[key] = {"operation": lg.operation, "at": lg.created_at.isoformat() if lg.created_at else None, "mode": (lg.metadata_ or {}).get("mode")}
        if key not in last_fail and lg.result == IntegrationCallResult.FAILURE:
            last_fail[key] = {"operation": lg.operation, "at": lg.created_at.isoformat() if lg.created_at else None,
                              "error_code": lg.error_message, "http_status": lg.http_status}
    cards = []
    for adapter in gov_providers.all_adapters():
        m = adapter.meta
        integ = integ_rows.get(m.code)
        resolved = connection_state(
            provider_code=m.code, credentials=adapter.credentials_present(), integration_row=integ,
            last_live_success_at=last_ok.get(m.code), official_portal_url=m.official_portal_url,
            environment=m.environment,
        )
        status = resolved["connection_state"]
        cards.append({
            **m.to_payload(),
            "credentials_configured": adapter.credentials_present(),
            "connection_status": status,
            "connection_note": resolved["note"],
            "outbound_enabled": resolved["outbound_enabled"],
            "last_call_failed": resolved["last_call_failed"],
            "last_failed_call": last_fail.get(m.code),
            "mode_label": status if status in ("CONNECTED", "CONFIGURED", "CONFIGURED_BUT_OUTBOUND_DISABLED", "DEMO") else (m.environment if m.authorization_status == "AUTHORIZED" else ("PENDING_AUTHORIZATION" if "PENDING" in m.authorization_status else m.fallback_mode)),
            "last_successful_call": last_ok.get(m.code),
            "last_verified_at": None,  # set only when a live call actually succeeds
            "health_from_integration_store": {
                "last_successful_request_at": integ.last_successful_request_at.isoformat() if integ and integ.last_successful_request_at else None,
                "last_failed_request_at": integ.last_failed_request_at.isoformat() if integ and integ.last_failed_request_at else None,
                "last_error": integ.last_error_message if integ else None,
            } if integ else None,
            "notice": (
                "Awaiting official partner authorization. You can continue through the official portal."
                if m.authorization_status in ("PENDING", "PENDING_AUTHORIZATION", "NOT_AUTHORIZED") and m.code != "niecp_demo_government"
                else ("Internal demonstration system — synthetic data only. DEMO DATA — NOT A LIVE GOVERNMENT CONNECTION." if m.code == "niecp_demo_government" else None)
            ),
        })
    return cards


# ═══════════════════════════════════ CONSENT MANAGEMENT (§7) ══

CONSENT_TEXT = (
    "I authorise NIECP-AI to request the selected document(s)/data on my behalf from the named government service, "
    "strictly for the stated purpose and project. I understand: (1) NIECP-AI accesses only what I explicitly allow; "
    "(2) retrieved material is stored against my project and shown with GOVERNMENT_RETRIEVED provenance; "
    "(3) AI checks on it are pre-validation, not legal certification; (4) I can revoke this consent at any time, "
    "and revocation stops future access."
)


def create_consent(
    db: Session, *, user: models.User, project: models.Project | None, provider: str,
    service: str, purpose: str, data_categories: list[str], documents_requested: list[str],
    integration_mode: str, accepted: bool,
) -> dict[str, Any]:
    if not accepted:
        audit_event(db, action="CONSENT_DENIED", action_category="CONSENT", user_id=user.id,
                    project_id=project.id if project else None, resource_type="consent",
                    details={"provider": provider, "service": service}, commit=True)
        return {"ok": False, "status": "DENIED", "message": "Consent declined — nothing was or will be accessed."}
    from ..enums import ConsentStatus
    consent = models.ConsentRecord(
        user_id=user.id, organization_id=project.organization_id if project else None,
        project_id=project.id if project else None, provider=provider[:64], service=service[:240],
        purpose=purpose[:2000], data_categories=data_categories or [], documents_requested=documents_requested or [],
        integration_mode=integration_mode[:32], status=ConsentStatus.GRANTED,
        granted_at=utcnow(), consent_text_shown=CONSENT_TEXT,
    )
    db.add(consent)
    db.flush()
    audit_event(db, action="CONSENT_GRANTED", action_category="CONSENT", user_id=user.id,
                project_id=project.id if project else None, resource_type="consent", resource_id=str(consent.id),
                after={"provider": provider, "status": "GRANTED", "documents": documents_requested}, commit=True)
    db.commit()
    return {"ok": True, "consent_id": consent.id, "status": "GRANTED", "consent_text_shown": CONSENT_TEXT,
            "note": "Consent recorded. Actual retrieval still requires the provider integration to be authorized."}


def revoke_consent(db: Session, user: models.User, consent_id: int) -> dict[str, Any]:
    from ..enums import ConsentStatus
    consent = db.get(models.ConsentRecord, consent_id)
    if consent is None or consent.user_id != user.id:
        return {"ok": False, "message": "Consent record not found."}
    consent.status = ConsentStatus.REVOKED
    consent.revoked_at = utcnow()
    audit_event(db, action="CONSENT_REVOKED", action_category="CONSENT", user_id=user.id,
                project_id=consent.project_id, resource_type="consent", resource_id=str(consent.id),
                before={"status": consent.status.value}, after={"status": "REVOKED"}, commit=True)
    db.commit()
    return {"ok": True, "status": "REVOKED"}


def consent_payload(c: models.ConsentRecord) -> dict[str, Any]:
    return {
        "consent_id": c.id, "user_id": c.user_id, "organization_id": c.organization_id, "project_id": c.project_id,
        "provider": c.provider, "service": c.service, "purpose": c.purpose,
        "data_categories": c.data_categories or [], "documents_requested": c.documents_requested or [],
        "integration_mode": c.integration_mode, "status": c.status.value if hasattr(c.status, "value") else str(c.status),
        "granted_at": c.granted_at.isoformat() if c.granted_at else None,
        "expiry": c.expiry.isoformat() if c.expiry else None,
        "revoked_at": c.revoked_at.isoformat() if c.revoked_at else None,
        "is_demo": c.is_demo,
    }
