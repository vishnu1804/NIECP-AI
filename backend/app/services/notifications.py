"""
Notification service (spec §34) + renewal engine (spec §22) + email.

Email honesty: unless SMTP is configured (NIECP_SMTP_HOST + NIECP_EMAIL_ENABLED),
email status is reported as NOT_CONFIGURED — never as "sent".
"""
from __future__ import annotations

import logging
import smtplib
from datetime import date, datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..enums import (
    AuditResult,
    EmailDeliveryStatus,
    NotificationChannel,
    NotificationType,
    RenewalStatus,
)
from .audit import audit_event

log = logging.getLogger("niecp.notifications")


def notify(
    db: Session,
    *,
    user_id: int | None,
    project_id: int | None = None,
    organization_id: int | None = None,
    notification_type: NotificationType,
    title: str,
    body: str | None = None,
    severity: str = "INFO",
    link: str | None = None,
    payload: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
    email: bool = False,
    commit: bool = True,
) -> models.Notification | None:
    if dedupe_key:
        existing = db.scalars(
            select(models.Notification).where(
                models.Notification.dedupe_key == dedupe_key,
                models.Notification.read_at.is_(None),
            )
        ).first()
        if existing is not None:
            return existing
    notification = models.Notification(
        user_id=user_id,
        project_id=project_id,
        organization_id=organization_id,
        channel=NotificationChannel.IN_APP,
        notification_type=notification_type,
        title=title[:300],
        body=body,
        severity=severity,
        link=link,
        payload=payload or {},
        dedupe_key=dedupe_key[:160] if dedupe_key else None,
        email_status=EmailDeliveryStatus.NOT_CONFIGURED,
    )
    db.add(notification)
    db.flush()
    if email:
        _dispatch_email(db, notification, commit=False)
    if commit:
        db.commit()
    return notification


def _dispatch_email(db: Session, notification: models.Notification, commit: bool = True) -> None:
    if not (settings.email_enabled and settings.smtp_host):
        notification.email_status = EmailDeliveryStatus.NOT_CONFIGURED
        notification.email_error = "SMTP is not configured in this deployment (NIECP_EMAIL_ENABLED=0). The in-app notification is available."
        if commit:
            db.commit()
        return
    user = db.get(models.User, notification.user_id) if notification.user_id else None
    if user is None or not user.email:
        notification.email_status = EmailDeliveryStatus.FAILED
        notification.email_error = "No recipient email available."
        if commit:
            db.commit()
        return
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = notification.title
        msg["From"] = settings.smtp_from
        msg["To"] = user.email
        msg.attach(MIMEText(notification.body or notification.title, "plain", "utf-8"))
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            if settings.smtp_user:
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_from, [user.email], msg.as_string())
        notification.email_status = EmailDeliveryStatus.SENT
    except (smtplib.SMTPException, OSError) as exc:
        notification.email_status = EmailDeliveryStatus.FAILED
        notification.email_error = str(exc)
        log.warning("email dispatch failed: %s", exc)
    if commit:
        db.commit()


# ═══════════════════════════════════════════════════ RENEWAL ENGINE ══
def update_renewal_statuses(db: Session) -> int:
    """Recompute renewal statuses from due dates (background job / on access)."""
    today = date.today()
    renewals = db.scalars(select(models.Renewal).where(models.Renewal.status != RenewalStatus.RENEWED)).all()
    changed = 0
    for r in renewals:
        if r.due_date is None:
            continue
        days = (r.due_date - today).days
        new_status = (
            RenewalStatus.OVERDUE if days < 0
            else RenewalStatus.DUE_SOON if days <= 30
            else RenewalStatus.UPCOMING
        )
        if new_status != r.status:
            r.status = new_status
            changed += 1
    if changed:
        db.commit()
    return changed


def generate_renewal_reminders(db: Session) -> int:
    """Create reminder notifications at configured lead times (90/60/30/7)."""
    today = date.today()
    created = 0
    renewals = db.scalars(select(models.Renewal).where(models.Renewal.status != RenewalStatus.RENEWED)).all()
    for r in renewals:
        if r.due_date is None:
            continue
        days_left = (r.due_date - today).days
        for lead in sorted(r.reminder_days or [90, 60, 30, 7], reverse=True):
            key = f"renewal:{r.id}:{lead}"
            if days_left <= lead and key not in (r.reminders_sent or []):
                notified = notify(
                    db,
                    user_id=None,
                    project_id=r.project_id,
                    organization_id=r.organization_id,
                    notification_type=NotificationType.RENEWAL_APPROACHING,
                    title=f"Renewal {'overdue' if days_left < 0 else f'due in {days_left} days'}: {r.title}",
                    body=f"{r.title} is due on {r.due_date.isoformat()}. Renewals commonly need fresh documents — start early. (Reminder set at {lead} days.)",
                    severity="CRITICAL" if days_left < 0 else "WARNING",
                    link="/projects/{pid}/calendar",
                    dedupe_key=key,
                    email=True,
                    commit=False,
                )
                if notified is not None:
                    sent = list(r.reminders_sent or [])
                    sent.append(key)
                    r.reminders_sent = sent
                    created += 1
    if created:
        db.commit()
    return created


def document_expiry_sweep(db: Session) -> int:
    """Flag expired documents and notify (90/30/7 day warnings via expiry date)."""
    today = date.today()
    created = 0
    docs = db.scalars(select(models.Document).where(models.Document.expiry_date.is_not(None))).all()
    for d in docs:
        if d.expiry_date is None:
            continue
        days = (d.expiry_date - today).days
        if days < 0 and d.status != models.DocumentStatus.EXPIRED:
            d.status = models.DocumentStatus.EXPIRED
            notify(
                db, user_id=None, project_id=d.project_id,
                notification_type=NotificationType.DOCUMENT_EXPIRY,
                title=f"Document expired: {d.title}",
                body=f"{d.title} expired on {d.expiry_date.isoformat()}. Upload the renewed copy or record the renewal.",
                severity="CRITICAL", link="/projects/{pid}/documents",
                dedupe_key=f"docexp:{d.id}:{d.expiry_date.isoformat()}",
                commit=False,
            )
            created += 1
        elif 0 <= days <= 30:
            notified = notify(
                db, user_id=None, project_id=d.project_id,
                notification_type=NotificationType.DOCUMENT_EXPIRY,
                title=f"Document expiring soon: {d.title}",
                body=f"{d.title} expires on {d.expiry_date.isoformat()} ({days} days).",
                severity="WARNING", link="/projects/{pid}/documents",
                dedupe_key=f"docsoon:{d.id}:{d.expiry_date.isoformat()}",
                commit=False,
            )
            if notified is not None:
                created += 1
    if created:
        db.commit()
    return created


def run_background_sweeps(db: Session) -> dict[str, int]:
    return {
        "renewal_status_updates": update_renewal_statuses(db),
        "renewal_reminders": generate_renewal_reminders(db),
        "document_expiry": document_expiry_sweep(db),
    }
