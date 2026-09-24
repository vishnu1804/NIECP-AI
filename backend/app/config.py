"""
NIECP-AI application configuration.

All secrets are read from the environment and never exposed through any API
response or to the frontend bundle. See SECURITY.md for the threat model.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.getenv("NIECP_ENV_FILE", str(BACKEND_ROOT / ".env")),
        env_prefix="NIECP_",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------------------------------------------------------- identity
    app_name: str = "NIECP-AI"
    app_long_name: str = "National Industrial Ease & Compliance Platform — AI"
    environment: str = Field(default="development")
    version: str = Field(default="1.0.0")
    api_prefix: str = Field(default="/api/v1")

    # ---------------------------------------------------------------- database
    # PostgreSQL is the production target. When no PostgreSQL server is reachable
    # the platform falls back to SQLite so that persistence still works (and is
    # still real, on-disk persistence). The active backend is reported by
    # GET /api/v1/system/health so nothing is hidden from operators or users.
    database_url: str = Field(
        default=f"sqlite:///{BACKEND_ROOT / 'niecp.db'}"
    )
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # ---------------------------------------------------------------- security
    # A development default exists so the app can boot; production refuses to
    # start with it (validated below) unless NIECP_ALLOW_INSECURE_DEFAULTS=1.
    secret_key: str = Field(default="dev-only-insecure-secret-change-me")
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60
    refresh_token_days: int = 14
    password_min_length: int = 10
    bcrypt_rounds: int = 12
    allow_insecure_defaults: bool = False

    cors_origins: str = "*"
    trusted_proxy_hosts: str = ""

    # ------------------------------------------------------------------- files
    storage_dir: str = Field(default=str(BACKEND_ROOT / "storage"))
    max_upload_mb: int = 25
    allowed_upload_extensions: str = (
        ".pdf,.jpg,.jpeg,.png,.webp,.doc,.docx,.xls,.xlsx,.csv,.txt,.xml,.zip"
    )

    # ---------------------------------------------------------------------- ai
    # NIECP-AI ships with a deterministic rule engine plus a local retrieval
    # (RAG) stack that always works. An external LLM is optional: if no key is
    # configured the assistant answers from the local rule/knowledge engine and
    # says so explicitly. We never pretend an external model was consulted.
    llm_provider: str = Field(default="none")  # none | openai | azure_openai
    llm_api_key: str = Field(default="")
    llm_base_url: str = Field(default="https://api.openai.com/v1")
    llm_model: str = Field(default="gpt-4o-mini")
    llm_timeout_seconds: int = 25
    rag_top_k: int = 6
    embedding_dim: int = 512

    # ------------------------------------------------------- gov integrations
    # Credentials for API Setu / NSWS / DigiLocker / MyScheme etc. are supplied
    # by the deploying agency. Without them the Integration Manager reports
    # NOT_CONNECTED / MANUAL_MODE and the UI offers the official portal link.
    # We never simulate a successful government API response.
    apisetu_client_id: str = ""
    apisetu_client_secret: str = ""
    apisetu_base_url: str = "https://api.apisetu.gov.in"
    digilocker_client_id: str = ""
    digilocker_client_secret: str = ""
    digilocker_base_url: str = "https://api.digilocker.gov.in"
    myscheme_api_key: str = ""
    enable_outbound_gov_calls: bool = False

    # ------------------------------------------------------ gov data providers
    # All credentials live here, server-side only (Master Upgrade Prompt §2).
    # They are NEVER serialized to the frontend — payloads carry status and
    # results only. Empty string = not provisioned = honest PENDING state.
    data_gov_api_key: str = Field(default="", description="data.gov.in API key (free registration at data.gov.in/api). Not provisioned by default.")
    data_gov_udyaam_resource_id: str = Field(default="", description="data.gov.in resource id of the UDYAM/MSME dataset — set by the deploying agency from the dataset page.")
    data_gov_pincode_resource_id: str = Field(default="", description="data.gov.in resource id of the India Post pincode dataset.")
    data_gov_mca_resource_id: str = Field(default="", description="data.gov.in resource id of the MCA Company Master Data (RoC-wise) public dataset.")
    data_gov_cpcb_air_resource_id: str = Field(default="", description="data.gov.in resource id of the CPCB real-time air quality dataset.")
    data_gov_surface_water_resource_id: str = Field(default="", description="data.gov.in resource id of the CPCB surface water quality (historical) dataset.")
    data_gov_asi_resource_id: str = Field(default="", description="data.gov.in resource id of the Annual Survey of Industries / factory-sector dataset.")
    data_gov_cache_ttl_seconds: int = Field(default=300, description="Short TTL for caching PUBLIC dataset responses (pincode/UDYAM/MCA/CPCB). Only public data is cached — never credentials or private payloads.")
    data_gov_base_url: str = Field(default="https://api.data.gov.in/resource")
    mca_api_base_url: str = Field(default="", description="MCA API base URL — only when MCA authorizes programmatic access.")
    mca_client_id: str = ""
    mca_client_secret: str = ""
    nsws_client_id: str = ""
    nsws_client_secret: str = ""
    gov_api_timeout_seconds: int = Field(default=12, description="Per-attempt timeout for government API calls.")
    gov_api_max_retries: int = Field(default=1, description="Retries on timeout/network error (never on 4xx).")

    # ------------------------------------------------------ demo government
    # The DemoGovernmentAdapter is an INTERNAL NIECP demonstration system. It
    # produces synthetic data only and is never connected to a government API.
    allow_demo_workflows: bool = Field(default=True, description="Demo government workflow availability (hard-disabled in production deployments unless explicitly re-enabled).")
    demo_allow_in_production: bool = Field(default=False, description="Production deployments never expose the demo workflow unless this is explicitly set.")
    demo_dwell_seconds: int = Field(default=3, description="Simulated review dwell between automatic demo status transitions.")

    # ----------------------------------------------------------- notifications
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@niecp.example.gov.in"
    email_enabled: bool = False  # never silently claims mail was delivered

    rate_limit_per_minute: int = 240
    audit_retention_days: int = 2555  # ~7 years

    @field_validator("cors_origins")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_extensions(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_upload_extensions.split(",")}

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    def validate_production_readiness(self) -> list[str]:
        """Returns human-readable blockers. Never raises so /system/health can
        report them to operators."""
        problems: list[str] = []
        if self.is_production:
            if self.secret_key == "dev-only-insecure-secret-change-me":
                problems.append("NIECP_SECRET_KEY must be set in production")
            if self.is_sqlite:
                problems.append(
                    "NIECP_DATABASE_URL should point at PostgreSQL in production"
                )
            if self.cors_origins == "*":
                problems.append("NIECP_CORS_ORIGINS must not be '*' in production")
        return problems


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    Path(s.storage_dir).mkdir(parents=True, exist_ok=True)
    (Path(s.storage_dir) / "documents").mkdir(parents=True, exist_ok=True)
    return s


settings = get_settings()
