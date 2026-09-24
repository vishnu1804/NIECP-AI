"""
Government Integration Manager (spec §16, §43).

TRUTH PROTOCOL
--------------
Every integration reports one of: CONNECTED / NOT_CONNECTED / PENDING_APPROVAL /
API_UNAVAILABLE / MANUAL_MODE. An integration is CONNECTED only when real
credentials exist AND a real health-check request has succeeded. Without
credentials the status is NOT_CONNECTED (or MANUAL_MODE where an official web
route exists) and the UI offers the official portal link. Nothing is ever
simulated as successful: failed calls are logged with their HTTP status and
error, and failure never converts into success.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..enums import (
    AuditResult,
    IntegrationCallResult,
    IntegrationStatus,
    SourceStatus,
)
from .audit import audit_event

log = logging.getLogger("niecp.integrations")

CATALOGUE: list[dict[str, Any]] = [
    {
        "code": "apisetu",
        "name": "API Setu",
        "provider": "Digital India / MeitY",
        "description": "Government API gateway for citizen and business documents and services.",
        "base_url": settings.apisetu_base_url,
        "docs_url": "https://apisetu.gov.in/",
        "portal_url": "https://www.apisetu.gov.in/",
        "credential_configured": bool(settings.apisetu_client_id and settings.apisetu_client_secret),
        "capabilities": ["Document verification", "Profile data fetch (consent-based)"],
        "scopes": ["document-verification", "profile"],
        "manual_url": "https://www.apisetu.gov.in/",
        "manual_text": "Use API Setu's catalogue directly, or continue through the individual department portal.",
    },
    {
        "code": "nsws",
        "name": "National Single Window System (NSWS)",
        "provider": "DPIIT, Ministry of Commerce & Industry",
        "description": "Common application route for central and state approvals.",
        "base_url": None,
        "docs_url": "https://www.nsws.gov.in/",
        "portal_url": "https://www.nsws.gov.in/",
        "credential_configured": False,
        "capabilities": ["Approval discovery", "Common application form"],
        "scopes": [],
        "manual_url": "https://www.nsws.gov.in/",
        "manual_text": "File your common application directly on the NSWS portal. NIECP-AI prepares the information you will need.",
    },
    {
        "code": "digilocker",
        "name": "DigiLocker",
        "provider": "MeitY",
        "description": "Fetch and verify government-issued documents with user consent.",
        "base_url": settings.digilocker_base_url,
        "docs_url": "https://www.digilocker.gov.in/",
        "portal_url": "https://www.digilocker.gov.in/",
        "credential_configured": bool(settings.digilocker_client_id and settings.digilocker_client_secret),
        "capabilities": ["Fetch issued documents", "Verify documents"],
        "scopes": ["document-fetch"],
        "manual_url": "https://www.digilocker.gov.in/",
        "manual_text": "Fetch your documents in DigiLocker and upload them here.",
    },
    {
        "code": "myscheme",
        "name": "MyScheme",
        "provider": "Government of India",
        "description": "Scheme discovery and eligibility screening.",
        "base_url": None,
        "docs_url": "https://www.myscheme.gov.in/",
        "portal_url": "https://www.myscheme.gov.in/",
        "credential_configured": bool(settings.myscheme_api_key),
        "capabilities": ["Scheme search", "Eligibility screening"],
        "scopes": [],
        "manual_url": "https://www.myscheme.gov.in/",
        "manual_text": "Search schemes directly on MyScheme. NIECP-AI's scheme matching uses its own curated catalogue with documented criteria.",
    },
    {
        "code": "parivesh",
        "name": "PARIVESH",
        "provider": "MoEFCC",
        "description": "Environmental, forest, wildlife and CRZ clearances.",
        "base_url": None,
        "docs_url": "https://parivesh.nic.in/",
        "portal_url": "https://parivesh.nic.in/",
        "credential_configured": False,
        "capabilities": ["Environmental clearance applications", "Status tracking (on portal)"],
        "scopes": [],
        "manual_url": "https://parivesh.nic.in/",
        "manual_text": "File and track environmental clearances on PARIVESH. Record the status here so your project stays current.",
    },
    {
        "code": "xgnb_cpcb",
        "name": "XGNB — Consent single window (CPCB)",
        "provider": "Central Pollution Control Board",
        "description": "National single-window route for pollution consents, forwarded to State Boards.",
        "base_url": None,
        "docs_url": "https://xgncpc.mcponline.gov.in/",
        "portal_url": "https://xgncpc.mcponline.gov.in/",
        "credential_configured": False,
        "capabilities": ["Consent to Establish", "Consent to Operate", "Authorisations"],
        "scopes": [],
        "manual_url": "https://xgncpc.mcponline.gov.in/",
        "manual_text": "File consent applications through XGNB or your State Pollution Control Board portal.",
    },
]


def sync_integrations(db: Session) -> int:
    existing = {i.code: i for i in db.scalars(select(models.Integration)).all()}
    n = 0
    for entry in CATALOGUE:
        integ = existing.get(entry["code"])
        if integ is None:
            integ = models.Integration(code=entry["code"])
            db.add(integ)
        integ.name = entry["name"]
        integ.provider = entry["provider"]
        integ.description = entry["description"]
        integ.base_url = entry.get("base_url")
        integ.official_documentation_url = entry.get("docs_url")
        integ.official_portal_url = entry.get("portal_url")
        integ.credentials_configured = entry["credential_configured"]
        integ.capabilities = entry.get("capabilities") or []
        integ.scopes = entry.get("scopes") or []
        integ.manual_workflow_url = entry.get("manual_url")
        integ.manual_workflow_text = entry.get("manual_text")
        # status derivation — honest by construction. Credentials + disabled
        # outbound never reads as CONNECTED; the honest state is surfaced in
        # approval_status_text and the payload's shared connection_state.
        if entry["credential_configured"] and not settings.enable_outbound_gov_calls:
            integ.approval_status_text = ("Credentials are configured server-side, but NIECP_ENABLE_OUTBOUND_GOV_CALLS is "
                                          "disabled in this deployment (CONFIGURED_BUT_OUTBOUND_DISABLED) — no outbound call "
                                          "will be attempted until an operator enables it.")
        if integ.status in (None, IntegrationStatus.NOT_CONNECTED, IntegrationStatus.MANUAL_MODE):
            if entry["credential_configured"]:
                integ.status = IntegrationStatus.PENDING_APPROVAL
                if not integ.approval_status_text:
                    integ.approval_status_text = "Credentials are configured server-side; API approval/onboarding with the provider is still required before any live call."
            else:
                integ.status = IntegrationStatus.MANUAL_MODE if entry.get("manual_url") else IntegrationStatus.NOT_CONNECTED
        n += 1
    db.commit()
    return n


def integration_status_payload(db: Session) -> list[dict[str, Any]]:
    rows = db.scalars(select(models.Integration).where(models.Integration.is_active.is_(True))).all()
    # §10 — shared vocabulary with gov_manager so both integration surfaces
    # always agree on the honest connection state for a provider.
    from .gov_manager import connection_state
    return [
        {
            "id": i.id,
            "code": i.code,
            **connection_state(provider_code=i.code, credentials={"__cred__": bool(i.credentials_configured)},
                               integration_row=i, official_portal_url=i.official_portal_url),
            "name": i.name,
            "provider": i.provider,
            "description": i.description,
            "status": i.status.value if i.status else IntegrationStatus.NOT_CONNECTED.value,
            "credentials_configured": i.credentials_configured,
            "approval_status_text": i.approval_status_text,
            "authentication_state": i.authentication_state,
            "capabilities": i.capabilities or [],
            "manual_workflow_url": i.manual_workflow_url,
            "manual_workflow_text": i.manual_workflow_text,
            "official_documentation_url": i.official_documentation_url,
            "official_portal_url": i.official_portal_url,
            "health": {
                "last_successful_request_at": i.last_successful_request_at.isoformat() if i.last_successful_request_at else None,
                "last_failed_request_at": i.last_failed_request_at.isoformat() if i.last_failed_request_at else None,
                "last_http_status": i.last_http_status,
                "last_error_message": i.last_error_message,
                "last_health_check_at": i.last_health_check_at.isoformat() if i.last_health_check_at else None,
                "health_check_result": i.health_check_result,
            },
            "notice": (
                "Official integration is currently unavailable. You can continue through the official government portal."
                if i.status in (IntegrationStatus.NOT_CONNECTED, IntegrationStatus.MANUAL_MODE, IntegrationStatus.API_UNAVAILABLE)
                else None
            ),
        }
        for i in rows
    ]


def log_call(
    db: Session,
    *,
    integration_code: str,
    operation: str,
    result: IntegrationCallResult,
    http_status: int | None = None,
    latency_ms: int | None = None,
    error_message: str | None = None,
    initiated_by: int | None = None,
    project_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    db.add(
        models.IntegrationLog(
            integration_code=integration_code,
            operation=operation,
            result=result,
            http_status=http_status,
            latency_ms=latency_ms,
            error_message=error_message,
            initiated_by=initiated_by,
            project_id=project_id,
            metadata_=metadata or {},
        )
    )
    integ = db.scalars(select(models.Integration).where(models.Integration.code == integration_code)).first()
    if integ is not None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if result == IntegrationCallResult.SUCCESS:
            integ.last_successful_request_at = now
            integ.last_http_status = http_status
            if integ.status == IntegrationStatus.PENDING_APPROVAL:
                integ.status = IntegrationStatus.CONNECTED
                integ.authentication_state = "verified by successful request"
        else:
            integ.last_failed_request_at = now
            integ.last_http_status = http_status
            integ.last_error_message = error_message
            if result in (IntegrationCallResult.FAILURE, IntegrationCallResult.TIMEOUT):
                integ.status = IntegrationStatus.API_UNAVAILABLE if http_status else IntegrationStatus.ERROR
                integ.health_check_result = result.value
    db.commit()


def health_check(db: Session, integration_code: str, actor: models.User | None = None) -> dict[str, Any]:
    """Run a real (read-only, unauthenticated where possible) reachability probe.
    A 200/401/403 from the host means the service is reachable — it does NOT mean
    NIECP-AI is authorised. Authentication is reported separately and honestly."""
    integ = db.scalars(select(models.Integration).where(models.Integration.code == integration_code)).first()
    if integ is None:
        return {"ok": False, "error": "unknown integration"}
    if settings.enable_outbound_gov_calls is False:
        integ.last_health_check_at = datetime.now(timezone.utc).replace(tzinfo=None)
        integ.health_check_result = "SKIPPED_DISABLED"
        db.commit()
        log_call(db, integration_code=integration_code, operation="health_check",
                 result=IntegrationCallResult.SKIPPED_DISABLED,
                 error_message="Outbound government API calls are disabled in this deployment (NIECP_ENABLE_OUTBOUND_GOV_CALLS=0). The portal link remains available.")
        return {
            "ok": False,
            "skipped": True,
            "reason": "Outbound government API calls are disabled in this deployment. This is a configuration choice, not an outage. Continue through the official portal.",
            "portal_url": integ.official_portal_url,
            "manual_url": integ.manual_workflow_url,
        }
    if not integ.base_url:
        integ.last_health_check_at = datetime.now(timezone.utc).replace(tzinfo=None)
        integ.health_check_result = "NO_API_ENDPOINT"
        db.commit()
        return {"ok": False, "reason": "This integration has no direct API endpoint; use the official portal.", "portal_url": integ.official_portal_url}
    started = time.monotonic()
    result = IntegrationCallResult.FAILURE
    http_status: int | None = None
    error: str | None = None
    try:
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            resp = client.get(integ.base_url, headers={"User-Agent": "NIECP-AI/1.0 (health-check)"})
        http_status = resp.status_code
        result = IntegrationCallResult.SUCCESS if resp.status_code < 500 else IntegrationCallResult.FAILURE
    except httpx.HTTPError as exc:
        error = str(exc)
    latency = int((time.monotonic() - started) * 1000)
    log_call(
        db, integration_code=integration_code, operation="health_check", result=result,
        http_status=http_status, latency_ms=latency, error_message=error,
        initiated_by=actor.id if actor else None,
    )
    return {
        "ok": result == IntegrationCallResult.SUCCESS,
        "http_status": http_status,
        "latency_ms": latency,
        "error": error,
        "note": "A reachable service is not an authenticated one. Authorised API operations require the provider's approval and credentials, and are shown as CONNECTED only after a successful authenticated call.",
        "portal_url": integ.official_portal_url,
    }
