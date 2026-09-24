"""Audit logging (spec §38). Every important event lands here."""
from __future__ import annotations

import datetime

import logging
from typing import Any

from sqlalchemy.orm import Session

from ..enums import AuditResult
from ..models import AuditLog
from ..models_mixins import utcnow

log = logging.getLogger("niecp.audit")


def audit_event(
    db: Session,
    *,
    action: str,
    action_category: str = "GENERAL",
    user_id: int | None = None,
    user_email: str | None = None,
    project_id: int | None = None,
    organization_id: int | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    result: AuditResult = AuditResult.SUCCESS,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
    correlation_id: str | None = None,
    integration_mode: str | None = None,
    provider: str | None = None,
    details: dict[str, Any] | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    agent: str | None = None,
    is_security_event: bool = False,
    commit: bool = False,
) -> AuditLog:
    entry = AuditLog(
        user_id=user_id,
        user_email=user_email,
        action=action[:96],
        action_category=action_category[:48],
        project_id=project_id,
        organization_id=organization_id,
        resource_type=resource_type[:64] if resource_type else None,
        resource_id=str(resource_id)[:64] if resource_id is not None else None,
        result=result,
        ip_address=ip_address,
        user_agent=user_agent[:400] if user_agent else None,
        request_id=request_id,
        correlation_id=correlation_id,
        integration_mode=integration_mode[:32] if integration_mode else None,
        provider=provider[:96] if provider else None,
        details=details or {},
        before=before or {},
        after=after or {},
        agent=agent,
        is_security_event=is_security_event,
    )
    db.add(entry)
    try:
        db.flush()
    except Exception:  # pragma: no cover — audit must never break the request
        db.rollback()
        log.exception("failed to persist audit entry for %s", action)
        raise
    if commit:
        db.commit()
    return entry


def audit_login(db: Session, user, *, success: bool, ip: str | None, user_agent: str | None, reason: str | None = None) -> None:
    audit_event(
        db,
        action="auth.login",
        action_category="AUTH",
        user_id=user.id if user else None,
        user_email=user.email if user else None,
        result=AuditResult.SUCCESS if success else AuditResult.FAILURE,
        ip_address=ip,
        user_agent=user_agent,
        details={"reason": reason} if reason else {},
        is_security_event=not success,
        commit=True,
    )


def audit_permission_change(db: Session, actor, organization_id: int, target_user_id: int, change: dict) -> None:
    audit_event(
        db,
        action="org.permission.change",
        action_category="RBAC",
        user_id=actor.id,
        user_email=actor.email,
        organization_id=organization_id,
        resource_type="organization_member",
        resource_id=str(target_user_id),
        after=change,
        commit=True,
    )


def audit_confirmation(
    db: Session,
    user,
    project_id: int | None,
    what: str,
    resource_type: str,
    resource_id: str,
    confirmation_text: str,
    request_id: str | None = None,
) -> None:
    """Record an explicit user confirmation (spec §38: user confirmations)."""
    audit_event(
        db,
        action="user.confirmation",
        action_category="CONFIRMATION",
        user_id=user.id,
        user_email=user.email,
        project_id=project_id,
        resource_type=resource_type,
        resource_id=resource_id,
        details={"what": what, "confirmation_text": confirmation_text},
        request_id=request_id,
        commit=True,
    )


def prune_old_entries(db: Session, retention_days: int) -> int:
    cutoff = utcnow() - datetime.timedelta(days=retention_days)
    deleted = db.query(AuditLog).filter(AuditLog.created_at < cutoff).delete(synchronize_session=False)
    db.commit()
    return deleted
