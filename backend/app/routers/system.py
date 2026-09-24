"""System endpoints: health, provenance disclaimers, meta catalogues."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models
from ..ai import llm
from ..config import settings
from datetime import datetime

from ..database import check_database_connectivity, database_dialect, get_db
from ..enums import PlatformRole
from ..knowledge.data.states import STATES
from ..services.gov_integrations import integration_status_payload
from ..services.localization import SUPPORTED_LANGUAGES, all_strings
from ..services.pwa import service_worker_version
from ..services.profile_facts import PROFILE_FIELDS, label_for
from ..services.auth_service import get_current_user, get_current_user_optional
from ..knowledge.data.industries import QUESTION_SETS

router = APIRouter()


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, Any]:
    db_ok, db_msg = check_database_connectivity()
    user_count = 0
    if db_ok:
        try:
            user_count = db.scalar(select(func.count(models.User.id))) or 0
        except Exception:  # noqa: BLE001 — first boot before tables exist
            db_ok = False
            db_msg = "tables not initialised yet (run migrations or restart once)"
    return {
        "status": "ok" if db_ok else "degraded",
        "app": settings.app_name,
        "long_name": settings.app_long_name,
        "version": settings.version,
        "environment": settings.environment,
        "database": {"dialect": database_dialect(), "connected": db_ok, "detail": db_msg},
        "seeded": user_count > 0,
        "sw_version": service_worker_version(),
        "production_blockers": settings.validate_production_readiness(),
        "time": datetime.utcnow().isoformat() + "Z",
    }


@router.get("/system/provenance")
def provenance() -> dict[str, Any]:
    """The platform's honesty contract, machine readable (spec §6/§37/§52)."""
    from ..enums import SourceStatus

    return {
        "principles": [
            "NIECP-AI never claims to grant or guarantee government approval.",
            "Applicability verdicts come from a deterministic rule engine evaluated on your project profile; every verdict shows the matched facts.",
            "Government actions (submission, payment, document transmission) require your explicit confirmation.",
            "Where a live government integration is unavailable, NIECP-AI shows the official portal and manual workflow — it never simulates connectivity.",
            "Government statuses shown in the app are user-recorded or demo-labelled; the authority's record is always the official one.",
            "Every important AI answer shows its source, confidence and last-verified date.",
        ],
        "source_statuses": [s.value for s in SourceStatus],
    }


@router.get("/system/llm")
def llm_status_endpoint() -> dict[str, Any]:
    return llm.llm_status()


@router.get("/system/integrations/summary")
def integrations_summary(db: Session = Depends(get_db), user: models.User | None = Depends(get_current_user_optional)) -> dict[str, Any]:
    rows = integration_status_payload(db)
    return {"count": len(rows), "connected": sum(1 for r in rows if r["status"] == "CONNECTED"), "integrations": rows}


@router.get("/meta/languages")
def languages() -> dict[str, Any]:
    return {"languages": SUPPORTED_LANGUAGES, "strings": all_strings()}


@router.get("/meta/states")
def states() -> dict[str, Any]:
    return {"states": STATES}


@router.get("/meta/industries")
def industries(db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = db.scalars(select(models.Industry).where(models.Industry.is_active.is_(True))).all()
    return {
        "industries": [
            {
                "code": i.code,
                "name": i.name,
                "name_ta": i.name_ta,
                "name_hi": i.name_hi,
                "description": i.description,
                "question_sets": i.question_sets,
                "requires_description": i.code == "other",
            }
            for i in rows
        ],
        "question_set_labels": QUESTION_SETS,
    }


@router.get("/meta/profile-fields")
def profile_fields() -> dict[str, Any]:
    return {"fields": [{"name": f, "label": label_for(f)} for f in PROFILE_FIELDS]}


@router.get("/meta/roles")
def roles() -> dict[str, Any]:
    return {"platform_roles": [r.value for r in PlatformRole]}
