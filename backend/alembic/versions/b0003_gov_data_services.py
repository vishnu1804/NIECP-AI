"""Government data services: consent records, dataset references, document origin, profile pincode.

Revision ID: b0003_gov_data_services
Revises: b0002_integration_upgrade
Create Date: 2026-09-22

Additive only, guarded (SQLite non-transactional DDL):
  * + consent_records (ConsentRecord)
  * + gov_data_references (GovDataReference)
  * project_profiles: + pincode
  * documents:        + origin (default USER_UPLOADED), gov_reference_id
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b0003_gov_data_services"
down_revision = "b0002_integration_upgrade"
branch_labels = None
depends_on = None


def _has_col(bind, table: str, col: str) -> bool:
    return col in [c["name"] for c in sa.inspect(bind).get_columns(table)]


def _has_table(bind, table: str) -> bool:
    return sa.inspect(bind).has_table(table)


def _mk_consent_records() -> None:
    return op.create_table(
        "consent_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, index=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("provider", sa.String(length=64), nullable=False, index=True),
        sa.Column("service", sa.String(length=240), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("data_categories", sa.JSON(), nullable=True),
        sa.Column("documents_requested", sa.JSON(), nullable=True),
        sa.Column("integration_mode", sa.String(length=32), nullable=False, server_default="PENDING_AUTHORIZATION"),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="GRANTED", index=True),
        sa.Column("granted_at", sa.DateTime(), nullable=True),
        sa.Column("expiry", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("consent_text_shown", sa.Text(), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def _mk_gov_data_references() -> None:
    op.create_table(
        "gov_data_references",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, index=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False, index=True),
        sa.Column("service", sa.String(length=240), nullable=False),
        sa.Column("external_id", sa.String(length=160), nullable=True, index=True),
        sa.Column("display_name", sa.String(length=300), nullable=True),
        sa.Column("verification_status", sa.String(length=48), nullable=False, server_default="NOT_VERIFIED"),
        sa.Column("match_payload", sa.JSON(), nullable=True),
        sa.Column("enrichment", sa.JSON(), nullable=True),
        sa.Column("integration_mode", sa.String(length=32), nullable=False, server_default="NOT_AVAILABLE"),
        sa.Column("selected_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("matched_at", sa.DateTime(), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_gdr_project_provider", "gov_data_references", ["project_id", "provider"])


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "consent_records"):
        _mk_consent_records()
    if not _has_table(bind, "gov_data_references"):
        _mk_gov_data_references()
    if not _has_col(bind, "project_profiles", "pincode"):
        op.add_column("project_profiles", sa.Column("pincode", sa.String(length=10), nullable=True))
    if not _has_col(bind, "documents", "origin"):
        op.add_column("documents", sa.Column("origin", sa.String(length=64), nullable=True))
        op.execute("UPDATE documents SET origin = 'USER_UPLOADED' WHERE origin IS NULL")
        op.create_index("ix_documents_origin", "documents", ["origin"])
    if not _has_col(bind, "documents", "gov_reference_id"):
        op.add_column("documents", sa.Column("gov_reference_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if _has_col(bind, "documents", "gov_reference_id"):
        op.drop_column("documents", "gov_reference_id")
    if _has_col(bind, "documents", "origin"):
        op.drop_index("ix_documents_origin", table_name="documents")
        op.drop_column("documents", "origin")
    if _has_col(bind, "project_profiles", "pincode"):
        op.drop_column("project_profiles", "pincode")
    if _has_table(bind, "gov_data_references"):
        op.drop_table("gov_data_references")
    if _has_table(bind, "consent_records"):
        op.drop_table("consent_records")
