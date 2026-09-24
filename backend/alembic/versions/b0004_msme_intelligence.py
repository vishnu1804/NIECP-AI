"""MSME intelligence: profile turnover + buyer-side flag.

Revision ID: b0004_msme_intelligence
Revises: b0003_gov_data_services
Create Date: 2026-09-23

Additive only, guarded: project_profiles + annual_turnover, + buys_from_msme_suppliers.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b0004_msme_intelligence"
down_revision = "b0003_gov_data_services"
branch_labels = None
depends_on = None


def _has_col(bind, table: str, col: str) -> bool:
    return col in [c["name"] for c in sa.inspect(bind).get_columns(table)]


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_col(bind, "project_profiles", "annual_turnover"):
        op.add_column("project_profiles", sa.Column("annual_turnover", sa.Numeric(18, 2), nullable=True))
    if not _has_col(bind, "project_profiles", "buys_from_msme_suppliers"):
        op.add_column("project_profiles", sa.Column("buys_from_msme_suppliers", sa.Boolean(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if _has_col(bind, "project_profiles", "buys_from_msme_suppliers"):
        op.drop_column("project_profiles", "buys_from_msme_suppliers")
    if _has_col(bind, "project_profiles", "annual_turnover"):
        op.drop_column("project_profiles", "annual_turnover")
