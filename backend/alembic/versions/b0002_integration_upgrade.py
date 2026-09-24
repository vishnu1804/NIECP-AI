"""Integration upgrade: execution channels, registry, translator, audit correlation.

Revision ID: b0002_integration_upgrade
Revises: b0001_baseline
Create Date: 2026-09-22

Additive only — no existing column is dropped or rewritten, and every step is
guarded (SQLite ALTERs are non-transactional under Alembic):
  * applications       : + integration_mode, correlation_id, provider
  * audit_logs         : + correlation_id, integration_mode, provider
  * government_queries : + translator
  * + gov_integration_registry (GovernmentIntegrationRegistry)
Existing rows are backfilled honestly: applications were filed/recorded by the
user, so integration_mode='MANUAL'.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b0002_integration_upgrade"
down_revision = "b0001_baseline"
branch_labels = None
depends_on = None


def _has_col(bind, table: str, col: str) -> bool:
    insp = sa.inspect(bind)
    return col in [c["name"] for c in insp.get_columns(table)]


def _has_index(bind, table: str, name: str) -> bool:
    insp = sa.inspect(bind)
    return name in [i["name"] for i in insp.get_indexes(table)]


def _has_table(bind, table: str) -> bool:
    return sa.inspect(bind).has_table(table)


def upgrade() -> None:
    bind = op.get_bind()

    # ── applications ──
    if not _has_col(bind, "applications", "integration_mode"):
        op.add_column("applications", sa.Column("integration_mode", sa.String(length=64), nullable=True))
    if not _has_col(bind, "applications", "correlation_id"):
        op.add_column("applications", sa.Column("correlation_id", sa.String(length=48), nullable=True))
    if not _has_col(bind, "applications", "provider"):
        op.add_column("applications", sa.Column("provider", sa.String(length=96), nullable=True))
    op.execute("UPDATE applications SET integration_mode = 'MANUAL' WHERE integration_mode IS NULL")
    if not _has_index(bind, "applications", "ix_applications_integration_mode"):
        op.create_index("ix_applications_integration_mode", "applications", ["integration_mode"])
    if not _has_index(bind, "applications", "ix_applications_correlation_id"):
        op.create_index("ix_applications_correlation_id", "applications", ["correlation_id"])

    # ── audit_logs ──
    if not _has_col(bind, "audit_logs", "correlation_id"):
        op.add_column("audit_logs", sa.Column("correlation_id", sa.String(length=48), nullable=True))
    if not _has_col(bind, "audit_logs", "integration_mode"):
        op.add_column("audit_logs", sa.Column("integration_mode", sa.String(length=32), nullable=True))
    if not _has_col(bind, "audit_logs", "provider"):
        op.add_column("audit_logs", sa.Column("provider", sa.String(length=96), nullable=True))
    if not _has_index(bind, "audit_logs", "ix_audit_logs_correlation_id"):
        op.create_index("ix_audit_logs_correlation_id", "audit_logs", ["correlation_id"])

    # ── government_queries ──
    if not _has_col(bind, "government_queries", "translator"):
        op.add_column("government_queries", sa.Column("translator", sa.JSON(), nullable=True))

    # ── gov_integration_registry ──
    if not _has_table(bind, "gov_integration_registry"):
        op.create_table(
            "gov_integration_registry",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, index=True),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("provider_code", sa.String(length=64), nullable=False, index=True),
            sa.Column("provider_name", sa.String(length=240), nullable=False),
            sa.Column("service_name", sa.String(length=240), nullable=False),
            sa.Column("jurisdiction", sa.String(length=64), nullable=True),
            sa.Column("authority", sa.String(length=240), nullable=True),
            sa.Column("official_portal_url", sa.String(length=500), nullable=True),
            sa.Column("api_directory_url", sa.String(length=500), nullable=True),
            sa.Column("api_specification_url", sa.String(length=500), nullable=True),
            sa.Column("environment", sa.String(length=32), nullable=False, server_default="OFFICIAL_REDIRECT"),
            sa.Column("authorization_status", sa.String(length=64), nullable=False, server_default="NOT_AUTHORIZED"),
            sa.Column("supported_operations", sa.JSON(), nullable=True),
            sa.Column("authentication_method", sa.String(length=120), nullable=True),
            sa.Column("schema_version", sa.String(length=32), nullable=True),
            sa.Column("last_verified_at", sa.DateTime(), nullable=True),
            sa.Column("fallback_mode", sa.String(length=64), nullable=False, server_default="OFFICIAL_REDIRECT"),
            sa.Column("data_categories", sa.JSON(), nullable=True),
            sa.Column("consent_required", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("live", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("source_type", sa.String(length=48), nullable=False, server_default="NOT_VERIFIED"),
            sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("notes", sa.Text(), nullable=True),
        )
        op.create_index("ix_gir_provider_service", "gov_integration_registry", ["provider_code", "service_name"])


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "gov_integration_registry"):
        op.drop_table("gov_integration_registry")
    if _has_col(bind, "government_queries", "translator"):
        op.drop_column("government_queries", "translator")
    if _has_index(bind, "audit_logs", "ix_audit_logs_correlation_id"):
        op.drop_index("ix_audit_logs_correlation_id", table_name="audit_logs")
    for col in ("provider", "integration_mode", "correlation_id"):
        if _has_col(bind, "audit_logs", col):
            op.drop_column("audit_logs", col)
    if _has_index(bind, "applications", "ix_applications_correlation_id"):
        op.drop_index("ix_applications_correlation_id", table_name="applications")
    if _has_index(bind, "applications", "ix_applications_integration_mode"):
        op.drop_index("ix_applications_integration_mode", table_name="applications")
    for col in ("provider", "correlation_id", "integration_mode"):
        if _has_col(bind, "applications", col):
            op.drop_column("applications", col)
