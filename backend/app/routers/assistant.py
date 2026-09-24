"""AI assistant chat, conversations, voice session logging (spec §26-§28, §50)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..ai import assistant as assistant_service
from ..ai import llm
from ..database import get_db
from ..enums import AIMessageRole, SourceStatus, VoiceState
from ..services.audit import audit_event
from ..services.auth_service import get_current_user, project_access, request_id

router = APIRouter(tags=["assistant"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    project_id: int | None = None
    conversation_id: int | None = None
    channel: str = "chat"
    language: str = "en"


class VoiceLogRequest(BaseModel):
    state: VoiceState
    project_id: int | None = None
    transcript: str | None = None
    intent: str | None = None
    sensitive_action: bool = False
    confirmation_required: bool = False
    error_code: str | None = None
    stt_engine: str | None = None
    tts_engine: str | None = None
    duration_ms: int | None = None
    language: str = "en"


@router.post("/assistant/chat")
def chat(body: ChatRequest, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    project = None
    if body.project_id is not None:
        project = project_access(db, user, body.project_id)
    conversation = None
    if body.conversation_id:
        conversation = db.get(models.AIConversation, body.conversation_id)
        if conversation is None or conversation.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found.")
    else:
        conversation = models.AIConversation(user_id=user.id, project_id=project.id if project else None,
                                             channel=body.channel, language=body.language)
        db.add(conversation)
        db.flush()
    try:
        result = assistant_service.answer(
            db, project, user, body.message, channel=body.channel, language=body.language,
            conversation=conversation, request_id=request_id(request),
        )
    except Exception:
        db.rollback()
        # honest error state (spec §44): AI assistance unavailable, data safe
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "AI assistance is temporarily unavailable. Your saved project information remains available — please try again shortly.")
    structured = result.to_structured()
    return {"conversation_id": conversation.id, **structured}


class AIAliasRequest(BaseModel):
    """Master Upgrade Prompt §36 — spec-shaped request envelope."""

    message: str = Field(min_length=1, max_length=4000)
    projectId: int | None = None
    project_id: int | None = None  # snake_case accepted too
    context: dict[str, Any] | None = None
    language: str = "en"


_ACTION_ROUTES: list[tuple[str, str, str]] = [
    ("PENDING_APPROVALS", "VIEW APPROVAL CHECKLIST", "/projects/{pid}/approvals"),
    ("MISSING_DOCUMENTS", "CHECK DOCUMENTS", "/projects/{pid}/documents"),
    ("CRITICAL_PATH", "VIEW CRITICAL PATH", "/projects/{pid}/approvals"),
    ("OPEN_PORTAL", "GOVERNMENT PORTALS", "/government-portals"),
    ("SCHEMES", "VIEW SCHEMES", "/projects/{pid}/schemes"),
    ("CALENDAR", "VIEW CALENDAR", "/projects/{pid}/calendar"),
    ("QUERIES", "VIEW QUERIES", "/projects/{pid}/queries"),
    ("APPLICATIONS", "VIEW APPLICATIONS", "/projects/{pid}/applications"),
    ("COMPLIANCE_TASKS", "VIEW TODAY'S TASKS", "/projects/{pid}/compliance"),
    ("NEXT_STEP", "OPEN DASHBOARD", "/dashboard"),
]


def _actions_for(intent: str, project_id: int | None) -> list[dict[str, str]]:
    """UI affordances the voice/text answer can offer (spec §56)."""
    actions: list[dict[str, str]] = []
    for route_intent, label, template in _ACTION_ROUTES:
        if route_intent == intent or (intent in ("GENERAL", "HELP", "UNKNOWN") and len(actions) < 3):
            if "{pid}" in template and project_id is None:
                continue
            actions.append({"action": route_intent, "label": label, "route": template.replace("{pid}", str(project_id))})
        if len(actions) >= 5:
            break
    if project_id is not None and all(a["action"] != "NEXT_STEP" for a in actions):
        actions.append({"action": "NEXT_STEP", "label": "ASK ANOTHER QUESTION", "route": ""})
    return actions


@router.post("/ai/assistant")
def ai_assistant(body: AIAliasRequest, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """Spec-shaped alias over the existing assistant brain (one AI, many
    envelopes). Uses actual project information whenever a project id is given
    (spec §37); the LLM never overrides deterministic rules (spec §25)."""
    project = None
    pid = body.projectId if body.projectId is not None else body.project_id
    if pid is not None:
        project = project_access(db, user, pid)
    try:
        result = assistant_service.answer(
            db, project, user, body.message, channel="voice", language=body.language,
            conversation=None, request_id=request_id(request),
        )
    except Exception:
        db.rollback()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "AI assistance is temporarily unavailable. Your saved project information remains available — please try again shortly.")
    structured = result.to_structured()
    return {
        "message": structured["answer"],
        "intent": structured["intent"],
        "sources": structured["sources"],
        "actions": _actions_for(structured["intent"], project.id if project else None),
        "why": structured["why"],
        "what_you_need": structured["what_you_need"],
        "next_step": structured["next_step"],
        "requires_confirmation": structured["requires_confirmation"],
        "status": "success",
        "used_llm": structured["used_llm"],
    }


@router.get("/assistant/conversations")
def conversations(project_id: int | None = None, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    stmt = select(models.AIConversation).where(models.AIConversation.user_id == user.id, models.AIConversation.archived_at.is_(None))
    if project_id:
        stmt = stmt.where(models.AIConversation.project_id == project_id)
    rows = db.scalars(stmt.order_by(models.AIConversation.updated_at.desc()).limit(50)).all()
    return {"conversations": [
        {"id": c.id, "title": c.title, "project_id": c.project_id, "channel": c.channel,
         "language": c.language, "message_count": c.message_count, "is_pinned": c.is_pinned,
         "updated_at": c.updated_at.isoformat() if c.updated_at else None}
        for c in rows
    ]}


@router.get("/assistant/conversations/{conversation_id}")
def conversation_detail(conversation_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    conversation = db.get(models.AIConversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found.")
    return {
        "id": conversation.id,
        "title": conversation.title,
        "project_id": conversation.project_id,
        "context_snapshot": conversation.context_snapshot or {},
        "messages": [
            {"id": m.id, "role": m.role.value, "content": m.content, "structured": m.structured or {},
             "citations": m.citations or [], "agent": m.agent.value if m.agent else None,
             "created_at": m.created_at.isoformat() if m.created_at else None, "spoken": m.spoken}
            for m in conversation.messages
        ],
    }


@router.delete("/assistant/conversations/{conversation_id}")
def delete_conversation(conversation_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    conversation = db.get(models.AIConversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found.")
    conversation.archived_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


@router.get("/assistant/capabilities")
def capabilities() -> dict[str, Any]:
    return {
        "llm": llm.llm_status(),
        "tools": [
            {"name": "rule_engine", "description": "Deterministic approval applicability from your project profile"},
            {"name": "readiness", "description": "Preparation score with component explanations"},
            {"name": "documents", "description": "Your actual document inventory and gaps"},
            {"name": "schemes", "description": "Documented scheme criteria matching"},
            {"name": "calendar", "description": "Renewals, deadlines, queries and inspections"},
            {"name": "retrieval", "description": "Grounded answers from the curated knowledge corpus with citations"},
        ],
        "commands": [i for i, _ in assistant_service.INTENT_PATTERNS],
        "sensitive_actions_require_confirmation": True,
        "languages": ["en", "ta", "hi"],
        "note": "The assistant answers from your project data and the curated corpus. It never executes a sensitive action from voice or chat alone.",
    }


@router.post("/assistant/voice/log")
def voice_log(body: VoiceLogRequest, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    session = models.VoiceSession(
        user_id=user.id, project_id=body.project_id, state=body.state, language=body.language,
        transcript=body.transcript, intent=body.intent, sensitive_action=body.sensitive_action,
        confirmation_required=body.confirmation_required, error_code=body.error_code,
        stt_engine=body.stt_engine, tts_engine=body.tts_engine, duration_ms=body.duration_ms,
        started_at=datetime.utcnow(), ended_at=datetime.utcnow(),
    )
    db.add(session)
    if body.transcript and body.intent:
        audit_event(db, action="voice.command", action_category="VOICE", user_id=user.id,
                    project_id=body.project_id, resource_type="voice_session", resource_id=str(session.id),
                    details={"intent": body.intent, "sensitive": body.sensitive_action}, commit=True)
    db.commit()
    return {"ok": True, "session_id": session.id}


class VoiceConfirmationRequest(BaseModel):
    session_id: int | None = None
    action: str
    approved: bool


@router.post("/assistant/voice/confirmation")
def voice_confirmation(body: VoiceConfirmationRequest, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    """Record the user's explicit confirm/cancel decision for a sensitive voice action."""
    if body.session_id:
        session = db.get(models.VoiceSession, body.session_id)
        if session is not None and session.user_id == user.id:
            session.confirmation_result = "APPROVED" if body.approved else "CANCELLED"
            session.confirmation_required = False
    audit_event(db, action="voice.confirmation", action_category="VOICE", user_id=user.id,
                resource_type="voice_action", resource_id=str(body.session_id),
                details={"action": body.action, "approved": body.approved},
                is_security_event=True, commit=True)
    return {"ok": True, "recorded": body.action, "approved": body.approved}
