"""
Catalogue seeding + government portal directory service (spec §17, §36).

Seed discipline:
 * government portals and sources are seeded from the curated data files with
   `verification_status=REQUIRES_VERIFICATION` and `last_verified_at=None`
   until an operator explicitly verifies them (which stamps a real timestamp);
 * nothing here invents a status value, fee or timeline;
 * the seed is idempotent.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..enums import Confidence, Jurisdiction, SourceStatus
from ..knowledge.data.knowledge_data import KNOWLEDGE
from ..knowledge.data.portal_data import PORTALS
from ..knowledge.data.states import STATES
from .approval_engine import sync_catalogue
from ..ai.retrieval import index_knowledge_document
from .scheme_engine import sync_schemes


def seed_reference_data(db: Session) -> dict[str, int]:
    from .gov_integrations import sync_integrations

    counts: dict[str, int] = {}
    counts["industries"] = seed_industries(db)
    counts["approval_templates"] = sync_catalogue(db)["templates"]
    counts["schemes"] = sync_schemes(db)
    counts["portals"] = seed_portals(db)
    counts["sources"] = seed_government_sources(db)
    counts["knowledge_documents"] = seed_knowledge(db)
    counts["integrations"] = sync_integrations(db)
    db.commit()
    return counts


def seed_industries(db: Session) -> int:
    from ..knowledge.data.industries import INDUSTRIES

    existing = {i.code: i for i in db.scalars(select(models.Industry)).all()}
    n = 0
    for entry in INDUSTRIES:
        ind = existing.get(entry["code"])
        if ind is None:
            ind = models.Industry(code=entry["code"])
            db.add(ind)
        ind.name = entry["name"]
        ind.name_ta = entry.get("name_ta")
        ind.name_hi = entry.get("name_hi")
        ind.description = entry.get("description")
        ind.nic_codes = entry.get("nic_codes") or []
        ind.typical_hazards = entry.get("typical_hazards") or []
        ind.question_sets = entry.get("question_sets") or []
        ind.pollution_load_class = entry.get("pollution_load_class")
        ind.source_status = SourceStatus.REQUIRES_VERIFICATION
        ind.is_active = True
        n += 1
    db.flush()
    return n


def seed_portals(db: Session) -> int:
    existing = {p.name: p for p in db.scalars(select(models.GovernmentPortal)).all()}
    n = 0
    for entry in PORTALS:
        portal = existing.get(entry["name"])
        if portal is None:
            portal = models.GovernmentPortal(name=entry["name"])
            db.add(portal)
        portal.department = entry["department"]
        portal.ministry = entry.get("ministry")
        portal.short_name = entry.get("short_name")
        portal.service = entry.get("service")
        portal.services_supported = entry.get("services_supported") or []
        portal.level = Jurisdiction(entry["level"])
        portal.state_code = entry.get("state_code")
        portal.official_url = entry["official_url"]
        portal.description = entry.get("description")
        portal.categories = entry.get("categories") or []
        portal.keywords = entry.get("keywords") or []
        portal.integration_status = entry.get("integration_status", "NOT_CONNECTED")
        portal.verification_status = SourceStatus(entry.get("verification_status", SourceStatus.REQUIRES_VERIFICATION.value))
        portal.is_active = True
        n += 1
    db.flush()
    return n


def seed_government_sources(db: Session) -> int:
    """Register the primary legal sources our catalogue cites."""
    entries = [
        ("India Code — Acts & Rules repository", "https://www.indiacode.nic.in/", "Ministry of Law and Justice", "CENTRAL", "LEGISLATION"),
        ("eGazette of India", "https://egazette.gov.in/", "Directorate of Printing", "CENTRAL", "GAZETTE"),
        ("MoEFCC notifications", "https://moef.gov.in/", "Ministry of Environment, Forest and Climate Change", "CENTRAL", "MINISTRY"),
        ("CPCB guidelines & categorisation", "https://cpcb.nic.in/", "Central Pollution Control Board", "CENTRAL", "REGULATOR"),
        ("Ministry of Labour & Employment", "https://www.labour.gov.in/", "Ministry of Labour and Employment", "CENTRAL", "MINISTRY"),
        ("Ministry of MSME — notifications", "https://msme.gov.in/", "Ministry of Micro, Small & Medium Enterprises", "CENTRAL", "MINISTRY"),
        ("DGFT — Foreign Trade Policy", "https://www.dgft.gov.in/", "Directorate General of Foreign Trade", "CENTRAL", "MINISTRY"),
        ("FSSAI regulations", "https://www.fssai.gov.in/", "Food Safety and Standards Authority of India", "CENTRAL", "REGULATOR"),
        ("CDSCO — Drugs & Cosmetics Rules", "https://cdsco.gov.in/", "Central Drugs Standard Control Organisation", "CENTRAL", "REGULATOR"),
        ("BIS — certification schemes & QCOs", "https://www.bis.gov.in/", "Bureau of Indian Standards", "CENTRAL", "REGULATOR"),
        ("PESO — rules & licensing", "https://peso.gov.in/", "Petroleum and Explosives Safety Organization", "CENTRAL", "REGULATOR"),
        ("CEA — regulations", "https://cea.nic.in/", "Central Electricity Authority", "CENTRAL", "REGULATOR"),
        ("CGWA — groundwater directions", "https://cgwa-noc.gov.in/", "Central Ground Water Authority", "CENTRAL", "REGULATOR"),
        ("EPFO", "https://www.epfindia.gov.in/", "Employees' Provident Fund Organisation", "CENTRAL", "REGULATOR"),
        ("ESIC", "https://www.esic.gov.in/", "Employees' State Insurance Corporation", "CENTRAL", "REGULATOR"),
        ("Startup India (DPIIT)", "https://www.startupindia.gov.in/", "DPIIT, Ministry of Commerce & Industry", "CENTRAL", "MINISTRY"),
        ("MyScheme", "https://www.myscheme.gov.in/", "Government of India", "CENTRAL", "DIRECTORY"),
        ("National Single Window System", "https://www.nsws.gov.in/", "DPIIT", "CENTRAL", "PORTAL"),
        ("PARIVESH", "https://parivesh.nic.in/", "MoEFCC", "CENTRAL", "PORTAL"),
        ("Guidance Tamil Nadu", "https://www.guidancetamilnadu.in/", "Government of Tamil Nadu", "STATE", "PORTAL"),
        ("TNPCB", "https://www.tnpcb.gov.in/", "Tamil Nadu Pollution Control Board", "STATE", "REGULATOR"),
    ]
    existing = {s.name: s for s in db.scalars(select(models.GovernmentSource)).all()}
    n = 0
    for name, url, publisher, level, kind in entries:
        src = existing.get(name)
        if src is None:
            src = models.GovernmentSource(name=name)
            db.add(src)
        src.url = url
        src.publisher = publisher
        src.jurisdiction = Jurisdiction(level)
        src.source_type = kind
        src.verification_status = SourceStatus.REQUIRES_VERIFICATION
        src.confidence = Confidence.REQUIRES_VERIFICATION
        src.is_active = True
        n += 1
    db.flush()
    return n


def seed_knowledge(db: Session) -> int:
    existing = {k.title: k for k in db.scalars(select(models.KnowledgeDocument)).all()}
    n = 0
    for entry in KNOWLEDGE:
        kd = existing.get(entry["title"])
        if kd is None:
            kd = models.KnowledgeDocument(title=entry["title"])
            db.add(kd)
        kd.doc_kind = entry["doc_kind"]
        kd.scope = "GLOBAL"
        kd.publisher = entry["publisher"]
        kd.url = entry.get("url")
        kd.section = entry.get("section")
        kd.language = entry.get("language", "en")
        kd.verification_status = (
            SourceStatus.REQUIRES_VERIFICATION if entry["doc_kind"] == "OFFICIAL_SUMMARY" else SourceStatus.AI_INTERPRETATION
        )
        kd.body = entry["body"]
        kd.content_hash = hashlib.sha256(entry["body"].encode()).hexdigest()
        n += 1
    db.flush()
    # (re)index chunks
    for entry in KNOWLEDGE:
        kd = existing.get(entry["title"])
        if kd is None:
            kd = db.scalars(select(models.KnowledgeDocument).where(models.KnowledgeDocument.title == entry["title"])).first()
        if kd is not None:
            index_knowledge_document(db, kd)
    db.flush()
    return n


def verify_portal(db: Session, portal_id: int, user: models.User) -> models.GovernmentPortal | None:
    """Operator action: mark a portal as verified *now* with a real timestamp."""
    portal = db.get(models.GovernmentPortal, portal_id)
    if portal is None:
        return None
    portal.last_verified_at = datetime.now(timezone.utc).replace(tzinfo=None)
    portal.verification_status = SourceStatus.VERIFIED_GOV_SOURCE
    portal.is_demo = False
    db.commit()
    return portal


def search_portals(db: Session, *, q: str | None = None, level: str | None = None, state_code: str | None = None, category: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
    stmt = select(models.GovernmentPortal).where(models.GovernmentPortal.is_active.is_(True))
    rows = db.scalars(stmt).all()
    ql = (q or "").lower().strip()
    out = []
    for p in rows:
        if level and p.level != level:
            continue
        if state_code and (p.state_code or "").upper() != state_code.upper():
            continue
        if category and category not in (p.categories or []):
            continue
        if ql:
            hay = " ".join(
                [p.name or "", p.short_name or "", p.department or "", p.service or "", p.description or "",
                 " ".join(p.keywords or []), " ".join(p.services_supported or []), p.state_code or ""]
            ).lower()
            if not all(word in hay for word in ql.split()):
                continue
        out.append(
            {
                "id": p.id,
                "name": p.name,
                "short_name": p.short_name,
                "department": p.department,
                "ministry": p.ministry,
                "service": p.service,
                "services_supported": p.services_supported or [],
                "level": p.level.value if p.level else None,
                "state_code": p.state_code,
                "official_url": p.official_url,
                "description": p.description,
                "integration_status": p.integration_status.value if p.integration_status else None,
                "verification_status": p.verification_status.value if p.verification_status else None,
                "last_verified_at": p.last_verified_at.isoformat() if p.last_verified_at else None,
                "is_demo": p.is_demo,
            }
        )
    return out[:limit]


def list_states() -> list[dict[str, str]]:
    return STATES
