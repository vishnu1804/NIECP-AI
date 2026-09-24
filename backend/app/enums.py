"""Central enums / controlled vocabularies.

Kept in one module so the API, rule engine and frontend share identical values.
"""
from __future__ import annotations

import enum


class StrEnum(str, enum.Enum):
    def __str__(self) -> str:  # stable JSON serialization
        return self.value


# ------------------------------------------------------------------ identity
class PlatformRole(StrEnum):
    """Spec §2 — role-based access at platform level."""

    APPLICANT = "APPLICANT"
    ENTREPRENEUR = "ENTREPRENEUR"
    MSME = "MSME"
    CONSULTANT = "CONSULTANT"
    COMPLIANCE_MANAGER = "COMPLIANCE_MANAGER"
    ORGANIZATION_ADMIN = "ORGANIZATION_ADMIN"
    REVIEWER = "REVIEWER"
    SYSTEM_ADMIN = "SYSTEM_ADMIN"


class OrgRole(StrEnum):
    """Spec §33 — permissions inside an organization."""

    ADMIN = "ADMIN"            # full access
    MANAGER = "MANAGER"        # project/application management
    EMPLOYEE = "EMPLOYEE"      # assigned tasks
    VIEWER = "VIEWER"          # read-only


class AccountStatus(StrEnum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DELETED = "DELETED"


# ------------------------------------------------------------------ projects
class ProjectStage(StrEnum):
    IDEA = "IDEA"
    PLANNING = "PLANNING"
    LAND_IDENTIFIED = "LAND_IDENTIFIED"
    APPROVALS_IN_PROGRESS = "APPROVALS_IN_PROGRESS"
    CONSTRUCTION = "CONSTRUCTION"
    PRE_OPERATIONAL = "PRE_OPERATIONAL"
    OPERATIONAL = "OPERATIONAL"
    EXPANSION = "EXPANSION"
    CLOSURE = "CLOSURE"


class ProjectType(StrEnum):
    NEW = "NEW"
    EXPANSION = "EXPANSION"
    MODIFICATION = "MODIFICATION"
    RELOCATION = "RELOCATION"
    CHANGE_OF_USE = "CHANGE_OF_USE"


class OrganizationType(StrEnum):
    INDIVIDUAL = "INDIVIDUAL"
    PROPRIETORSHIP = "PROPRIETORSHIP"
    PARTNERSHIP = "PARTNERSHIP"
    LLP = "LLP"
    PRIVATE_LIMITED = "PRIVATE_LIMITED"
    PUBLIC_LIMITED = "PUBLIC_LIMITED"
    COOPERATIVE = "COOPERATIVE"
    TRUST_SOCIETY = "TRUST_SOCIETY"
    PSU = "PSU"
    OTHER = "OTHER"


class EnterpriseClass(StrEnum):
    STARTUP = "STARTUP"
    MICRO = "MICRO"
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    MSME_UNREGISTERED = "MSME_UNREGISTERED"
    LARGE = "LARGE"
    UNKNOWN = "UNKNOWN"


class LandTenure(StrEnum):
    OWNED = "OWNED"
    LEASED_PRIVATE = "LEASED_PRIVATE"
    LEASED_GOVERNMENT = "LEASED_GOVERNMENT"
    INDUSTRIAL_PARK_ALLOTMENT = "INDUSTRIAL_PARK_ALLOTMENT"
    SEZ = "SEZ"
    PENDING = "PENDING"
    NOT_APPLICABLE = "NOT_APPLICABLE"


# ------------------------------------------------------- information provenance
class SourceStatus(StrEnum):
    """Spec §6/§37 — every claim carries where it came from."""

    VERIFIED_GOV_SOURCE = "VERIFIED_GOV_SOURCE"
    OFFICIAL_API = "OFFICIAL_API"
    USER_PROVIDED = "USER_PROVIDED"
    AI_INTERPRETATION = "AI_INTERPRETATION"
    REQUIRES_VERIFICATION = "REQUIRES_VERIFICATION"
    INFORMATION_UNAVAILABLE = "INFORMATION_UNAVAILABLE"
    DEMO = "DEMO"


class Confidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    REQUIRES_VERIFICATION = "REQUIRES_VERIFICATION"
    UNKNOWN = "UNKNOWN"


class ConsentStatus(StrEnum):
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    PENDING = "PENDING"


# ----------------------------------------------------------------- approvals
class ApprovalCategory(StrEnum):
    BUSINESS = "BUSINESS"
    LAND = "LAND"
    ENVIRONMENT = "ENVIRONMENT"
    SAFETY = "SAFETY"
    LABOUR = "LABOUR"
    INDUSTRY_SPECIFIC = "INDUSTRY_SPECIFIC"
    TAX = "TAX"
    UTILITIES = "UTILITIES"
    TRADE = "TRADE"


class Jurisdiction(StrEnum):
    CENTRAL = "CENTRAL"
    STATE = "STATE"
    LOCAL_BODY = "LOCAL_BODY"
    CENTRAL_AND_STATE = "CENTRAL_AND_STATE"


class Applicability(StrEnum):
    APPLIES = "APPLIES"                    # rule engine matched deterministically
    LIKELY = "LIKELY"                      # rule matched with informational gaps
    CONDITIONAL = "CONDITIONAL"            # depends on answers not yet given
    NOT_APPLICABLE = "NOT_APPLICABLE"      # rule evaluated false
    UNKNOWN = "UNKNOWN"                    # insufficient data — never a guess


class ApprovalNodeState(StrEnum):
    """Spec §11 dependency-graph node states."""

    COMPLETED = "COMPLETED"
    READY = "READY"
    BLOCKED = "BLOCKED"
    WAITING = "WAITING"
    QUERY_RAISED = "QUERY_RAISED"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NOT_STARTED = "NOT_STARTED"


# --------------------------------------------------------------- applications
class ApplicationStatus(StrEnum):
    """Spec §14. Terminal/branch states included. USER_CONFIRMED and
    USER_RESPONDED were added for the demo execution workflow (§8)."""

    DRAFT = "DRAFT"
    READY_TO_APPLY = "READY_TO_APPLY"
    USER_CONFIRMED = "USER_CONFIRMED"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    QUERY_RAISED = "QUERY_RAISED"
    USER_RESPONDED = "USER_RESPONDED"
    INSPECTION = "INSPECTION"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"
    RENEWAL_DUE = "RENEWAL_DUE"
    CANCELLED = "CANCELLED"


class IntegrationMode(StrEnum):
    """Master Upgrade Prompt §4 — how an application is executed.

    LIVE/UAT/SANDBOX require a real authorized provider connection which does
    not exist in this deployment; they can only appear when a verified,
    provider-approved integration is actually provisioned."""

    LIVE = "LIVE"
    UAT = "UAT"
    SANDBOX = "SANDBOX"
    OFFICIAL_REDIRECT = "OFFICIAL_REDIRECT"
    MANUAL = "MANUAL"
    DEMO = "DEMO"
    PENDING_AUTHORIZATION = "PENDING_AUTHORIZATION"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class AuthorizationStatus(StrEnum):
    """Master Upgrade Prompt §4 — provider authorization lifecycle."""

    AUTHORIZED = "AUTHORIZED"
    PENDING = "PENDING"
    NOT_AUTHORIZED = "NOT_AUTHORIZED"
    EXPIRED = "EXPIRED"


class SubmissionChannel(StrEnum):
    """How the application actually reached the authority. We never claim
    NIECP-AI submitted something it did not."""

    NOT_SUBMITTED = "NOT_SUBMITTED"
    OFFICIAL_PORTAL_BY_USER = "OFFICIAL_PORTAL_BY_USER"
    OFFLINE_BY_USER = "OFFLINE_BY_USER"
    VERIFIED_API_INTEGRATION = "VERIFIED_API_INTEGRATION"


class QueryStatus(StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    READY = "READY"
    RESPONDED = "RESPONDED"
    CLOSED = "CLOSED"


class InspectionStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FOLLOW_UP_REQUIRED = "FOLLOW_UP_REQUIRED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class TaskStatus(StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    DONE = "DONE"
    SKIPPED = "SKIPPED"


class TaskPriority(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class RenewalStatus(StrEnum):
    UPCOMING = "UPCOMING"
    DUE_SOON = "DUE_SOON"
    OVERDUE = "OVERDUE"
    RENEWED = "RENEWED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


# ------------------------------------------------------------------ documents
class DocumentCategory(StrEnum):
    IDENTITY = "IDENTITY"
    BUSINESS = "BUSINESS"
    LAND = "LAND"
    FINANCIAL = "FINANCIAL"
    TECHNICAL = "TECHNICAL"
    ENVIRONMENTAL = "ENVIRONMENTAL"
    SAFETY = "SAFETY"
    LABOUR = "LABOUR"
    GOVERNMENT_CERTIFICATE = "GOVERNMENT_CERTIFICATE"
    PROJECT_REPORT = "PROJECT_REPORT"
    OTHER = "OTHER"


class DocumentOrigin(StrEnum):
    """Where a document came from. GOVERNMENT_RETRIEVED is only possible via
    an authorized provider (DigiLocker requester) — never simulated."""

    USER_UPLOADED = "USER_UPLOADED"
    GOVERNMENT_RETRIEVED = "GOVERNMENT_RETRIEVED"


class DocumentStatus(StrEnum):
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    VALIDATION_REQUIRED = "VALIDATION_REQUIRED"
    VERIFIED_BY_USER = "VERIFIED_BY_USER"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class ValidationSeverity(StrEnum):
    PASS = "PASS"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    BLOCKING = "BLOCKING"


# --------------------------------------------------------------- integrations
class IntegrationStatus(StrEnum):
    """Spec §16. Never faked."""

    CONNECTED = "CONNECTED"
    NOT_CONNECTED = "NOT_CONNECTED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    API_UNAVAILABLE = "API_UNAVAILABLE"
    MANUAL_MODE = "MANUAL_MODE"
    ERROR = "ERROR"


class IntegrationCallResult(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    SKIPPED_NO_CREDENTIALS = "SKIPPED_NO_CREDENTIALS"
    SKIPPED_DISABLED = "SKIPPED_DISABLED"
    TIMEOUT = "TIMEOUT"


# ---------------------------------------------------------------- notifications
class NotificationChannel(StrEnum):
    IN_APP = "IN_APP"
    EMAIL = "EMAIL"
    BROWSER = "BROWSER"


class NotificationType(StrEnum):
    MISSING_DOCUMENT = "MISSING_DOCUMENT"
    APPLICATION_QUERY = "APPLICATION_QUERY"
    APPLICATION_STATUS_CHANGE = "APPLICATION_STATUS_CHANGE"
    RENEWAL_APPROACHING = "RENEWAL_APPROACHING"
    DEADLINE_APPROACHING = "DEADLINE_APPROACHING"
    REGULATORY_CHANGE = "REGULATORY_CHANGE"
    NEW_TASK = "NEW_TASK"
    INTEGRATION_STATUS = "INTEGRATION_STATUS"
    DOCUMENT_EXPIRY = "DOCUMENT_EXPIRY"
    SYSTEM = "SYSTEM"


class EmailDeliveryStatus(StrEnum):
    NOT_CONFIGURED = "NOT_CONFIGURED"   # honest state — SMTP not provisioned
    QUEUED = "QUEUED"
    SENT = "SENT"
    FAILED = "FAILED"


# ------------------------------------------------------------------------ ai
class AIMessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class VoiceState(StrEnum):
    """Spec §27."""

    IDLE = "IDLE"
    ACTIVATING = "ACTIVATING"
    LISTENING = "LISTENING"
    PROCESSING = "PROCESSING"
    RESPONDING = "RESPONDING"
    ERROR = "ERROR"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    NO_SPEECH = "NO_SPEECH"
    NETWORK_ERROR = "NETWORK_ERROR"
    UNSUPPORTED = "UNSUPPORTED"


class AgentName(StrEnum):
    """Spec §53."""

    STRATEGIST = "STRATEGIST"
    APPROVAL = "APPROVAL"
    COMPLIANCE = "COMPLIANCE"
    DOCUMENT = "DOCUMENT"
    RESEARCH = "RESEARCH"
    APPLICATION = "APPLICATION"
    TRACKING = "TRACKING"
    SCHEME = "SCHEME"
    VOICE = "VOICE"
    DEBUG = "DEBUG"


# ------------------------------------------------------------- change radar
class ChangeType(StrEnum):
    NEW_REGULATION = "NEW_REGULATION"
    CHANGED_REQUIREMENT = "CHANGED_REQUIREMENT"
    NEW_SCHEME = "NEW_SCHEME"
    DEADLINE_CHANGE = "DEADLINE_CHANGE"
    PORTAL_CHANGE = "PORTAL_CHANGE"
    FORM_CHANGE = "FORM_CHANGE"
    RENEWAL_CHANGE = "RENEWAL_CHANGE"


class ChangeVerification(StrEnum):
    VERIFIED_OFFICIAL = "VERIFIED_OFFICIAL"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    UNVERIFIED_REPORT = "UNVERIFIED_REPORT"


# ------------------------------------------------------------------- audit
class AuditResult(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    DENIED = "DENIED"
    PARTIAL = "PARTIAL"


class SyncConflictResolution(StrEnum):
    KEEP_LOCAL = "KEEP_LOCAL"
    KEEP_SERVER = "KEEP_SERVER"
    REVIEW = "REVIEW"
    MERGED = "MERGED"
