"""
NIECP-AI relational model (spec §45).

Entities: User, Organization, OrganizationMember, Project, ProjectProfile,
Industry, Approval, ApprovalRequirement, ApprovalDependency, Application,
ApplicationStatusHistory, Document, DocumentVersion, DocumentValidation,
ComplianceTask, Renewal, GovernmentQuery, Inspection, Scheme, SchemeEligibility,
GovernmentPortal, GovernmentSource, KnowledgeDocument, KnowledgeChunk,
Integration, IntegrationLog, Notification, AuditLog, AIConversation, AIMessage,
VoiceSession, UserPreference — plus auth tokens, rule provenance, dynamic
questionnaire answers and offline-sync records.

Design rules enforced here:
 * every government-facing record carries a provenance/status column, so the UI
   can never present an AI interpretation as a verified government fact;
 * nothing stores a fake government application number — `official_reference`
   is only ever written from user-confirmed input or a verified API response.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .enums import (
    AccountStatus,
    AgentName,
    AIMessageRole,
    Applicability,
    ApprovalCategory,
    ApprovalNodeState,
    ApplicationStatus,
    AuditResult,
    AuthorizationStatus,
    ChangeType,
    ChangeVerification,
    Confidence,
    ConsentStatus,
    DocumentCategory,
    DocumentOrigin,
    DocumentStatus,
    EmailDeliveryStatus,
    EnterpriseClass,
    InspectionStatus,
    IntegrationCallResult,
    IntegrationMode,
    IntegrationStatus,
    Jurisdiction,
    LandTenure,
    NotificationChannel,
    NotificationType,
    OrgRole,
    OrganizationType,
    PlatformRole,
    ProjectStage,
    ProjectType,
    QueryStatus,
    RenewalStatus,
    SourceStatus,
    SubmissionChannel,
    SyncConflictResolution,
    TaskPriority,
    TaskStatus,
    ValidationSeverity,
    VoiceState,
)
from .models_mixins import IdMixin, TimestampMixin


def _enum(col: type, **kw: Any):
    return Enum(col, native_enum=False, length=64, validate_strings=False, **kw)


# ══════════════════════════════════════════════════════════════ IDENTITY ══
class User(Base, IdMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    email_normalized: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), index=True)
    platform_role: Mapped[PlatformRole] = mapped_column(
        _enum(PlatformRole), default=PlatformRole.APPLICANT, nullable=False, index=True
    )
    status: Mapped[AccountStatus] = mapped_column(
        _enum(AccountStatus), default=AccountStatus.PENDING_VERIFICATION, nullable=False, index=True
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_demo_account: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    avatar_color: Mapped[str] = mapped_column(String(16), default="#2563eb", nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"), index=True)

    organization: Mapped["Organization | None"] = relationship(back_populates="users", foreign_keys=[organization_id])
    preferences: Mapped["UserPreference | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    memberships: Mapped[list["OrganizationMember"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", foreign_keys="OrganizationMember.user_id"
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_users_role_status", "platform_role", "status"),)


class Organization(Base, IdMixin, TimestampMixin):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    legal_name: Mapped[str | None] = mapped_column(String(240))
    org_type: Mapped[OrganizationType] = mapped_column(
        _enum(OrganizationType), default=OrganizationType.PRIVATE_LIMITED, nullable=False
    )
    enterprise_class: Mapped[EnterpriseClass] = mapped_column(
        _enum(EnterpriseClass), default=EnterpriseClass.UNKNOWN, nullable=False
    )
    pan: Mapped[str | None] = mapped_column(String(20), index=True)
    gstin: Mapped[str | None] = mapped_column(String(20), index=True)
    cin: Mapped[str | None] = mapped_column(String(30), index=True)
    udyam_number: Mapped[str | None] = mapped_column(String(40), index=True)
    startup_dpiit_number: Mapped[str | None] = mapped_column(String(40))
    address_line: Mapped[str | None] = mapped_column(String(400))
    city: Mapped[str | None] = mapped_column(String(120))
    state_code: Mapped[str | None] = mapped_column(String(8), index=True)
    pincode: Mapped[str | None] = mapped_column(String(10))
    website: Mapped[str | None] = mapped_column(String(240))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    users: Mapped[list["User"]] = relationship(back_populates="organization", foreign_keys=[User.organization_id])
    members: Mapped[list["OrganizationMember"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    projects: Mapped[list["Project"]] = relationship(back_populates="organization")


class OrganizationMember(Base, IdMixin, TimestampMixin):
    """Spec §33 — org-scoped RBAC."""

    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_member"),
        Index("ix_orgmember_org_role", "organization_id", "org_role"),
    )

    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    org_role: Mapped[OrgRole] = mapped_column(_enum(OrgRole), default=OrgRole.VIEWER, nullable=False)
    project_scope: Mapped[list[int]] = mapped_column(JSON, default=list)  # empty => all projects
    can_submit_applications: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_manage_documents: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    can_manage_users: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    invited_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    organization: Mapped["Organization"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="memberships", foreign_keys=[user_id])


class RefreshToken(Base, IdMixin, TimestampMixin):
    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_user_active", "user_id", "revoked_at"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    user_agent: Mapped[str | None] = mapped_column(String(400))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


class PasswordResetToken(Base, IdMixin, TimestampMixin):
    __tablename__ = "password_reset_tokens"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    ip_address: Mapped[str | None] = mapped_column(String(64))


class EmailVerificationToken(Base, IdMixin, TimestampMixin):
    __tablename__ = "email_verification_tokens"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)


class UserPreference(Base, IdMixin, TimestampMixin):
    """Spec §29/§30 — language, Easy Mode, theme, voice, reminders."""

    __tablename__ = "user_preferences"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    language: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    easy_mode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    theme: Mapped[str] = mapped_column(String(16), default="dark", nullable=False)
    voice_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    voice_rate: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    voice_pitch: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    voice_voice_uri: Mapped[str | None] = mapped_column(String(200))
    reminder_days: Mapped[list[int]] = mapped_column(JSON, default=lambda: [90, 60, 30, 7])
    notification_channels: Mapped[list[str]] = mapped_column(
        JSON, default=lambda: [NotificationChannel.IN_APP.value]
    )
    browser_push_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    dashboard_layout: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata", nullable=False)

    user: Mapped["User"] = relationship(back_populates="preferences")


# ═════════════════════════════════════════════════════════════ INDUSTRY ══
class Industry(Base, IdMixin, TimestampMixin):
    """Spec §5 — dynamic industry engine catalogue."""

    __tablename__ = "industries"

    code: Mapped[str] = mapped_column(String(48), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    name_ta: Mapped[str | None] = mapped_column(String(200))
    name_hi: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    nic_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    typical_hazards: Mapped[list[str]] = mapped_column(JSON, default=list)
    question_sets: Mapped[list[str]] = mapped_column(JSON, default=list)
    pollution_load_class: Mapped[str | None] = mapped_column(String(32))  # CPCB-style category label
    source_status: Mapped[SourceStatus] = mapped_column(
        _enum(SourceStatus), default=SourceStatus.REQUIRES_VERIFICATION, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SubIndustry(Base, IdMixin, TimestampMixin):
    __tablename__ = "sub_industries"
    __table_args__ = (Index("ix_subind_industry", "industry_id"),)

    industry_id: Mapped[int] = mapped_column(
        ForeignKey("industries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    extra_question_sets: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text)

    industry: Mapped["Industry"] = relationship()


# ══════════════════════════════════════════════════════════════ PROJECTS ══
class Project(Base, IdMixin, TimestampMixin):
    """Spec §32 — a user can run several independent projects."""

    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_project_org_active", "organization_id", "is_archived"),
        UniqueConstraint("organization_id", "slug", name="uq_project_org_slug"),
    )

    name: Mapped[str] = mapped_column(String(240), nullable=False)
    slug: Mapped[str] = mapped_column(String(260), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), index=True
    )
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    stage: Mapped[ProjectStage] = mapped_column(
        _enum(ProjectStage), default=ProjectStage.IDEA, nullable=False, index=True
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_ai_analysis_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_readiness_at: Mapped[datetime | None] = mapped_column(DateTime)
    readiness_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    organization: Mapped["Organization | None"] = relationship(back_populates="projects")
    profile: Mapped["ProjectProfile | None"] = relationship(
        back_populates="project", uselist=False, cascade="all, delete-orphan"
    )
    approvals: Mapped[list["ProjectApproval"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    documents: Mapped[list["Document"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    applications: Mapped[list["Application"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    tasks: Mapped[list["ComplianceTask"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    answers: Mapped[list["QuestionnaireAnswer"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Project {self.id} {self.name!r}>"


class ProjectProfile(Base, IdMixin, TimestampMixin):
    """Spec §4 — the Master Project Profile (single source of truth).

    Typed columns hold the primary, queryable facts; `extra` holds industry
    specific answers so new questions never require a migration.
    """

    __tablename__ = "project_profiles"
    __table_args__ = (Index("ix_profile_project_state", "project_id", "state_code"),)

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )

    # organization block
    organization_name: Mapped[str | None] = mapped_column(String(240))
    applicant_name: Mapped[str | None] = mapped_column(String(160))
    contact_email: Mapped[str | None] = mapped_column(String(320))
    contact_phone: Mapped[str | None] = mapped_column(String(32))
    organization_type: Mapped[OrganizationType | None] = mapped_column(_enum(OrganizationType), nullable=True)
    enterprise_class: Mapped[EnterpriseClass | None] = mapped_column(_enum(EnterpriseClass), nullable=True)
    pan: Mapped[str | None] = mapped_column(String(20))
    gstin: Mapped[str | None] = mapped_column(String(20))
    cin: Mapped[str | None] = mapped_column(String(30))
    udyam_number: Mapped[str | None] = mapped_column(String(40))
    is_startup_recognized: Mapped[bool | None] = mapped_column(Boolean)
    is_export_oriented: Mapped[bool | None] = mapped_column(Boolean)

    # project block
    project_type: Mapped[ProjectType | None] = mapped_column(_enum(ProjectType), nullable=True)
    industry_id: Mapped[int | None] = mapped_column(ForeignKey("industries.id", ondelete="SET NULL"), index=True)
    industry_code: Mapped[str | None] = mapped_column(String(48), index=True)
    industry_other_description: Mapped[str | None] = mapped_column(Text)
    sub_industry: Mapped[str | None] = mapped_column(String(200))
    project_stage: Mapped[ProjectStage | None] = mapped_column(_enum(ProjectStage), nullable=True)

    # location block
    state_code: Mapped[str | None] = mapped_column(String(8), index=True)
    district: Mapped[str | None] = mapped_column(String(120), index=True)
    city_village: Mapped[str | None] = mapped_column(String(160))
    pincode: Mapped[str | None] = mapped_column(String(10))
    annual_turnover: Mapped[float | None] = mapped_column(Numeric(18, 2))
    buys_from_msme_suppliers: Mapped[bool | None] = mapped_column(Boolean)
    industrial_area: Mapped[str | None] = mapped_column(String(200))
    in_notified_industrial_area: Mapped[bool | None] = mapped_column(Boolean)
    land_tenure: Mapped[LandTenure | None] = mapped_column(_enum(LandTenure), nullable=True)
    land_area_sqm: Mapped[float | None] = mapped_column(Float)
    built_up_area_sqm: Mapped[float | None] = mapped_column(Float)
    survey_number: Mapped[str | None] = mapped_column(String(120))
    zoning_classification: Mapped[str | None] = mapped_column(String(120))
    is_coastal_regulation_zone: Mapped[bool | None] = mapped_column(Boolean)
    is_eco_sensitive_zone: Mapped[bool | None] = mapped_column(Boolean)
    is_forest_land: Mapped[bool | None] = mapped_column(Boolean)

    # investment block (INR)
    total_investment: Mapped[float | None] = mapped_column(Numeric(18, 2))
    land_investment: Mapped[float | None] = mapped_column(Numeric(18, 2))
    building_investment: Mapped[float | None] = mapped_column(Numeric(18, 2))
    machinery_investment: Mapped[float | None] = mapped_column(Numeric(18, 2))
    working_capital: Mapped[float | None] = mapped_column(Numeric(18, 2))
    employment_generated: Mapped[int | None] = mapped_column(Integer)
    women_employed: Mapped[int | None] = mapped_column(Integer)

    # operations block
    production_type: Mapped[str | None] = mapped_column(String(200))
    production_capacity: Mapped[str | None] = mapped_column(String(200))
    raw_materials: Mapped[list[str]] = mapped_column(JSON, default=list)
    chemicals_used: Mapped[list[str]] = mapped_column(JSON, default=list)
    hazardous_substances: Mapped[list[str]] = mapped_column(JSON, default=list)
    uses_hazardous_chemicals: Mapped[bool | None] = mapped_column(Boolean)
    is_mah_directed: Mapped[bool | None] = mapped_column(Boolean)  # above threshold installation
    water_consumption_kld: Mapped[float | None] = mapped_column(Float)
    wastewater_generated_kld: Mapped[float | None] = mapped_column(Float)
    has_etp: Mapped[bool | None] = mapped_column(Boolean)
    has_stp: Mapped[bool | None] = mapped_column(Boolean)
    air_emissions_present: Mapped[bool | None] = mapped_column(Boolean)
    emission_sources: Mapped[list[str]] = mapped_column(JSON, default=list)
    has_boiler: Mapped[bool | None] = mapped_column(Boolean)
    boiler_capacity_tph: Mapped[float | None] = mapped_column(Float)
    has_dg_set: Mapped[bool | None] = mapped_column(Boolean)
    dg_set_kva: Mapped[float | None] = mapped_column(Float)
    fire_risk_level: Mapped[str | None] = mapped_column(String(32))
    electrical_load_kw: Mapped[float | None] = mapped_column(Float)
    htaht_connection_required: Mapped[bool | None] = mapped_column(Boolean)
    e_waste_generated: Mapped[bool | None] = mapped_column(Boolean)
    plastic_waste_generated: Mapped[bool | None] = mapped_column(Boolean)
    hazardous_waste_generated: Mapped[bool | None] = mapped_column(Boolean)
    hazardous_waste_tpa: Mapped[float | None] = mapped_column(Float)
    solid_waste_generated: Mapped[bool | None] = mapped_column(Boolean)
    biomedical_waste_generated: Mapped[bool | None] = mapped_column(Boolean)
    construction_demolition_waste: Mapped[bool | None] = mapped_column(Boolean)
    battery_waste_generated: Mapped[bool | None] = mapped_column(Boolean)
    uses_batteries: Mapped[bool | None] = mapped_column(Boolean)
    workers_on_site: Mapped[int | None] = mapped_column(Integer)
    is_factory_under_factories_act: Mapped[bool | None] = mapped_column(Boolean)
    operates_in_shifts: Mapped[bool | None] = mapped_column(Boolean)
    uses_contract_labour: Mapped[bool | None] = mapped_column(Boolean)

    # business block
    domestic_sales_annual: Mapped[float | None] = mapped_column(Numeric(18, 2))
    export_annual: Mapped[float | None] = mapped_column(Numeric(18, 2))
    import_annual: Mapped[float | None] = mapped_column(Numeric(18, 2))
    number_of_employees: Mapped[int | None] = mapped_column(Integer)
    power_requirement_kw: Mapped[float | None] = mapped_column(Float)
    water_requirement_kld: Mapped[float | None] = mapped_column(Float)

    # dynamic / industry specific
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    completeness: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    project: Mapped["Project"] = relationship(back_populates="profile")
    industry: Mapped["Industry | None"] = relationship()


class QuestionnaireAnswer(Base, IdMixin, TimestampMixin):
    """Spec §5 — answers to dynamically selected questions."""

    __tablename__ = "questionnaire_answers"
    __table_args__ = (UniqueConstraint("project_id", "question_key", name="uq_answer_project_key"),)

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_key: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    question_set: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[Any] = mapped_column(JSON, nullable=True)
    answered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    why_asked: Mapped[str | None] = mapped_column(Text)  # explainability of the question itself

    project: Mapped["Project"] = relationship(back_populates="answers")


# ═════════════════════════════════════════════════════════════ APPROVALS ══
class ApprovalTemplate(Base, IdMixin, TimestampMixin):
    """Catalogue entry: a known approval/registration type with its authority
    and official source. Rule-engine produced, human-curated."""

    __tablename__ = "approval_templates"
    __table_args__ = (
        Index("ix_approval_tpl_cat_juris", "category", "jurisdiction"),
        UniqueConstraint("code", name="uq_approval_template_code"),
    )

    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    name_ta: Mapped[str | None] = mapped_column(String(240))
    name_hi: Mapped[str | None] = mapped_column(String(240))
    category: Mapped[ApprovalCategory] = mapped_column(_enum(ApprovalCategory), nullable=False, index=True)
    jurisdiction: Mapped[Jurisdiction] = mapped_column(_enum(Jurisdiction), nullable=False)
    authority: Mapped[str] = mapped_column(String(240), nullable=False)
    department: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    why_it_may_apply: Mapped[str | None] = mapped_column(Text)
    applicability_conditions: Mapped[list[str]] = mapped_column(JSON, default=list)
    required_documents: Mapped[list[str]] = mapped_column(JSON, default=list)
    process_summary: Mapped[str | None] = mapped_column(Text)
    estimated_timeline_days: Mapped[int | None] = mapped_column(Integer)
    statutory_timeline_text: Mapped[str | None] = mapped_column(Text)
    fee_information: Mapped[str | None] = mapped_column(Text)
    validity_text: Mapped[str | None] = mapped_column(Text)
    renewal_period_months: Mapped[int | None] = mapped_column(Integer)
    official_portal_name: Mapped[str | None] = mapped_column(String(200))
    official_portal_url: Mapped[str | None] = mapped_column(String(500))
    legal_basis: Mapped[list[str]] = mapped_column(JSON, default=list)
    graph_layer: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    source_status: Mapped[SourceStatus] = mapped_column(
        _enum(SourceStatus), default=SourceStatus.REQUIRES_VERIFICATION, nullable=False
    )
    confidence: Mapped[Confidence] = mapped_column(
        _enum(Confidence), default=Confidence.REQUIRES_VERIFICATION, nullable=False
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    verification_note: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("government_sources.id", ondelete="SET NULL"), index=True
    )
    portal_id: Mapped[int | None] = mapped_column(ForeignKey("government_portals.id", ondelete="SET NULL"), index=True)
    applies_to_states: Mapped[list[str]] = mapped_column(JSON, default=list)  # empty = all
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    rules: Mapped[list["ApprovalRule"]] = relationship(back_populates="template")


class ApprovalRule(Base, IdMixin, TimestampMixin):
    """Deterministic rule definitions (spec §1/§7: the AI never overrides these).

    `condition` is a small, auditable expression evaluated by the rule engine
    against the project profile. `explanation_template` produces the
    human-readable "why this may apply" text.
    """

    __tablename__ = "approval_rules"
    __table_args__ = (Index("ix_rule_template_active", "template_id", "is_active"),)

    template_id: Mapped[int] = mapped_column(
        ForeignKey("approval_templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_key: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    condition: Mapped[str] = mapped_column(Text, nullable=False)
    explanation_template: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    produces_applicability: Mapped[Applicability] = mapped_column(
        _enum(Applicability), default=Applicability.APPLIES, nullable=False
    )
    required_question_keys: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    template: Mapped["ApprovalTemplate"] = relationship(back_populates="rules")


class ApprovalDependencyTemplate(Base, IdMixin, TimestampMixin):
    """Spec §11 — catalogue-level dependency graph edges."""

    __tablename__ = "approval_dependency_templates"
    __table_args__ = (
        UniqueConstraint("parent_code", "child_code", name="uq_dep_template_edge"),
    )

    parent_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    child_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    dependency_type: Mapped[str] = mapped_column(String(32), default="PREREQUISITE", nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    typical_lag_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class ProjectApproval(Base, IdMixin, TimestampMixin):
    """An approval instance for a specific project, with provenance."""

    __tablename__ = "project_approvals"
    __table_args__ = (
        UniqueConstraint("project_id", "template_code", name="uq_project_approval"),
        Index("ix_pa_project_state", "project_id", "node_state"),
        Index("ix_pa_project_cat", "project_id", "category"),
    )

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("approval_templates.id", ondelete="SET NULL"), index=True
    )
    template_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    category: Mapped[ApprovalCategory] = mapped_column(_enum(ApprovalCategory), nullable=False)
    authority: Mapped[str] = mapped_column(String(240), nullable=False)
    jurisdiction: Mapped[Jurisdiction] = mapped_column(_enum(Jurisdiction), nullable=False)
    applicability: Mapped[Applicability] = mapped_column(
        _enum(Applicability), default=Applicability.UNKNOWN, nullable=False, index=True
    )
    node_state: Mapped[ApprovalNodeState] = mapped_column(
        _enum(ApprovalNodeState), default=ApprovalNodeState.NOT_STARTED, nullable=False
    )
    # provenance — this is what keeps AI output distinguishable from fact
    source_status: Mapped[SourceStatus] = mapped_column(
        _enum(SourceStatus), default=SourceStatus.REQUIRES_VERIFICATION, nullable=False
    )
    confidence: Mapped[Confidence] = mapped_column(
        _enum(Confidence), default=Confidence.REQUIRES_VERIFICATION, nullable=False
    )
    matched_rule_keys: Mapped[list[str]] = mapped_column(JSON, default=list)
    why_it_applies: Mapped[str | None] = mapped_column(Text)
    matched_facts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    missing_information: Mapped[list[str]] = mapped_column(JSON, default=list)
    required_documents: Mapped[list[str]] = mapped_column(JSON, default=list)
    document_requirements: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    dependencies: Mapped[list[str]] = mapped_column(JSON, default=list)  # template codes
    dependents: Mapped[list[str]] = mapped_column(JSON, default=list)
    graph_layer: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    risk_indicators: Mapped[list[str]] = mapped_column(JSON, default=list)
    official_portal_name: Mapped[str | None] = mapped_column(String(200))
    official_portal_url: Mapped[str | None] = mapped_column(String(500))
    legal_basis: Mapped[list[str]] = mapped_column(JSON, default=list)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    verification_note: Mapped[str | None] = mapped_column(Text)
    estimated_timeline_days: Mapped[int | None] = mapped_column(Integer)
    user_notes: Mapped[str | None] = mapped_column(Text)
    user_dismissed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    user_confirmed_required: Mapped[bool | None] = mapped_column(Boolean)
    is_on_critical_path: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    project: Mapped["Project"] = relationship(back_populates="approvals")
    template: Mapped["ApprovalTemplate | None"] = relationship()
    requirements: Mapped[list["ProjectApprovalRequirement"]] = relationship(
        back_populates="project_approval", cascade="all, delete-orphan"
    )


class ProjectApprovalRequirement(Base, IdMixin, TimestampMixin):
    """Spec §45 ApprovalRequirement — one line of the document/prereq checklist."""

    __tablename__ = "project_approval_requirements"
    __table_args__ = (Index("ix_par_approval_kind", "project_approval_id", "requirement_type"),)

    project_approval_id: Mapped[int] = mapped_column(
        ForeignKey("project_approvals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requirement_type: Mapped[str] = mapped_column(String(32), nullable=False)  # DOCUMENT | PREREQUISITE | ACTION
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    document_category: Mapped[DocumentCategory | None] = mapped_column(_enum(DocumentCategory), nullable=True)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_satisfied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    satisfied_by_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )
    source_status: Mapped[SourceStatus] = mapped_column(
        _enum(SourceStatus), default=SourceStatus.REQUIRES_VERIFICATION, nullable=False
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    project_approval: Mapped["ProjectApproval"] = relationship(back_populates="requirements")


# ═════════════════════════════════════════════════════════════ DOCUMENTS ══
class Document(Base, IdMixin, TimestampMixin):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_doc_project_cat", "project_id", "category"),
        Index("ix_doc_project_status", "project_id", "status"),
    )

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"), index=True)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(300), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[DocumentCategory] = mapped_column(_enum(DocumentCategory), nullable=False, index=True)
    ai_category: Mapped[DocumentCategory | None] = mapped_column(_enum(DocumentCategory), nullable=True)
    ai_document_type: Mapped[str | None] = mapped_column(String(160), index=True)
    ai_classification_confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[DocumentStatus] = mapped_column(
        _enum(DocumentStatus), default=DocumentStatus.UPLOADED, nullable=False, index=True
    )
    mime_type: Mapped[str | None] = mapped_column(String(160))
    extension: Mapped[str | None] = mapped_column(String(16))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    page_count: Mapped[int | None] = mapped_column(Integer)
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    expiry_date: Mapped[date | None] = mapped_column(Date, index=True)
    issue_date: Mapped[date | None] = mapped_column(Date)
    issuing_authority: Mapped[str | None] = mapped_column(String(240))
    document_number: Mapped[str | None] = mapped_column(String(160), index=True)
    origin: Mapped[DocumentOrigin] = mapped_column(
        _enum(DocumentOrigin), default=DocumentOrigin.USER_UPLOADED, nullable=False, index=True
    )
    gov_reference_id: Mapped[int | None] = mapped_column(Integer)  # → gov_data_references.id when set
    verification_status: Mapped[SourceStatus] = mapped_column(
        _enum(SourceStatus), default=SourceStatus.USER_PROVIDED, nullable=False
    )
    verified_by_authority: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    linked_approval_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    extracted_text_preview: Mapped[str | None] = mapped_column(Text)
    ocr_engine: Mapped[str | None] = mapped_column(String(64))
    text_extraction_status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)

    project: Mapped["Project"] = relationship(back_populates="documents")
    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    validations: Mapped[list["DocumentValidation"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentVersion(Base, IdMixin, TimestampMixin):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version", name="uq_doc_version"),)

    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(200), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    change_reason: Mapped[str | None] = mapped_column(String(400))
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    document: Mapped["Document"] = relationship(back_populates="versions")


class DocumentValidation(Base, IdMixin, TimestampMixin):
    """Spec §10 — AI validation findings. Always labelled as AI interpretation."""

    __tablename__ = "document_validations"
    __table_args__ = (Index("ix_dv_doc_sev", "document_id", "severity"),)

    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    check_key: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[ValidationSeverity] = mapped_column(
        _enum(ValidationSeverity), default=ValidationSeverity.INFO, nullable=False
    )
    source_status: Mapped[SourceStatus] = mapped_column(
        _enum(SourceStatus), default=SourceStatus.AI_INTERPRETATION, nullable=False
    )
    expected_value: Mapped[str | None] = mapped_column(String(300))
    found_value: Mapped[str | None] = mapped_column(String(300))
    auto_fix_hint: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    run_id: Mapped[str | None] = mapped_column(String(48), index=True)

    document: Mapped["Document"] = relationship(back_populates="validations")


# ══════════════════════════════════════════════════════════ APPLICATIONS ══
class Application(Base, IdMixin, TimestampMixin):
    """Spec §14/§15. `official_reference` is ONLY ever user-confirmed input or
    a verified API response — the platform never invents one."""

    __tablename__ = "applications"
    __table_args__ = (
        Index("ix_app_project_status", "project_id", "status"),
        Index("ix_app_org_status", "organization_id", "status"),
    )

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"), index=True)
    project_approval_id: Mapped[int | None] = mapped_column(
        ForeignKey("project_approvals.id", ondelete="SET NULL"), index=True
    )
    approval_template_code: Mapped[str | None] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    authority: Mapped[str | None] = mapped_column(String(240))
    status: Mapped[ApplicationStatus] = mapped_column(
        _enum(ApplicationStatus), default=ApplicationStatus.DRAFT, nullable=False, index=True
    )
    submission_channel: Mapped[SubmissionChannel] = mapped_column(
        _enum(SubmissionChannel), default=SubmissionChannel.NOT_SUBMITTED, nullable=False
    )
    integration_mode: Mapped[IntegrationMode] = mapped_column(
        _enum(IntegrationMode), default=IntegrationMode.MANUAL, nullable=False, index=True
    )
    correlation_id: Mapped[str | None] = mapped_column(String(48), index=True)
    provider: Mapped[str | None] = mapped_column(String(96))
    official_reference: Mapped[str | None] = mapped_column(String(160), index=True)
    official_reference_source: Mapped[SourceStatus] = mapped_column(
        _enum(SourceStatus), default=SourceStatus.INFORMATION_UNAVAILABLE, nullable=False
    )
    official_portal_url: Mapped[str | None] = mapped_column(String(500))
    prepared_at: Mapped[datetime | None] = mapped_column(DateTime)
    user_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    user_confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    confirmation_text: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    submitted_by_user: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    decision_date: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date, index=True)
    fee_paid: Mapped[float | None] = mapped_column(Numeric(14, 2))
    fee_payment_reference: Mapped[str | None] = mapped_column(String(160))
    application_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    preparation_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    readiness_score: Mapped[float | None] = mapped_column(Float)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status_is_self_reported: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)

    project: Mapped["Project"] = relationship(back_populates="applications")
    project_approval: Mapped["ProjectApproval | None"] = relationship()
    history: Mapped[list["ApplicationStatusHistory"]] = relationship(
        back_populates="application", cascade="all, delete-orphan", order_by="ApplicationStatusHistory.id"
    )
    queries: Mapped[list["GovernmentQuery"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )
    inspections: Mapped[list["Inspection"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )


class ApplicationStatusHistory(Base, IdMixin, TimestampMixin):
    __tablename__ = "application_status_history"
    __table_args__ = (Index("ix_ash_app_status", "application_id", "status"),)

    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[ApplicationStatus] = mapped_column(_enum(ApplicationStatus), nullable=False)
    previous_status: Mapped[ApplicationStatus | None] = mapped_column(_enum(ApplicationStatus), nullable=True)
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    source_status: Mapped[SourceStatus] = mapped_column(
        _enum(SourceStatus), default=SourceStatus.USER_PROVIDED, nullable=False
    )
    evidence_reference: Mapped[str | None] = mapped_column(String(300))
    effective_at: Mapped[datetime | None] = mapped_column(DateTime)

    application: Mapped["Application"] = relationship(back_populates="history")


# ═══════════════════════════════════════════════════════════ COMPLIANCE ══
class ComplianceTask(Base, IdMixin, TimestampMixin):
    __tablename__ = "compliance_tasks"
    __table_args__ = (
        Index("ix_task_project_status", "project_id", "status"),
        Index("ix_task_due", "project_id", "due_date"),
    )

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"), index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    task_type: Mapped[str] = mapped_column(String(48), default="GENERAL", nullable=False, index=True)
    status: Mapped[TaskStatus] = mapped_column(
        _enum(TaskStatus), default=TaskStatus.OPEN, nullable=False, index=True
    )
    priority: Mapped[TaskPriority] = mapped_column(
        _enum(TaskPriority), default=TaskPriority.MEDIUM, nullable=False, index=True
    )
    due_date: Mapped[date | None] = mapped_column(Date, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    approval_code: Mapped[str | None] = mapped_column(String(64), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    source_status: Mapped[SourceStatus] = mapped_column(
        _enum(SourceStatus), default=SourceStatus.AI_INTERPRETATION, nullable=False
    )
    generated_by_agent: Mapped[str | None] = mapped_column(String(32))
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    recurrence_rule: Mapped[str | None] = mapped_column(String(120))
    offline_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    checklist: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    project: Mapped["Project"] = relationship(back_populates="tasks")
    assignee: Mapped["User | None"] = relationship(foreign_keys=[assigned_to])


class Renewal(Base, IdMixin, TimestampMixin):
    """Spec §22 — renewal engine state."""

    __tablename__ = "renewals"
    __table_args__ = (
        Index("ix_renewal_project_due", "project_id", "due_date"),
        Index("ix_renewal_status", "status"),
    )

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"), index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    renewal_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    approval_code: Mapped[str | None] = mapped_column(String(64), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id", ondelete="SET NULL"), index=True)
    issued_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date, index=True)
    status: Mapped[RenewalStatus] = mapped_column(
        _enum(RenewalStatus), default=RenewalStatus.UPCOMING, nullable=False, index=True
    )
    reminder_days: Mapped[list[int]] = mapped_column(JSON, default=lambda: [90, 60, 30, 7])
    reminders_sent: Mapped[list[str]] = mapped_column(JSON, default=list)  # e.g. "30:2026-01-01"
    official_portal_url: Mapped[str | None] = mapped_column(String(500))
    source_status: Mapped[SourceStatus] = mapped_column(
        _enum(SourceStatus), default=SourceStatus.USER_PROVIDED, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class GovernmentQuery(Base, IdMixin, TimestampMixin):
    """Spec §23."""

    __tablename__ = "government_queries"
    __table_args__ = (Index("ix_query_app_status", "application_id", "status"),)

    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    authority: Mapped[str | None] = mapped_column(String(240))
    reference_number: Mapped[str | None] = mapped_column(String(160))
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    date_received: Mapped[date | None] = mapped_column(Date, index=True)
    deadline: Mapped[date | None] = mapped_column(Date, index=True)
    status: Mapped[QueryStatus] = mapped_column(
        _enum(QueryStatus), default=QueryStatus.OPEN, nullable=False, index=True
    )
    required_documents: Mapped[list[str]] = mapped_column(JSON, default=list)
    response_text: Mapped[str | None] = mapped_column(Text)
    response_attachments: Mapped[list[int]] = mapped_column(JSON, default=list)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime)
    user_confirmed_response_at: Mapped[datetime | None] = mapped_column(DateTime)
    ai_explanation: Mapped[str | None] = mapped_column(Text)
    ai_suggested_steps: Mapped[list[str]] = mapped_column(JSON, default=list)
    translator: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_status: Mapped[SourceStatus] = mapped_column(
        _enum(SourceStatus), default=SourceStatus.USER_PROVIDED, nullable=False
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    application: Mapped["Application | None"] = relationship(back_populates="queries")


class Inspection(Base, IdMixin, TimestampMixin):
    """Spec §24. Officer details only when officially provided by the user."""

    __tablename__ = "inspections"
    __table_args__ = (Index("ix_insp_project_date", "project_id", "inspection_date"),)

    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), index=True
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    inspection_date: Mapped[date | None] = mapped_column(Date, index=True)
    department: Mapped[str | None] = mapped_column(String(240))
    inspection_type: Mapped[str] = mapped_column(String(64), default="GENERAL", nullable=False)
    officer_name: Mapped[str | None] = mapped_column(String(200))
    officer_designation: Mapped[str | None] = mapped_column(String(200))
    officer_details_source: Mapped[SourceStatus] = mapped_column(
        _enum(SourceStatus), default=SourceStatus.INFORMATION_UNAVAILABLE, nullable=False
    )
    status: Mapped[InspectionStatus] = mapped_column(
        _enum(InspectionStatus), default=InspectionStatus.SCHEDULED, nullable=False, index=True
    )
    checklist: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    documents_to_keep_ready: Mapped[list[str]] = mapped_column(JSON, default=list)
    findings: Mapped[str | None] = mapped_column(Text)
    corrective_actions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    follow_up_date: Mapped[date | None] = mapped_column(Date)
    source_status: Mapped[SourceStatus] = mapped_column(
        _enum(SourceStatus), default=SourceStatus.USER_PROVIDED, nullable=False
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    application: Mapped["Application | None"] = relationship(back_populates="inspections")


# ══════════════════════════════════════════════════════ GOV KNOWLEDGE BASE ══
class GovernmentSource(Base, IdMixin, TimestampMixin):
    """Spec §36/§37 — the registry of official sources behind our claims."""

    __tablename__ = "government_sources"
    __table_args__ = (Index("ix_govsrc_kind_level", "source_type", "jurisdiction"),)

    name: Mapped[str] = mapped_column(String(300), nullable=False)
    source_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    publisher: Mapped[str] = mapped_column(String(240), nullable=False)
    jurisdiction: Mapped[Jurisdiction] = mapped_column(_enum(Jurisdiction), nullable=False)
    state_code: Mapped[str | None] = mapped_column(String(8), index=True)
    url: Mapped[str] = mapped_column(String(600), nullable=False)
    citation: Mapped[str | None] = mapped_column(Text)
    published_on: Mapped[date | None] = mapped_column(Date)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    verification_status: Mapped[SourceStatus] = mapped_column(
        _enum(SourceStatus), default=SourceStatus.REQUIRES_VERIFICATION, nullable=False
    )
    confidence: Mapped[Confidence] = mapped_column(
        _enum(Confidence), default=Confidence.REQUIRES_VERIFICATION, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class GovernmentPortal(Base, IdMixin, TimestampMixin):
    """Spec §17 — searchable portal directory."""

    __tablename__ = "government_portals"
    __table_args__ = (
        Index("ix_portal_level_state", "level", "state_code"),
        Index("ix_portal_dept", "department"),
    )

    name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    short_name: Mapped[str | None] = mapped_column(String(80))
    department: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    ministry: Mapped[str | None] = mapped_column(String(240))
    service: Mapped[str | None] = mapped_column(String(300))
    services_supported: Mapped[list[str]] = mapped_column(JSON, default=list)
    level: Mapped[Jurisdiction] = mapped_column(_enum(Jurisdiction), nullable=False, index=True)
    state_code: Mapped[str | None] = mapped_column(String(8), index=True)
    official_url: Mapped[str] = mapped_column(String(600), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    integration_status: Mapped[IntegrationStatus] = mapped_column(
        _enum(IntegrationStatus), default=IntegrationStatus.NOT_CONNECTED, nullable=False
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    verification_status: Mapped[SourceStatus] = mapped_column(
        _enum(SourceStatus), default=SourceStatus.REQUIRES_VERIFICATION, nullable=False
    )
    categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("government_sources.id", ondelete="SET NULL"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Scheme(Base, IdMixin, TimestampMixin):
    """Spec §18."""

    __tablename__ = "schemes"
    __table_args__ = (
        Index("ix_scheme_level_state", "level", "state_code"),
        Index("ix_scheme_status", "is_active"),
    )

    name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    authority: Mapped[str] = mapped_column(String(240), nullable=False)
    ministry: Mapped[str | None] = mapped_column(String(240))
    level: Mapped[Jurisdiction] = mapped_column(_enum(Jurisdiction), nullable=False, index=True)
    state_code: Mapped[str | None] = mapped_column(String(8), index=True)
    categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    short_description: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    benefits: Mapped[list[str]] = mapped_column(JSON, default=list)
    eligibility_summary: Mapped[str | None] = mapped_column(Text)
    required_documents: Mapped[list[str]] = mapped_column(JSON, default=list)
    application_process: Mapped[str | None] = mapped_column(Text)
    application_mode: Mapped[str | None] = mapped_column(String(64))
    official_url: Mapped[str | None] = mapped_column(String(600))
    official_source_name: Mapped[str | None] = mapped_column(String(300))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("government_sources.id", ondelete="SET NULL"))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    verification_status: Mapped[SourceStatus] = mapped_column(
        _enum(SourceStatus), default=SourceStatus.REQUIRES_VERIFICATION, nullable=False
    )
    confidence: Mapped[Confidence] = mapped_column(
        _enum(Confidence), default=Confidence.REQUIRES_VERIFICATION, nullable=False
    )
    valid_until: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    eligibility_rules: Mapped[list["SchemeEligibility"]] = relationship(
        back_populates="scheme", cascade="all, delete-orphan"
    )


class SchemeEligibility(Base, IdMixin, TimestampMixin):
    """Machine-readable eligibility criteria used by the Scheme Agent."""

    __tablename__ = "scheme_eligibility"
    __table_args__ = (Index("ix_selig_scheme", "scheme_id"),)

    scheme_id: Mapped[int] = mapped_column(
        ForeignKey("schemes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    criterion_key: Mapped[str] = mapped_column(String(96), nullable=False)
    expression: Mapped[str] = mapped_column(Text, nullable=False)
    human_text: Mapped[str] = mapped_column(String(500), nullable=False)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    data_gap_message: Mapped[str | None] = mapped_column(Text)

    scheme: Mapped["Scheme"] = relationship(back_populates="eligibility_rules")


class KnowledgeDocument(Base, IdMixin, TimestampMixin):
    """Spec §36 — RAG corpus entries (official docs + user project docs)."""

    __tablename__ = "knowledge_documents"
    __table_args__ = (Index("ix_kd_kind_scope", "doc_kind", "scope"),)

    title: Mapped[str] = mapped_column(String(400), nullable=False)
    doc_kind: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(32), default="GLOBAL", nullable=False, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("government_sources.id", ondelete="SET NULL"), index=True)
    url: Mapped[str | None] = mapped_column(String(600))
    publisher: Mapped[str | None] = mapped_column(String(240))
    published_on: Mapped[date | None] = mapped_column(Date)
    section: Mapped[str | None] = mapped_column(String(200))
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    language: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    verification_status: Mapped[SourceStatus] = mapped_column(
        _enum(SourceStatus), default=SourceStatus.REQUIRES_VERIFICATION, nullable=False
    )
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    body: Mapped[str | None] = mapped_column(Text)

    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class KnowledgeChunk(Base, IdMixin):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (Index("ix_kc_doc", "document_id"),)

    document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    section: Mapped[str | None] = mapped_column(String(200))
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary)
    embedding_model: Mapped[str | None] = mapped_column(String(64))
    terms: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)  # sparse vector for BM25-style scoring

    document: Mapped["KnowledgeDocument"] = relationship(back_populates="chunks")


class RegulatoryChange(Base, IdMixin, TimestampMixin):
    """Spec §25 — change radar entries."""

    __tablename__ = "regulatory_changes"
    __table_args__ = (Index("ix_change_verified_date", "verification_status", "detected_at"),)

    title: Mapped[str] = mapped_column(String(400), nullable=False)
    change_type: Mapped[ChangeType] = mapped_column(_enum(ChangeType), nullable=False, index=True)
    what_changed: Mapped[str] = mapped_column(Text, nullable=False)
    who_may_be_affected: Mapped[str | None] = mapped_column(Text)
    why_it_matters: Mapped[str | None] = mapped_column(Text)
    recommended_review: Mapped[str | None] = mapped_column(Text)
    affected_categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    affected_industries: Mapped[list[str]] = mapped_column(JSON, default=list)
    affected_states: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("government_sources.id", ondelete="SET NULL"), index=True)
    source_url: Mapped[str | None] = mapped_column(String(600))
    publisher: Mapped[str | None] = mapped_column(String(240))
    published_on: Mapped[date | None] = mapped_column(Date)
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    verification_status: Mapped[ChangeVerification] = mapped_column(
        _enum(ChangeVerification), default=ChangeVerification.PENDING_VERIFICATION, nullable=False, index=True
    )
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    impact_summary: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


# ═════════════════════════════════════════════════════════ INTEGRATIONS ══
class Integration(Base, IdMixin, TimestampMixin):
    """Spec §16/§43 — Integration Manager + API health."""

    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("code", name="uq_integration_code"),)

    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    provider: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    base_url: Mapped[str | None] = mapped_column(String(400))
    official_documentation_url: Mapped[str | None] = mapped_column(String(600))
    official_portal_url: Mapped[str | None] = mapped_column(String(600))
    status: Mapped[IntegrationStatus] = mapped_column(
        _enum(IntegrationStatus), default=IntegrationStatus.NOT_CONNECTED, nullable=False, index=True
    )
    credentials_configured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approval_status_text: Mapped[str | None] = mapped_column(String(200))
    authentication_state: Mapped[str | None] = mapped_column(String(120))
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    manual_workflow_url: Mapped[str | None] = mapped_column(String(600))
    manual_workflow_text: Mapped[str | None] = mapped_column(Text)
    last_successful_request_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_failed_request_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_http_status: Mapped[int | None] = mapped_column(Integer)
    last_error_message: Mapped[str | None] = mapped_column(Text)
    last_health_check_at: Mapped[datetime | None] = mapped_column(DateTime)
    health_check_result: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class IntegrationLog(Base, IdMixin, TimestampMixin):
    __tablename__ = "integration_logs"
    __table_args__ = (Index("ix_intlog_code_result", "integration_code", "result"),)

    integration_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(120), nullable=False)
    result: Mapped[IntegrationCallResult] = mapped_column(
        _enum(IntegrationCallResult), nullable=False
    )
    http_status: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    request_ref: Mapped[str | None] = mapped_column(String(160))
    initiated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


# ═════════════════════════════════════ GOVERNMENT INTEGRATION REGISTRY ══
class GovernmentIntegrationRegistry(Base, IdMixin, TimestampMixin):
    """Master Upgrade Prompt §12 — one authoritative row per provider service.

    `live` is True only when a real, provider-authorized connection has been
    provisioned and verified. Demo rows carry source_type=DEMO and never
    represent a government system."""

    __tablename__ = "gov_integration_registry"
    __table_args__ = (Index("ix_gir_provider_service", "provider_code", "service_name"),)

    provider_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider_name: Mapped[str] = mapped_column(String(240), nullable=False)
    service_name: Mapped[str] = mapped_column(String(240), nullable=False)
    jurisdiction: Mapped[str | None] = mapped_column(String(64))          # CENTRAL / STATE:<code>
    authority: Mapped[str | None] = mapped_column(String(240))
    official_portal_url: Mapped[str | None] = mapped_column(String(500))
    api_directory_url: Mapped[str | None] = mapped_column(String(500))
    api_specification_url: Mapped[str | None] = mapped_column(String(500))
    environment: Mapped[str] = mapped_column(String(32), default="OFFICIAL_REDIRECT", nullable=False)
    authorization_status: Mapped[AuthorizationStatus] = mapped_column(
        _enum(AuthorizationStatus), default=AuthorizationStatus.NOT_AUTHORIZED, nullable=False, index=True
    )
    supported_operations: Mapped[list[str]] = mapped_column(JSON, default=list)
    authentication_method: Mapped[str | None] = mapped_column(String(120))
    schema_version: Mapped[str | None] = mapped_column(String(32))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    fallback_mode: Mapped[IntegrationMode] = mapped_column(
        _enum(IntegrationMode), default=IntegrationMode.OFFICIAL_REDIRECT, nullable=False
    )
    data_categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    consent_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    live: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_type: Mapped[str] = mapped_column(String(48), default="NOT_VERIFIED", nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


# ══════════════════════════ CONSENT & GOVERNMENT DATA REFERENCES ══
class ConsentRecord(Base, IdMixin, TimestampMixin):
    """Master upgrade §7 — explicit, revocable consent before any government
    data/document exchange. Nothing is retrieved without a GRANTED consent
    row referenced by the operation."""

    __tablename__ = "consent_records"
    __table_args__ = (Index("ix_consent_user_status", "user_id", "status"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    service: Mapped[str] = mapped_column(String(240), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    data_categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    documents_requested: Mapped[list[str]] = mapped_column(JSON, default=list)
    integration_mode: Mapped[str] = mapped_column(String(32), default="PENDING_AUTHORIZATION", nullable=False)
    status: Mapped[ConsentStatus] = mapped_column(
        _enum(ConsentStatus), default=ConsentStatus.GRANTED, nullable=False, index=True
    )
    granted_at: Mapped[datetime | None] = mapped_column(DateTime)
    expiry: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    consent_text_shown: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class GovDataReference(Base, IdMixin, TimestampMixin):
    """A government dataset match the USER selected (never auto-applied):
    UDYAM dataset match, MCA company match, pincode lookup result. Stored with
    full provenance; enrichment feeds the regulatory digital twin as input."""

    __tablename__ = "gov_data_references"
    __table_args__ = (Index("ix_gdr_project_provider", "project_id", "provider"),)

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"))
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    service: Mapped[str] = mapped_column(String(240), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(160), index=True)
    display_name: Mapped[str | None] = mapped_column(String(300))
    verification_status: Mapped[str] = mapped_column(String(48), default="NOT_VERIFIED", nullable=False)
    match_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enrichment: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    integration_mode: Mapped[str] = mapped_column(String(32), default="NOT_AVAILABLE", nullable=False)
    selected_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    matched_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


# ════════════════════════════════════════ DECISION TRAIL (MVP §G) ══
class DecisionTrail(Base, IdMixin, TimestampMixin):
    """Immutable record of one deterministic rule evaluation, so the user can
    always ask WHY / WHAT EVIDENCE / WHICH RULE / WHAT IS MISSING. Written by
    the approval engine on every discovery run; never edited afterwards."""

    __tablename__ = "decision_trail"
    __table_args__ = (Index("ix_dt_project_template", "project_id", "approval_template_code"),)

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    approval_template_code: Mapped[str | None] = mapped_column(String(64), index=True)
    approval_name: Mapped[str | None] = mapped_column(String(240))
    authority: Mapped[str | None] = mapped_column(String(240))
    rule_key: Mapped[str | None] = mapped_column(String(160))
    rule_expression: Mapped[str | None] = mapped_column(Text)
    result: Mapped[str] = mapped_column(String(40), nullable=False)  # APPLIES/CONDITIONAL/NOT_APPLICABLE/INFORMATION_REQUIRED/REQUIRES_VERIFICATION
    triggering_facts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    missing_facts: Mapped[list[str]] = mapped_column(JSON, default=list)
    explanation: Mapped[str | None] = mapped_column(Text)
    legal_basis: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_url: Mapped[str | None] = mapped_column(String(500))
    source_status: Mapped[str | None] = mapped_column(String(48))
    rule_version: Mapped[str | None] = mapped_column(String(64))
    engine_version: Mapped[str | None] = mapped_column(String(64))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


# ══════════════════════════════════════════════════════ NOTIFICATIONS ══
class Notification(Base, IdMixin, TimestampMixin):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notif_user_read", "user_id", "read_at"),
        Index("ix_notif_project", "project_id"),
    )

    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    channel: Mapped[NotificationChannel] = mapped_column(
        _enum(NotificationChannel), default=NotificationChannel.IN_APP, nullable=False, index=True
    )
    notification_type: Mapped[NotificationType] = mapped_column(_enum(NotificationType), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16), default="INFO", nullable=False, index=True)
    link: Mapped[str | None] = mapped_column(String(400))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(160), index=True)
    email_status: Mapped[EmailDeliveryStatus] = mapped_column(
        _enum(EmailDeliveryStatus), default=EmailDeliveryStatus.NOT_CONFIGURED, nullable=False
    )
    email_error: Mapped[str | None] = mapped_column(Text)
    browser_push_status: Mapped[str] = mapped_column(String(32), default="NOT_ATTEMPTED", nullable=False)


# ═══════════════════════════════════════════════════════════════ AUDIT ══
class AuditLog(Base, IdMixin, TimestampMixin):
    """Spec §38."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_user_time", "user_id", "created_at"),
        Index("ix_audit_project_action", "project_id", "action"),
        Index("ix_audit_resource", "resource_type", "resource_id"),
    )

    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    user_email: Mapped[str | None] = mapped_column(String(320))
    action: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    action_category: Mapped[str] = mapped_column(String(48), default="GENERAL", nullable=False, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"), index=True)
    resource_type: Mapped[str | None] = mapped_column(String(64), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), index=True)
    result: Mapped[AuditResult] = mapped_column(
        _enum(AuditResult), default=AuditResult.SUCCESS, nullable=False, index=True
    )
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(400))
    request_id: Mapped[str | None] = mapped_column(String(48), index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(48), index=True)
    integration_mode: Mapped[str | None] = mapped_column(String(32))
    provider: Mapped[str | None] = mapped_column(String(96))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    before: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    after: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    agent: Mapped[str | None] = mapped_column(String(32))
    is_security_event: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)


# ═════════════════════════════════════════════════════════════════ AI ══
class AIConversation(Base, IdMixin, TimestampMixin):
    __tablename__ = "ai_conversations"
    __table_args__ = (Index("ix_conv_user_project", "user_id", "project_id"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    title: Mapped[str] = mapped_column(String(300), default="New conversation", nullable=False)
    channel: Mapped[str] = mapped_column(String(16), default="chat", nullable=False)  # chat | voice
    language: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime)
    context_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    messages: Mapped[list["AIMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="AIMessage.id"
    )


class AIMessage(Base, IdMixin, TimestampMixin):
    __tablename__ = "ai_messages"
    __table_args__ = (Index("ix_msg_conv", "conversation_id"),)

    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[AIMessageRole] = mapped_column(_enum(AIMessageRole), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    structured: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # spec §51 answer format
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    agent: Mapped[AgentName | None] = mapped_column(_enum(AgentName), nullable=True, index=True)
    intent: Mapped[str | None] = mapped_column(String(64), index=True)
    confidence: Mapped[Confidence | None] = mapped_column(_enum(Confidence), nullable=True)
    source_status: Mapped[SourceStatus] = mapped_column(
        _enum(SourceStatus), default=SourceStatus.AI_INTERPRETATION, nullable=False
    )
    tools_used: Mapped[list[str]] = mapped_column(JSON, default=list)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    language: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    spoken: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))

    conversation: Mapped["AIConversation"] = relationship(back_populates="messages")


class VoiceSession(Base, IdMixin, TimestampMixin):
    """Spec §27/§28 — voice interaction telemetry (no audio is stored)."""

    __tablename__ = "voice_sessions"
    __table_args__ = (Index("ix_voice_user_state", "user_id", "state"),)

    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("ai_conversations.id", ondelete="SET NULL"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    state: Mapped[VoiceState] = mapped_column(_enum(VoiceState), default=VoiceState.IDLE, nullable=False, index=True)
    language: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    transcript: Mapped[str | None] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String(64), index=True)
    command: Mapped[str | None] = mapped_column(String(120))
    sensitive_action: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confirmation_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confirmation_result: Mapped[str | None] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(64))
    stt_engine: Mapped[str | None] = mapped_column(String(64))
    tts_engine: Mapped[str | None] = mapped_column(String(64))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)


# ══════════════════════════════════════════════════════════ OFFLINE SYNC ══
class SyncRecord(Base, IdMixin, TimestampMixin):
    """Spec §40 — offline change queue + conflict tracking.

    Conflicts are surfaced to the user for a Keep Local / Keep Server / Review
    decision; nothing is silently overwritten.
    """

    __tablename__ = "sync_records"
    __table_args__ = (
        Index("ix_sync_user_entity", "user_id", "entity_type", "entity_id"),
        Index("ix_sync_state", "state"),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    entity_type: Mapped[str] = mapped_column(String(48), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(48), nullable=False)
    client_id: Mapped[str | None] = mapped_column(String(64), index=True)
    operation: Mapped[str] = mapped_column(String(16), default="UPSERT", nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    server_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    client_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    server_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    base_version: Mapped[int | None] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(24), default="PENDING", nullable=False, index=True)
    resolution: Mapped[SyncConflictResolution | None] = mapped_column(
        _enum(SyncConflictResolution), nullable=True
    )
    conflict_fields: Mapped[list[str]] = mapped_column(JSON, default=list)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)


__all__ = [
    "AIConversation",
    "AIMessage",
    "Application",
    "ApplicationStatusHistory",
    "ApprovalDependencyTemplate",
    "ApprovalRule",
    "ApprovalTemplate",
    "AuditLog",
    "ComplianceTask",
    "GovDataReference"
    "ConsentRecord"
    "Document",
    "DocumentValidation",
    "DocumentVersion",
    "EmailVerificationToken",
    "GovernmentPortal",
    "GovernmentQuery",
    "GovernmentSource",
    "GovernmentIntegrationRegistry",
    "Industry",
    "Inspection",
    "Integration",
    "IntegrationLog",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "Notification",
    "Organization",
    "OrganizationMember",
    "PasswordResetToken",
    "Project",
    "ProjectApproval",
    "ProjectApprovalRequirement",
    "ProjectProfile",
    "QuestionnaireAnswer",
    "RefreshToken",
    "RegulatoryChange",
    "Renewal",
    "Scheme",
    "SchemeEligibility",
    "SubIndustry",
    "SyncRecord",
    "User",
    "UserPreference",
    "VoiceSession",
]
