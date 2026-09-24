"""Authentication & account endpoints (spec §3)."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..database import get_db
from ..enums import AccountStatus, PlatformRole
from ..models_mixins import utcnow
from ..security import (
    create_reset_token,
    password_problems,
    password_strength,
    verify_reset_token,
    verify_password,
    hash_password,
)
from ..services import notifications as notification_service
from ..services.auth_service import (
    authenticate,
    client_ip,
    create_user,
    get_current_user,
    issue_session,
    list_sessions,
    request_id as req_id,
    revoke_all_sessions,
    revoke_session,
    rotate_session,
    user_agent,
    validate_registration,
)
from ..services.audit import audit_event

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str = Field(min_length=2, max_length=160)
    phone: str | None = None
    organization_name: str | None = Field(default=None, max_length=240)
    platform_role: PlatformRole = PlatformRole.APPLICANT


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class ForgotRequest(BaseModel):
    email: str


class ResetRequest(BaseModel):
    email: str
    token: str
    new_password: str


class VerifyRequest(BaseModel):
    email: str
    token: str


class ProfileUpdate(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    avatar_color: str | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class PreferenceUpdate(BaseModel):
    language: str | None = None
    easy_mode: bool | None = None
    theme: str | None = None
    voice_enabled: bool | None = None
    voice_rate: float | None = None
    voice_pitch: float | None = None
    reminder_days: list[int] | None = None
    notification_channels: list[str] | None = None
    timezone: str | None = None


def _session_payload(db: Session, user: models.User, *, ip: str | None, ua: str | None) -> dict[str, Any]:
    session = issue_session(db, user, ip=ip, user_agent=ua)
    pref = db.scalars(select(models.UserPreference).where(models.UserPreference.user_id == user.id)).first()
    return {
        **session,
        "user": _user_payload(user),
        "preferences": _pref_payload(pref),
        "email_delivery": {
            "smtp_configured": bool(settings.email_enabled and settings.smtp_host),
            "note": None if (settings.email_enabled and settings.smtp_host) else
            "Email delivery is not configured in this deployment. Verification links are shown here instead of being emailed.",
        },
    }


def _user_payload(user: models.User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "phone": user.phone,
        "platform_role": user.platform_role.value,
        "status": user.status.value,
        "email_verified": user.email_verified_at is not None,
        "organization_id": user.organization_id,
        "avatar_color": user.avatar_color,
        "must_change_password": user.must_change_password,
        "onboarding_completed": user.onboarding_completed_at is not None,
        "is_demo": user.is_demo_account,
    }


def _pref_payload(pref: models.UserPreference | None) -> dict[str, Any]:
    if pref is None:
        return {"language": "en", "easy_mode": False, "theme": "dark", "voice_enabled": True,
                "reminder_days": [90, 60, 30, 7], "timezone": "Asia/Kolkata"}
    return {
        "language": pref.language,
        "easy_mode": pref.easy_mode,
        "theme": pref.theme,
        "voice_enabled": pref.voice_enabled,
        "voice_rate": pref.voice_rate,
        "voice_pitch": pref.voice_pitch,
        "reminder_days": pref.reminder_days or [90, 60, 30, 7],
        "notification_channels": pref.notification_channels or ["IN_APP"],
        "timezone": pref.timezone,
    }


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    problems = validate_registration(body.email, body.password, body.full_name)
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            {"message": "Please provide: " + ", ".join(problems), "field_problems": problems})
    from ..services.auth_service import get_user_by_email

    if get_user_by_email(db, body.email) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists. Try signing in or reset your password.")
    strength = password_strength(body.password)
    ip, ua, rid = client_ip(request), user_agent(request), req_id(request)
    user, token = create_user(
        db,
        email=body.email,
        password=body.password,
        full_name=body.full_name,
        phone=body.phone,
        platform_role=body.platform_role,
        organization_name=body.organization_name,
        ip=ip,
        user_agent=ua,
        request_id=rid,
    )
    payload = _session_payload(db, user, ip=ip, ua=ua)
    payload["password_strength"] = strength
    payload["email_verification"] = {
        "required": True,
        "verified": False,
        "delivery": payload["email_delivery"],
        "token": token,  # surfaced only because SMTP may not be configured; never emailed silently
    }
    return payload


@router.post("/login")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    user, error = authenticate(db, email=body.email, password=body.password,
                               ip=client_ip(request), user_agent=user_agent(request))
    if user is None:
        message = {
            "invalid_credentials": "Email or password is incorrect.",
            "account_locked": "Too many failed attempts. This account is temporarily locked — try again in 15 minutes or reset your password.",
            "account_disabled": "This account is not active. Contact your organization admin.",
        }.get(error or "", "Sign-in failed.")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, message)
    return _session_payload(db, user, ip=client_ip(request), ua=user_agent(request))


@router.post("/refresh")
def refresh(body: RefreshRequest, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    session = rotate_session(db, body.refresh_token, ip=client_ip(request), user_agent=user_agent(request))
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired. Please sign in again.")
    return session


@router.post("/logout")
def logout(body: LogoutRequest, request: Request, db: Session = Depends(get_db),
           user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    revoked = revoke_session(db, body.refresh_token)
    audit_event(db, action="auth.logout", action_category="AUTH", user_id=user.id, user_email=user.email,
                ip_address=client_ip(request), commit=True)
    return {"ok": True, "revoked": revoked}


@router.post("/forgot-password")
def forgot_password(body: ForgotRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    from ..services.auth_service import get_user_by_email

    user = get_user_by_email(db, body.email)
    generic = {"ok": True, "message": "If an account exists for this email, a reset link has been generated."}
    if user is None:
        return generic
    raw, hashed = create_reset_token()
    db.add(models.PasswordResetToken(user_id=user.id, token_hash=hashed, expires_at=utcnow() + timedelta(hours=2)))
    db.commit()
    notification_service.notify(
        db, user_id=user.id, notification_type=notification_service.NotificationType.SYSTEM,
        title="Password reset requested", body="A password reset was requested for your account. If this wasn't you, ignore this.",
        severity="INFO", dedupe_key=f"pwreset:{user.id}:{utcnow().date().isoformat()}", email=True,
    )
    if settings.email_enabled and settings.smtp_host:
        return {**generic, "delivery": "email"}
    # Transparent manual workflow when SMTP is unavailable:
    return {
        **generic,
        "delivery": "manual",
        "reset_token": raw,
        "note": "Email delivery is not configured in this deployment. Use the token below on the reset screen. In production, configure SMTP so tokens are only ever emailed.",
    }


@router.post("/reset-password")
def reset_password(body: ResetRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    from ..services.auth_service import get_user_by_email

    user = get_user_by_email(db, body.email)
    row = None
    if user is not None:
        rows = db.scalars(
            select(models.PasswordResetToken)
            .where(models.PasswordResetToken.user_id == user.id, models.PasswordResetToken.used_at.is_(None))
            .order_by(models.PasswordResetToken.created_at.desc())
        ).all()
        for candidate in rows:
            if candidate.expires_at > utcnow() and verify_reset_token(body.token, candidate.token_hash):
                row = candidate
                break
    problems = password_problems(body.new_password)
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Password needs: " + ", ".join(problems))
    if row is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This reset link is invalid or has expired. Request a new one.")
    user.password_hash = hash_password(body.new_password)  # type: ignore[union-attr]
    user.must_change_password = False
    row.used_at = utcnow()
    revoke_all_sessions(db, user.id)  # type: ignore[union-attr]
    audit_event(db, action="auth.password_reset", action_category="AUTH", user_id=user.id, is_security_event=True, commit=True)
    return {"ok": True, "message": "Password updated. Sign in with your new password."}


@router.post("/verify-email")
def verify_email(body: VerifyRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    from ..services.auth_service import get_user_by_email

    user = get_user_by_email(db, body.email)
    row = None
    if user is not None:
        rows = db.scalars(
            select(models.EmailVerificationToken)
            .where(models.EmailVerificationToken.user_id == user.id, models.EmailVerificationToken.used_at.is_(None))
        ).all()
        for candidate in rows:
            if candidate.expires_at > utcnow() and verify_reset_token(body.token, candidate.token_hash):
                row = candidate
                break
    if row is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This verification link is invalid or has expired.")
    row.used_at = utcnow()
    user.email_verified_at = utcnow()  # type: ignore[union-attr]
    user.status = AccountStatus.ACTIVE
    audit_event(db, action="auth.email_verified", action_category="AUTH", user_id=user.id, commit=True)
    return {"ok": True, "verified": True}


@router.post("/resend-verification")
def resend_verification(request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    if user.email_verified_at is not None:
        return {"ok": True, "already_verified": True}
    raw, hashed = create_reset_token()
    db.add(models.EmailVerificationToken(user_id=user.id, token_hash=hashed, expires_at=utcnow() + timedelta(days=3)))
    db.commit()
    if settings.email_enabled and settings.smtp_host:
        return {"ok": True, "delivery": "email"}
    return {"ok": True, "delivery": "manual", "token": raw,
            "note": "Email delivery is not configured in this deployment; the token is shown here."}


@router.get("/me")
def me(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    pref = db.scalars(select(models.UserPreference).where(models.UserPreference.user_id == user.id)).first()
    memberships = db.scalars(select(models.OrganizationMember).where(models.OrganizationMember.user_id == user.id)).all()
    return {
        "user": _user_payload(user),
        "preferences": _pref_payload(pref),
        "memberships": [
            {"organization_id": m.organization_id, "role": m.org_role.value, "can_submit_applications": m.can_submit_applications,
             "can_manage_users": m.can_manage_users}
            for m in memberships
        ],
    }


@router.patch("/me")
def update_me(body: ProfileUpdate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    before = {"full_name": user.full_name, "phone": user.phone}
    if body.full_name is not None:
        user.full_name = body.full_name.strip()[:160]
    if body.phone is not None:
        user.phone = body.phone.strip()[:32]
    if body.avatar_color is not None:
        user.avatar_color = body.avatar_color[:16]
    audit_event(db, action="profile.update", action_category="PROFILE", user_id=user.id, user_email=user.email,
                before=before, after={"full_name": user.full_name, "phone": user.phone}, commit=True)
    return {"ok": True, "user": _user_payload(user)}


@router.post("/me/password")
def change_password(body: PasswordChange, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Your current password is incorrect.")
    problems = password_problems(body.new_password)
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Password needs: " + ", ".join(problems))
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    revoke_all_sessions(db, user.id)
    audit_event(db, action="auth.password_change", action_category="AUTH", user_id=user.id,
                ip_address=client_ip(request), is_security_event=True, commit=True)
    return {"ok": True, "message": "Password changed. Other sessions have been signed out."}


@router.get("/me/sessions")
def sessions(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    rows = list_sessions(db, user.id)
    return {
        "sessions": [
            {"id": r.id, "created_at": r.created_at.isoformat() if r.created_at else None,
             "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None,
             "ip_address": r.ip_address, "user_agent": r.user_agent}
            for r in rows
        ]
    }


@router.post("/me/sessions/revoke-all")
def revoke_sessions(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    count = revoke_all_sessions(db, user.id)
    return {"ok": True, "revoked": count}


@router.patch("/me/preferences")
def update_preferences(body: PreferenceUpdate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, Any]:
    pref = db.scalars(select(models.UserPreference).where(models.UserPreference.user_id == user.id)).first()
    if pref is None:
        pref = models.UserPreference(user_id=user.id)
        db.add(pref)
    if body.language is not None:
        if body.language not in ("en", "ta", "hi"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Supported languages: en, ta, hi.")
        pref.language = body.language
    for attr in ("easy_mode", "theme", "voice_enabled", "voice_rate", "voice_pitch", "reminder_days", "notification_channels", "timezone"):
        val = getattr(body, attr)
        if val is not None:
            setattr(pref, attr, val)
    db.commit()
    return {"ok": True, "preferences": _pref_payload(pref)}
