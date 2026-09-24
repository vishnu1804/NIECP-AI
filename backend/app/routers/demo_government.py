"""INTERNAL NIECP demo government endpoints (Master Upgrade Prompt §6, §7, §8).

These are NIECP-AI's own demonstration endpoints. They are NOT government
endpoints, never call a government system, and return only synthetic data.
Every response carries the demo metadata block:

    environment=DEMO · data_source=SYNTHETIC · government_api=NOT_CONNECTED ·
    authorization_status=NOT_AUTHORIZED · live=false
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..enums import ApplicationStatus
from ..services import demo_government
from ..services import next_action as next_action_service
from ..services.auth_service import get_current_user, project_access

router = APIRouter(prefix="/demo/government", tags=["demo-government"])


def _gate_demo() -> None:
    ok, reason = demo_government.demo_available()
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, reason or "Demo workflows are unavailable.")


def _get_application(db: Session, user: models.User, application_id: int) -> tuple[models.Application, models.Project]:
    application = db.get(models.Application, application_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found.")
    project = project_access(db, user, application.project_id)
    return application, project


class DemoSubmit(BaseModel):
    project_id: int
    application_id: int
    demo_confirmation: bool = Field(description="Must be true — confirms the user understands this is the NIECP demo environment using synthetic data.")


class DemoResponse(BaseModel):
    query_id: int
    response_text: str = Field(min_length=5, max_length=8000)
    confirm_response_submission: bool = Field(description="Must be true — confirms the user wants this response filed in the demo environment.")


@router.get("/approvals")
def demo_approvals(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """Approvals in this project that can be exercised in the demo environment."""
    _gate_demo()
    project = project_access(db, user, project_id)
    rows = db.scalars(
        select(models.ProjectApproval).where(
            models.ProjectApproval.project_id == project.id,
            models.ProjectApproval.user_dismissed.is_(False),
        )
    ).all()
    return {
        "demo": dict(demo_government.METADATA),
        "project_id": project.id,
        "approvals": [
            {
                "project_approval_id": pa.id,
                "code": pa.template_code,
                "name": pa.name,
                "authority": pa.authority,
                "category": pa.category,
                "applicability": pa.applicability.value if pa.applicability else None,
                "node_state": pa.node_state,
                "demo_eligible": pa.applicability in ("APPLIES", "LIKELY", "CONDITIONAL", "UNKNOWN"),
            }
            for pa in rows
        ],
        "notice": demo_government.NOTICE,
    }


@router.post("/applications", status_code=status.HTTP_201_CREATED)
def demo_submit(body: DemoSubmit, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """Submit an application into the DEMO environment (synthetic).

    Gates: application prepared → user confirmed the preparation package →
    explicit demo confirmation ("…synthetic data"). NIECP never auto-submits."""
    _gate_demo()
    project = project_access(db, user, body.project_id)
    application = db.get(models.Application, body.application_id)
    if application is None or application.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found in this project.")
    if application.is_demo and application.official_reference:
        raise HTTPException(status.HTTP_409_CONFLICT, f"This application is already in the demo environment as {application.official_reference}.")
    if application.prepared_at is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Prepare the application package first (Applications → Prepare).")
    if application.user_confirmed_at is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Confirm the preparation package first — submission (even to the demo environment) requires your explicit confirmation.")
    if not body.demo_confirmation:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Demo submission requires your explicit confirmation that you understand this is the NIECP demonstration environment using synthetic data — not a government system.",
        )
    # readiness display: report blockers honestly without fabricating an outcome
    blockers = demo_government._missing_blockers(application)
    result = demo_government.submit(db, application=application, user=user, project=project)
    result["readiness_warnings"] = blockers
    result["readiness_note"] = (
        "The demo environment accepts the application regardless of readiness. In a real filing these gaps would likely trigger a deficiency query."
        if blockers else None
    )
    return result


@router.get("/applications/{application_id}")
def demo_application(application_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    _gate_demo()
    application, _ = _get_application(db, user, application_id)
    if not application.is_demo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This application is not in the demo environment.")
    return demo_government.demo_payload(db, application)


@router.get("/applications/{application_id}/status")
def demo_status(application_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """Current demo status. Automatic transitions advance after the simulated
    review dwell; the query stage always waits for the user."""
    _gate_demo()
    application, _ = _get_application(db, user, application_id)
    if not application.is_demo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This application is not in the demo environment.")
    demo_government._auto_advance(db, application, user, demo_government.utcnow())
    db.commit()
    return demo_government.demo_payload(db, application)


@router.post("/applications/{application_id}/advance")
def demo_advance(application_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """DEMO CONTROL — force the next automatic transition (audited)."""
    _gate_demo()
    application, _ = _get_application(db, user, application_id)
    if not application.is_demo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This application is not in the demo environment.")
    new_status = demo_government.advance(db, application, user)
    db.commit()
    return {**demo_government.demo_payload(db, application), "advanced_to": new_status}


@router.get("/applications/{application_id}/queries")
def demo_queries(application_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    _gate_demo()
    application, _ = _get_application(db, user, application_id)
    if not application.is_demo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This application is not in the demo environment.")
    queries = [
        {
            "id": q.id, "reference": q.reference_number, "status": q.status.value,
            "query_text": q.query_text, "deadline": q.deadline.isoformat() if q.deadline else None,
            "required_documents": q.required_documents or [],
            "response_text": q.response_text, "responded_at": q.responded_at.isoformat() if q.responded_at else None,
            "translator": q.translator or None, "is_demo": True,
        }
        for q in application.queries
    ]
    return {"demo": dict(demo_government.METADATA), "application_reference": application.official_reference, "queries": queries, "notice": demo_government.NOTICE}


@router.post("/applications/{application_id}/response")
def demo_respond(application_id: int, body: DemoResponse, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """File a response to the synthetic query in the demo environment."""
    _gate_demo()
    application, _ = _get_application(db, user, application_id)
    if not application.is_demo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This application is not in the demo environment.")
    if application.status != ApplicationStatus.QUERY_RAISED:
        raise HTTPException(status.HTTP_409_CONFLICT, f"The demo application is currently {application.status.value}; a response can be filed only when a query is open (QUERY_RAISED).")
    if not body.confirm_response_submission:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Filing the response requires your explicit confirmation (even in the demo environment).")
    query = db.get(models.GovernmentQuery, body.query_id)
    if query is None or query.application_id != application.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Query not found on this demo application.")
    result = demo_government.respond(db, application=application, query=query, response_text=body.response_text.strip(), user=user)
    db.commit()
    return {**result, "application": demo_government.demo_payload(db, application)}


@router.get("/documents/{document_id}")
def demo_document_receipt(document_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """The demo authority's synthetic receipt for an uploaded document."""
    _gate_demo()
    document = db.get(models.Document, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found.")
    project = project_access(db, user, document.project_id)
    receipt = {
        "demo": dict(demo_government.METADATA),
        "document_id": document.id,
        "filename": document.original_filename or document.title,
        "title": document.title,
        "classification": document.ai_document_type,
        "classification_confidence": document.ai_classification_confidence,
        "sha256": document.sha256,
        "receipt_reference": f"DEMO-RCPT-{document.id:06d}",
        "received_by": "NIECP Demo Government (synthetic)",
        "received_at": demo_government.utcnow().isoformat(),
        "synthetic_acknowledgement": "The demo environment acknowledges the document for demonstration purposes only. No government system received this document.",
        "notice": demo_government.NOTICE,
    }
    return receipt
