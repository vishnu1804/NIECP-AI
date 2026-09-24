"""Decision trail (MVP §G): immutable per-rule evaluation records.

Revision ID: b0005_decision_trail
Revises: b0004_msme_intelligence
Create Date: 2026-09-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b0005_decision_trail"
down_revision = "b0004_msme_intelligence"
branch_labels = None
depends_on = None


def _has_table(bind, name: str) -> bool:
    return bool(sa.inspect(bind).has_table(name))


def upgrade() -> None:
    if _has_table(op.get_bind(), "decision_trail"):
        return
    op.create_table(
        "decision_trail",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("approval_template_code", sa.String(64), index=True),
        sa.Column("approval_name", sa.String(240)),
        sa.Column("authority", sa.String(240)),
        sa.Column("rule_key", sa.String(160)),
        sa.Column("rule_expression", sa.Text()),
        sa.Column("result", sa.String(40), nullable=False),
        sa.Column("triggering_facts", sa.JSON(), server_default="{}"),
        sa.Column("missing_facts", sa.JSON(), server_default="[]"),
        sa.Column("explanation", sa.Text()),
        sa.Column("legal_basis", sa.JSON(), server_default="[]"),
        sa.Column("source_url", sa.String(500)),
        sa.Column("source_status", sa.String(48)),
        sa.Column("rule_version", sa.String(64)),
        sa.Column("engine_version", sa.String(64)),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.create_index("ix_dt_project_template", "decision_trail", ["project_id", "approval_template_code"])


def downgrade() -> None:
    if _has_table(op.get_bind(), "decision_trail"):
        op.drop_table("decision_trail")
