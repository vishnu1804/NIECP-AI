"""
Authentication & authorization service (spec §3, §39).

 * email+password auth with bcrypt, lockout after repeated failures;
 * JWT access tokens + revocable, hashed refresh tokens (session management);
 * email verification and password reset via single-use hashed tokens — in a
   deployment without SMTP the token is returned in the API response and the
   response says plainly that email delivery is not configured (never "email
   sent");
 * RBAC: platform role + per-organization membership role + FastAPI
   dependencies used by every protected router.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..database import get_db
from ..enums import AccountStatus, AuditResult, OrgRole, PlatformRole
from ..models_mixins import utcnow
from ..security import (
    create_access_token,
    decode_token,
    expires_in_seconds,
    hash_password,
    new_refresh_token,
    password_problems,
    token_hash,
    verify_password,
)
from . import notifications as notification_service
from .audit import audit_event

log = logging.getLogger("niecp.auth")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15

bearer_scheme = HTTPBearer(auto_error=False)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_registration(email: str, password: str, full_name: str) -> list[str]:
    problems: list[str] = []
    if not EMAIL_RE.match(email or ""):
        problems.append("a valid email address")
    if not full_name or len(full_name.strip()) < 2:
        problems.append("your full name")
    pw = password_problems(password or "")
    problems.extend(pw)
    return problems


def get_user_by_email(db: Session, email: str) -> models.User | None:
    return db.scalars(select(models.User).where(models.User.email_normalized == normalize_email(email))).first()


def create_user(
    db: Session,
    *,
    email: str,
    password: str,
    full_name: str,
    phone: str | None = None,
    platform_role: PlatformRole = PlatformRole.APPLICANT,
    organization_name: str | None = None,
    organization_type: models.OrganizationType | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> tuple[models.User, str | None]:
    """Create user (+ optional org). Returns (user, email_verification_token_or_None)."""
    from ..security import create_reset_token

    user = models.User(
        email=email.strip(),
        email_normalized=normalize_email(email),
        password_hash=hash_password(password),
        full_name=full_name.strip(),
        phone=phone,
        platform_role=platform_role,
        status=AccountStatus.PENDING_VERIFICATION,
        avatar_color="#2563eb",
    )
    db.add(user)
    db.flush()

    if organization_name:
        org = models.Organization(name=organization_name.strip(), org_type=organization_type or models.OrganizationType.PRIVATE_LIMITED)
        db.add(org)
        db.flush()
        user.organization_id = org.id
        db.add(
            models.OrganizationMember(
                organization_id=org.id,
                user_id=user.id,
                org_role=OrgRole.ADMIN,
                can_submit_applications=True,
                can_manage_users=True,
            )
        )
    db.add(models.UserPreference(user_id=user.id))

    raw_token, hashed = create_reset_token()
    db.add(
        models.EmailVerificationToken(
            user_id=user.id,
            token_hash=hashed,
            expires_at=utcnow() + timedelta(days=3),
        )
    )
    audit_event(
        db, action="auth.register", action_category="AUTH", user_id=user.id, user_email=user.email,
        ip_address=ip, user_agent=user_agent, request_id=request_id, commit=False,
    )
    db.commit()
    return user, raw_token


def authenticate(db: Session, *, email: str, password: str, ip: str | None = None, user_agent: str | None = None) -> tuple[models.User | None, str | None]:
    """Returns (user, error_code). Lockout and audit are handled here."""
    user = get_user_by_email(db, email)
    if user is None:
        audit_event(db, action="auth.login", action_category="AUTH", result=AuditResult.FAILURE,
                    user_email=normalize_email(email), ip_address=ip, user_agent=user_agent,
                    details={"reason": "unknown_email"}, is_security_event=True, commit=True)
        return None, "invalid_credentials"
    if user.locked_until and user.locked_until > utcnow():
        audit_event(db, action="auth.login", action_category="AUTH", user_id=user.id, user_email=user.email,
                    result=AuditResult.DENIED, ip_address=ip, user_agent=user_agent,
                    details={"reason": "locked"}, is_security_event=True, commit=True)
        return None, "account_locked"
    if user.status in (AccountStatus.SUSPENDED, AccountStatus.DELETED):
        return None, "account_disabled"
    if not verify_password(password, user.password_hash):
        user.failed_login_count = (user.failed_login_count or 0) + 1
        if user.failed_login_count >= MAX_FAILED_LOGINS:
            user.locked_until = utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
            user.failed_login_count = 0
        db.commit()
        audit_event(db, action="auth.login", action_category="AUTH", user_id=user.id, user_email=user.email,
                    result=AuditResult.FAILURE, ip_address=ip, user_agent=user_agent,
                    details={"reason": "bad_password"}, is_security_event=True, commit=True)
        return None, "invalid_credentials"

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = utcnow()
    db.commit()
    audit_event(db, action="auth.login", action_category="AUTH", user_id=user.id, user_email=user.email,
                ip_address=ip, user_agent=user_agent, commit=True)
    return user, None


def issue_session(db: Session, user: models.User, *, ip: str | None = None, user_agent: str | None = None) -> dict[str, Any]:
    access = create_access_token(str(user.id), claims={"role": user.platform_role.value, "email": user.email})
    refresh = new_refresh_token()
    db.add(
        models.RefreshToken(
            user_id=user.id,
            token_hash=token_hash(refresh),
            expires_at=expires_in_seconds(),
            ip_address=ip,
            user_agent=user_agent[:400] if user_agent else None,
            last_used_at=utcnow(),
        )
    )
    db.commit()
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": settings.access_token_minutes * 60,
    }


def rotate_session(db: Session, refresh_token: str, *, ip: str | None = None, user_agent: str | None = None) -> dict[str, Any] | None:
    row = db.scalars(select(models.RefreshToken).where(models.RefreshToken.token_hash == token_hash(refresh_token))).first()
    if row is None or row.revoked_at is not None or row.expires_at < utcnow():
        return None
    user = db.get(models.User, row.user_id)
    if user is None or user.status != AccountStatus.ACTIVE and user.status != AccountStatus.PENDING_VERIFICATION:
        return None
    row.revoked_at = utcnow()  # rotation: old token is single-use
    row.last_used_at = utcnow()
    session = issue_session(db, user, ip=ip, user_agent=user_agent)
    return session


def revoke_session(db: Session, refresh_token: str | None) -> bool:
    if not refresh_token:
        return False
    row = db.scalars(select(models.RefreshToken).where(models.RefreshToken.token_hash == token_hash(refresh_token))).first()
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = utcnow()
    db.commit()
    return True


def revoke_all_sessions(db: Session, user_id: int) -> int:
    rows = db.scalars(select(models.RefreshToken).where(models.RefreshToken.user_id == user_id, models.RefreshToken.revoked_at.is_(None))).all()
    for r in rows:
        r.revoked_at = utcnow()
    db.commit()
    return len(rows)


def list_sessions(db: Session, user_id: int) -> list[models.RefreshToken]:
    return db.scalars(
        select(models.RefreshToken)
        .where(models.RefreshToken.user_id == user_id, models.RefreshToken.revoked_at.is_(None))
        .order_by(models.RefreshToken.created_at.desc())
    ).all()


# ─────────────────────────────────────────────────────── FastAPI deps ──
def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required", {"WWW-Authenticate": "Bearer"})
    payload = decode_token(credentials.credentials)
    if payload is None or payload.get("typ") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired or invalid. Please sign in again.")
    user = db.get(models.User, int(payload.get("sub", "0")))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found.")
    if user.status == AccountStatus.SUSPENDED:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is suspended.")
    if user.status == AccountStatus.DELETED:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account has been deleted.")
    return user


def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> models.User | None:
    if credentials is None or not credentials.credentials:
        return None
    try:
        return get_current_user(credentials, db)
    except HTTPException:
        return None


def require_verified_email(user: models.User = Depends(get_current_user)) -> models.User:
    # Email verification is enforced softly until SMTP is configured, so that
    # local/offline deployments remain usable — but the state is always shown.
    if user.status == AccountStatus.PENDING_VERIFICATION and settings.email_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Please verify your email address first.")
    return user


def get_org_role(db: Session, user: models.User, organization_id: int | None) -> OrgRole | None:
    if organization_id is None:
        organization_id = user.organization_id
    if organization_id is None:
        return None
    membership = db.scalars(
        select(models.OrganizationMember).where(
            models.OrganizationMember.user_id == user.id,
            models.OrganizationMember.organization_id == organization_id,
            models.OrganizationMember.is_active.is_(True),
        )
    ).first()
    if membership is not None:
        return membership.org_role
    if user.platform_role == PlatformRole.SYSTEM_ADMIN:
        return OrgRole.ADMIN
    return None


def require_org_role(minimum: OrgRole):
    ordering = {OrgRole.VIEWER: 0, OrgRole.EMPLOYEE: 1, OrgRole.MANAGER: 2, OrgRole.ADMIN: 3}

    def _dep(
        organization_id: int | None = None,
        user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> models.User:
        role = get_org_role(db, user, organization_id)
        if role is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not a member of this organization.")
        if ordering[role] < ordering[minimum]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"This action requires the {minimum.value} role.")
        return user

    return _dep


def require_platform_role(*roles: PlatformRole):
    def _dep(user: models.User = Depends(get_current_user)) -> models.User:
        if user.platform_role not in roles and user.platform_role != PlatformRole.SYSTEM_ADMIN:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This action requires elevated platform permissions.")
        return user

    return _dep


def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


def request_id(request: Request) -> str | None:
    return request.headers.get("x-request-id")


def project_access(db: Session, user: models.User, project_id: int) -> models.Project:
    """Load a project and verify the user may access it (org membership or owner
    or platform admin)."""
    project = db.get(models.Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    if project.created_by == user.id or user.platform_role == PlatformRole.SYSTEM_ADMIN:
        return project
    if project.organization_id is not None:
        role = get_org_role(db, user, project.organization_id)
        if role is not None:
            return project
    raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have access to this project.")
