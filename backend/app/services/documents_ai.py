"""
Document processing & AI validation (spec §9, §10).

Capabilities, honestly scoped:
 * text extraction for PDF (pypdf) and common text formats — no external OCR
   engine is bundled, so scanned images without a text layer are reported as
   "text could not be extracted" rather than silently passed;
 * deterministic classification against a vocabulary of document types;
 * pattern extraction for identifiers (PAN, GSTIN, CIN, Udyam, dates) and
   comparison against the Master Project Profile;
 * expiry detection and low-quality-scan flags;
 * every finding labelled AI_INTERPRETATION — never "legally valid".
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..enums import (
    AuditResult,
    Confidence,
    DocumentCategory,
    DocumentStatus,
    SourceStatus,
    ValidationSeverity,
)
from .audit import audit_event

log = logging.getLogger("niecp.documents")

# ────────────────────────────────────────────────────────── extraction ──
PAN_RE = re.compile(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b")
GSTIN_RE = re.compile(r"\b([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]{3}[0-9A-Z][0-9A-Z])\b")
CIN_RE = re.compile(r"\b([LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6})\b")
UDYAM_RE = re.compile(r"\b(UDYAM-([A-Z]{2})-\d{2}-\d{7})\b", re.I)
DATE_RE = re.compile(r"\b(\d{1,2}[-/. ]\d{1,2}[-/. ]\d{2,4}|\d{4}[-/.]\d{1,2}[-/.]\d{1,2})\b")

DOC_VOCABULARY: list[tuple[str, str, list[str]]] = [
    ("Sale Deed / Title Document", "LAND", ["sale deed", "title deed", "conveyance deed", "vendor", "purchaser", "consideration"]),
    ("Lease Deed", "LAND", ["lease deed", "lessor", "lessee", "lease period", "rent"]),
    ("Allotment Letter", "LAND", ["allotment", "plot", "sidco", "sipcot", "industrial area", "premium"]),
    ("Patta / Chitta / Revenue Record", "LAND", ["patta", "chitta", "revenue record", "taluk", "village", "survey number"]),
    ("Certificate of Incorporation", "BUSINESS", ["certificate of incorporation", "corporate identity number", "cin", "registrar of companies"]),
    ("GST Registration Certificate", "BUSINESS", ["goods and services tax", "gstin", "certificate of registration", "taxable person"]),
    ("Udyam Registration Certificate", "BUSINESS", ["udyam", "udyog aadhaar", "micro small medium", "msme"]),
    ("PAN Card", "IDENTITY", ["income tax", "permanent account number", "pan"]),
    ("Aadhaar Card", "IDENTITY", ["aadhaar", "unique identification", "uidai"]),
    ("Consent to Establish / Operate", "ENVIRONMENTAL", ["consent to establish", "consent to operate", "water act", "air act", "pollution control board"]),
    ("Hazardous Waste Authorisation", "ENVIRONMENTAL", ["hazardous waste", "authorisation", "hw rules", "form 3"]),
    ("Environmental Clearance", "ENVIRONMENTAL", ["environmental clearance", "eia", "seiaa", "moefcc", "impact assessment"]),
    ("Factory Licence", "SAFETY", ["factory licence", "factories act", "chief inspector of factories", "licence to work a factory"]),
    ("Fire NOC", "SAFETY", ["fire", "no objection", "fire and rescue", "fire safety"]),
    ("Boiler Certificate", "SAFETY", ["boiler", "indian boilers act", "steam", "certificate under"]),
    ("FSSAI Licence", "GOVERNMENT_CERTIFICATE", ["fssai", "food safety", "license", "food business operator"]),
    ("Building Plan Sanction", "LAND", ["building plan", "sanction", "planning permission", "municipal", "corporation"]),
    ("Project Report", "PROJECT_REPORT", ["project report", "promoter", "means of finance", "capacity", "market"]),
    ("Electricity Connection / Tariff Order", "TECHNICAL", ["electricity", "sanction load", "distribution licensee", "tariff", "service connection"]),
    ("Bank Statement / Financial Statement", "FINANCIAL", ["bank", "statement", "balance sheet", "auditor", "financial year"]),
]


def extract_text_from_pdf(data: bytes) -> tuple[str, int]:
    from io import BytesIO

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 — a broken page shouldn't kill extraction
            pages.append("")
    text = "\n".join(pages)
    return text, len(reader.pages)


def extract_text(data: bytes, extension: str) -> tuple[str, str]:
    """Returns (text, engine). Empty text means extraction failed honestly."""
    ext = extension.lower().lstrip(".")
    try:
        if ext == "pdf":
            text, _pages = extract_text_from_pdf(data)
            return text, "pypdf"
        if ext in ("txt", "csv", "xml", "json", "md"):
            return data.decode("utf-8", errors="replace"), "utf8"
        if ext in ("docx",):
            # minimal docx text extraction (word/document.xml)
            import io
            import zipfile
            import xml.etree.ElementTree as ET

            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                with zf.open("word/document.xml") as f:
                    tree = ET.parse(f)
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            paragraphs = []
            for para in tree.getroot().iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
                texts = [t.text or "" for t in para.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")]
                paragraphs.append("".join(texts))
            return "\n".join(paragraphs), "docx-xml"
        if ext in ("jpg", "jpeg", "png", "webp"):
            # No OCR engine bundled: report honestly.
            return "", "image-no-ocr"
    except Exception as exc:  # noqa: BLE001
        log.warning("text extraction failed: %s", exc)
        return "", "failed"
    return "", "unsupported"


# ──────────────────────────────────────────────────── classification ──
def classify(text: str) -> tuple[str, str, float]:
    """Returns (doc_type, category, confidence)."""
    low = text.lower()
    if not low.strip():
        return ("Unknown — no text extracted", "OTHER", 0.0)
    best_type, best_cat, best_score = "Unclassified", "OTHER", 0.0
    for doc_type, cat, keywords in DOC_VOCABULARY:
        hits = sum(1 for k in keywords if k in low)
        if hits:
            score = hits / len(keywords)
            if score > best_score:
                best_type, best_cat, best_score = doc_type, cat, score
    confidence = min(0.95, best_score)
    return best_type, best_cat, confidence


def parse_date(value: str) -> date | None:
    formats = ["%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %m %Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%y"]
    for fmt in formats:
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def extract_fields(text: str) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "pan": PAN_RE.search(text).group(1) if PAN_RE.search(text) else None,
        "gstin": GSTIN_RE.search(text).group(1) if GSTIN_RE.search(text) else None,
        "cin": CIN_RE.search(text).group(1) if CIN_RE.search(text) else None,
        "udyam": UDYAM_RE.search(text).group(1).upper() if UDYAM_RE.search(text) else None,
    }
    dates = [parse_date(m.group(1)) for m in DATE_RE.finditer(text)]
    dates = [d for d in dates if d is not None]
    fields["dates_found"] = [d.isoformat() for d in dates[:10]]
    if dates:
        fields["latest_date"] = max(dates).isoformat()
        fields["earliest_date"] = min(dates).isoformat()
    # expiry-ish phrasing
    expiry = None
    for kw in ("valid till", "valid up to", "valid upto", "valid until", "expiry date", "expires on", "renewal due"):
        idx = low = text.lower().find(kw)
        if idx >= 0:
            window = text[idx: idx + 60]
            m = DATE_RE.search(window)
            if m:
                expiry = parse_date(m.group(1))
                if expiry:
                    break
    fields["expiry_date"] = expiry.isoformat() if expiry else None
    return fields


# ─────────────────────────────────────────────────────── validation ──
def _finding(run_id: str, document: models.Document, key: str, title: str, severity: ValidationSeverity, detail: str, **kw: Any) -> models.DocumentValidation:
    return models.DocumentValidation(
        document_id=document.id,
        project_id=document.project_id,
        check_key=key,
        title=title,
        severity=severity,
        detail=detail,
        source_status=SourceStatus.AI_INTERPRETATION,
        run_id=run_id,
        **kw,
    )


def validate_document(db: Session, document: models.Document, project: models.Project, actor: models.User | None = None) -> list[models.DocumentValidation]:
    """Run the full validation suite and persist findings (spec §10)."""
    run_id = hashlib.sha256(f"{document.id}:{document.updated_at}:{datetime.utcnow().timestamp()}".encode()).hexdigest()[:16]
    for old in db.query(models.DocumentValidation).filter(models.DocumentValidation.document_id == document.id).all():
        db.delete(old)
    db.flush()

    text = document.extracted_text_preview or ""
    findings: list[models.DocumentValidation] = []

    # 1. readability
    if not text.strip():
        findings.append(
            _finding(run_id, document, "readability", "Document readable", ValidationSeverity.ERROR,
                     "No text could be extracted from this file. If it is a scan or photo, upload a clearer copy or a PDF with a text layer. The document is stored but not machine-validated.")
        )
        document.status = DocumentStatus.VALIDATION_REQUIRED
        document.text_extraction_status = "NO_TEXT"
        db.add_all(findings)
        db.commit()
        return findings

    findings.append(
        _finding(run_id, document, "readability", "Document readable", ValidationSeverity.PASS,
                 f"Text extracted ({len(text):,} characters). Machine reading succeeded; interpretation below is AI-generated.")
    )

    # 2. classification
    doc_type, category, conf = classify(text)
    document.ai_document_type = doc_type
    document.ai_category = DocumentCategory(category) if category in DocumentCategory.__members__ else DocumentCategory.OTHER
    document.ai_classification_confidence = conf
    if conf >= 0.3:
        findings.append(
            _finding(run_id, document, "classification", f"Detected document type: {doc_type}", ValidationSeverity.PASS,
                     f"Classified as {doc_type} (category {category}) with {conf:.0%} vocabulary match confidence.",
                     found_value=doc_type)
        )
    else:
        findings.append(
            _finding(run_id, document, "classification", "Document type uncertain", ValidationSeverity.INFO,
                     "The document type could not be determined with confidence. You can set the type manually on the document card.")
        )

    # 3. field extraction + profile comparison
    extracted = extract_fields(text)
    profile = project.profile
    matched_points: list[str] = []
    mismatch_points: list[str] = []

    if profile is not None:
        if extracted.get("pan"):
            if profile.pan and extracted["pan"].upper() == str(profile.pan).upper():
                matched_points.append(f"PAN {extracted['pan']} matches the project profile")
                findings.append(_finding(run_id, document, "pan_match", "PAN matches project profile", ValidationSeverity.PASS,
                                         f"PAN on document ({extracted['pan']}) matches the profile.", expected_value=profile.pan, found_value=extracted['pan']))
            elif profile.pan:
                mismatch_points.append("PAN")
                findings.append(_finding(run_id, document, "pan_match", "PAN mismatch", ValidationSeverity.WARNING,
                                         f"Document shows PAN {extracted['pan']} but the project profile records {profile.pan}. Check whether this document belongs to the same entity.",
                                         expected_value=profile.pan, found_value=extracted['pan']))
            else:
                findings.append(_finding(run_id, document, "pan_found", "PAN found on document", ValidationSeverity.INFO,
                                         f"Document shows PAN {extracted['pan']}. Add it to the project profile so future uploads can be cross-checked.", found_value=extracted['pan']))
        if extracted.get("gstin") and profile.gstin:
            if extracted["gstin"].upper() == str(profile.gstin).upper():
                matched_points.append("GSTIN matches")
            else:
                mismatch_points.append("GSTIN")
                findings.append(_finding(run_id, document, "gstin_match", "GSTIN mismatch", ValidationSeverity.WARNING,
                                         f"Document shows GSTIN {extracted['gstin']} but the profile records {profile.gstin}.",
                                         expected_value=profile.gstin, found_value=extracted['gstin']))
        if extracted.get("udyam") and profile.udyam_number:
            if extracted["udyam"].upper() == str(profile.udyam_number).upper():
                matched_points.append("Udyam number matches")
            else:
                mismatch_points.append("Udyam number")
                findings.append(_finding(run_id, document, "udyam_match", "Udyam number mismatch", ValidationSeverity.WARNING,
                                         f"Document shows {extracted['udyam']} but the profile records {profile.udyam_number}.",
                                         expected_value=profile.udyam_number, found_value=extracted['udyam']))

        # name presence check
        org = (profile.organization_name or "").lower()
        if org and len(org) > 3:
            if org in text.lower():
                matched_points.append("Organization name appears in the document")
            else:
                findings.append(
                    _finding(run_id, document, "name_match", "Organization name not found in document", ValidationSeverity.WARNING,
                             f"“{profile.organization_name}” does not appear in the extracted text. This may be fine (abbreviations, logos as images), but check that the document belongs to this entity.",
                             expected_value=profile.organization_name)
                )

        # address sanity: state/district mention
        state_names = {"TN": ["tamil nadu"], "MH": ["maharashtra"], "KA": ["karnataka"], "GJ": ["gujarat"], "TG": ["telangana"], "AP": ["andhra pradesh"], "UP": ["uttar pradesh"], "DL": ["delhi"], "WB": ["west bengal"], "KL": ["kerala"], "RJ": ["rajasthan"], "PB": ["punjab"], "HR": ["haryana"], "MP": ["madhya pradesh"], "OD": ["odisha"]}
        expected_state = str(profile.state_code or "").upper()
        if expected_state in state_names:
            names = state_names[expected_state]
            if any(n in text.lower() for n in names):
                matched_points.append(f"State ({names[0].title()}) appears in the document")
            else:
                findings.append(
                    _finding(run_id, document, "address_match", "Address cannot be confirmed", ValidationSeverity.INFO,
                             f"The document text does not clearly mention {names[0].title()}. If the address on the document differs from the project site, correct whichever is wrong — authorities routinely reject on address mismatch.",
                             expected_value=names[0].title())
                )

    if matched_points:
        findings.append(_finding(run_id, document, "profile_match", "Profile consistency", ValidationSeverity.PASS,
                                 "; ".join(matched_points) + "."))
    if mismatch_points:
        findings.append(_finding(run_id, document, "profile_mismatch", "Manual verification required", ValidationSeverity.WARNING,
                                 f"Field(s) differ from the project profile: {', '.join(mismatch_points)}. An authority may raise a query on this — reconcile before filing."))

    # 4. expiry
    expiry = extracted.get("expiry_date")
    if expiry:
        exp_date = date.fromisoformat(expiry)
        document.expiry_date = exp_date
        if exp_date < date.today():
            document.status = DocumentStatus.EXPIRED
            findings.append(_finding(run_id, document, "expiry", "Document appears expired", ValidationSeverity.BLOCKING,
                                     f"Expiry date parsed as {expiry}, which is in the past. Operating on an expired certificate is treated as operating without it — renew before filing or recording outcomes.",
                                     found_value=expiry))
        else:
            days = (exp_date - date.today()).days
            sev = ValidationSeverity.WARNING if days < 90 else ValidationSeverity.PASS
            findings.append(_finding(run_id, document, "expiry", "Document validity date found", sev,
                                     f"Expiry/validity parsed as {expiry} ({days} days remaining). Confirm this is the right date — parsing is pattern-based."))

    # 5. low-quality scan detection
    words = len(text.split())
    if words < 40:
        findings.append(
            _finding(run_id, document, "quality", "Low content — possible poor scan", ValidationSeverity.WARNING,
                     f"Only {words} words were extracted. If this is a multi-page document, the scan may be poor quality or the text layer damaged. Please upload a clearer copy.")
        )

    # final status
    if document.status in (DocumentStatus.UPLOADED, DocumentStatus.PROCESSING, DocumentStatus.PROCESSED, DocumentStatus.VALIDATION_REQUIRED):
        document.status = DocumentStatus.PROCESSED if not any(f.severity in (ValidationSeverity.BLOCKING, ValidationSeverity.ERROR) for f in findings) else DocumentStatus.VALIDATION_REQUIRED
    document.text_extraction_status = "OK"
    db.add_all(findings)
    db.flush()

    audit_event(
        db,
        action="document.validated",
        action_category="DOCUMENT",
        user_id=actor.id if actor else None,
        project_id=project.id,
        resource_type="document",
        resource_id=str(document.id),
        result=AuditResult.SUCCESS,
        details={"findings": len(findings), "doc_type": doc_type, "blocking": sum(1 for f in findings if f.severity == ValidationSeverity.BLOCKING)},
        agent="DOCUMENT",
    )
    return findings


def validation_summary(db: Session, document: models.Document) -> dict[str, Any]:
    findings = db.query(models.DocumentValidation).filter(models.DocumentValidation.document_id == document.id).order_by(models.DocumentValidation.id).all()
    return {
        "run_id": findings[0].run_id if findings else None,
        "findings": [
            {
                "key": f.check_key,
                "title": f.title,
                "severity": f.severity.value,
                "detail": f.detail,
                "expected": f.expected_value,
                "found": f.found_value,
                "source_status": f.source_status.value,
            }
            for f in findings
        ],
        "counts": {
            "pass": sum(1 for f in findings if f.severity == ValidationSeverity.PASS),
            "info": sum(1 for f in findings if f.severity == ValidationSeverity.INFO),
            "warning": sum(1 for f in findings if f.severity == ValidationSeverity.WARNING),
            "error": sum(1 for f in findings if f.severity in (ValidationSeverity.ERROR, ValidationSeverity.BLOCKING)),
        },
        "disclaimer": "These findings are AI interpretations of the uploaded file. They are not a legal opinion and do not establish that a document is genuine or that an authority will accept it — only the issuing authority can do that.",
    }
