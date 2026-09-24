"""Document management + AI validation (spec §9, §10)."""
from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..database import get_db
from ..enums import (
    AuditResult,
    DocumentCategory,
    DocumentStatus,
    SourceStatus,
    ValidationSeverity,
)
from ..services import documents_ai
from ..services.audit import audit_event
from ..services.auth_service import client_ip, get_current_user, project_access, request_id, user_agent

router = APIRouter(tags=["documents"])

BLOCKED_PATTERNS = re.compile(r"\.(exe|bat|cmd|sh|js|vbs|ps1|dll|msi|scr)$", re.I)


def _safe_storage_path(project_id: int, stored_name: str) -> str:
    base = os.path.join(settings.storage_dir, "documents", str(project_id))
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, stored_name)


@router.get("/projects/{project_id}/documents")
def list_documents(
    project_id: int,
    category: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    rows = db.scalars(select(models.Document).where(models.Document.project_id == project.id).order_by(models.Document.created_at.desc())).all()
    ql = (q or "").lower()
    out = []
    for d in rows:
        if category and (d.category.value if d.category else None) != category:
            continue
        if ql and ql not in d.title.lower() and ql not in (d.ai_document_type or "").lower() and ql not in d.original_filename.lower():
            continue
        out.append(_document_payload(db, d))
    cats = sorted({(d.category.value if d.category else "OTHER") for d in rows})
    return {"documents": out, "categories": cats}


def _document_payload(db: Session, d: models.Document) -> dict[str, Any]:
    validation = documents_ai.validation_summary(db, d) if d.id else {"findings": [], "counts": {}}
    has_file = d.stored_filename != "demo-no-file.bin" and os.path.exists(_safe_storage_path(d.project_id, d.stored_filename))
    return {
        "id": d.id,
        "title": d.title,
        "original_filename": d.original_filename,
        "category": d.category.value if d.category else None,
        "ai_category": d.ai_category.value if d.ai_category else None,
        "ai_document_type": d.ai_document_type,
        "ai_classification_confidence": d.ai_classification_confidence,
        "status": d.status.value if d.status else None,
        "mime_type": d.mime_type,
        "extension": d.extension,
        "size_bytes": d.size_bytes,
        "sha256": d.sha256[:16] if d.sha256 and d.sha256 != "demo" else None,
        "page_count": d.page_count,
        "current_version": d.current_version,
        "expiry_date": d.expiry_date.isoformat() if d.expiry_date else None,
        "issue_date": d.issue_date.isoformat() if d.issue_date else None,
        "issuing_authority": d.issuing_authority,
        "document_number": d.document_number,
        "verification_status": d.verification_status.value if d.verification_status else None,
        "linked_approval_codes": d.linked_approval_codes or [],
        "notes": d.notes,
        "is_demo": d.is_demo,
        "has_file": has_file,
        "text_extraction_status": d.text_extraction_status,
        "text_preview": (d.extracted_text_preview or "")[:600],
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "validation": validation,
    }


class DocumentMeta(BaseModel):
    title: str | None = None
    category: str | None = None
    expiry_date: str | None = None
    issue_date: str | None = None
    issuing_authority: str | None = None
    document_number: str | None = None
    notes: str | None = None
    linked_approval_codes: list[str] | None = None


@router.post("/projects/{project_id}/documents", status_code=status.HTTP_201_CREATED)
def upload_document(
    project_id: int,
    request: Request,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    category: str | None = Form(default=None),
    expiry_date: str | None = Form(default=None),
    issue_date: str | None = Form(default=None),
    issuing_authority: str | None = Form(default=None),
    document_number: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    original = file.filename or "document"
    ext = os.path.splitext(original)[1].lower() or ""
    if BLOCKED_PATTERNS.search(ext):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "This file type is not allowed for security reasons.")
    if ext and ext not in settings.allowed_extensions:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"File type {ext} is not accepted. Allowed: {', '.join(sorted(settings.allowed_extensions))}")
    data = file.file.read()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"File exceeds the {settings.max_upload_mb} MB limit.")
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The uploaded file is empty.")

    stored = f"{uuid.uuid4().hex}{ext or '.bin'}"
    path = _safe_storage_path(project.id, stored)
    with open(path, "wb") as fh:
        fh.write(data)
    sha = hashlib.sha256(data).hexdigest()

    # duplicate detection
    dup = db.scalars(select(models.Document).where(models.Document.project_id == project.id, models.Document.sha256 == sha)).first()

    doc_category = DocumentCategory.OTHER
    if category:
        try:
            doc_category = DocumentCategory(category)
        except ValueError:
            pass

    document = models.Document(
        project_id=project.id,
        organization_id=project.organization_id,
        uploaded_by=user.id,
        title=(title or os.path.splitext(original)[0])[:300],
        original_filename=original[:300],
        stored_filename=stored,
        category=doc_category,
        status=DocumentStatus.PROCESSING,
        mime_type=file.content_type,
        extension=ext or None,
        size_bytes=len(data),
        sha256=sha,
    )
    for attr_name, raw in (("expiry_date", expiry_date), ("issue_date", issue_date)):
        if raw:
            try:
                setattr(document, attr_name, date.fromisoformat(raw))
            except ValueError:
                pass
    document.issuing_authority = issuing_authority
    document.document_number = document_number
    document.notes = notes
    db.add(document)
    db.flush()
    db.add(models.DocumentVersion(document_id=document.id, version=1, stored_filename=stored,
                                  size_bytes=len(data), sha256=sha, uploaded_by=user.id, is_current=True,
                                  change_reason="Initial upload"))
    audit_event(db, action="document.upload", action_category="DOCUMENT", user_id=user.id, project_id=project.id,
                resource_type="document", resource_id=str(document.id),
                details={"filename": original, "size": len(data), "duplicate_of": dup.id if dup else None},
                ip_address=client_ip(request), commit=False)

    # AI processing pipeline
    text, engine = documents_ai.extract_text(data, ext or "")
    document.extracted_text_preview = text[:20000] if text else None
    document.ocr_engine = engine
    if dup is not None:
        document.notes = ((document.notes or "") + f" | Duplicate of document #{dup.id} (identical content hash).").strip(" |")
    findings = documents_ai.validate_document(db, document, project, actor=user)
    db.commit()
    return {"ok": True, "document": _document_payload(db, document)}


@router.get("/projects/{project_id}/documents/{document_id}")
def get_document(project_id: int, document_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    document = db.get(models.Document, document_id)
    if document is None or document.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found.")
    payload = _document_payload(db, document)
    payload["versions"] = [
        {"version": v.version, "size_bytes": v.size_bytes, "sha256": v.sha256[:16], "change_reason": v.change_reason,
         "uploaded_at": v.created_at.isoformat() if v.created_at else None, "is_current": v.is_current}
        for v in sorted(document.versions, key=lambda x: x.version, reverse=True)
    ]
    return payload


@router.get("/projects/{project_id}/documents/{document_id}/download")
def download_document(project_id: int, document_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    project = project_access(db, user, project_id)
    document = db.get(models.Document, document_id)
    if document is None or document.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found.")
    path = _safe_storage_path(project.id, document.stored_filename)
    if document.stored_filename == "demo-no-file.bin" or not os.path.exists(path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No file is attached to this document record (demo metadata entry).")
    audit_event(db, action="document.download", action_category="DOCUMENT", user_id=user.id, project_id=project.id,
                resource_type="document", resource_id=str(document.id), commit=True)
    return FileResponse(path, media_type=document.mime_type or "application/octet-stream", filename=document.original_filename)


@router.patch("/projects/{project_id}/documents/{document_id}")
def update_document(project_id: int, document_id: int, body: DocumentMeta, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    document = db.get(models.Document, document_id)
    if document is None or document.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found.")
    if body.title is not None:
        document.title = body.title.strip()[:300]
    if body.category is not None:
        try:
            document.category = DocumentCategory(body.category)
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown category {body.category}")
    for attr_name in ("expiry_date", "issue_date"):
        raw = getattr(body, attr_name)
        if raw:
            try:
                setattr(document, attr_name, date.fromisoformat(raw))
            except ValueError:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Invalid date for {attr_name}")
    if body.issuing_authority is not None:
        document.issuing_authority = body.issuing_authority
    if body.document_number is not None:
        document.document_number = body.document_number
    if body.notes is not None:
        document.notes = body.notes
    if body.linked_approval_codes is not None:
        document.linked_approval_codes = body.linked_approval_codes
    audit_event(db, action="document.update", action_category="DOCUMENT", user_id=user.id, project_id=project.id,
                resource_type="document", resource_id=str(document.id), commit=True)
    return {"ok": True, "document": _document_payload(db, document)}


@router.post("/projects/{project_id}/documents/{document_id}/validate")
def revalidate_document(project_id: int, document_id: int, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    document = db.get(models.Document, document_id)
    if document is None or document.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found.")
    findings = documents_ai.validate_document(db, document, project, actor=user)
    db.commit()
    return {"ok": True, "document": _document_payload(db, document)}


@router.delete("/projects/{project_id}/documents/{document_id}")
def delete_document(project_id: int, document_id: int, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_access(db, user, project_id)
    document = db.get(models.Document, document_id)
    if document is None or document.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found.")
    audit_event(db, action="document.delete", action_category="DOCUMENT", user_id=user.id, project_id=project.id,
                resource_type="document", resource_id=str(document.id),
                before={"title": document.title, "filename": document.original_filename},
                ip_address=client_ip(request), commit=False)
    path = _safe_storage_path(project.id, document.stored_filename)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass
    db.delete(document)
    db.commit()
    return {"ok": True, "deleted": document_id}
