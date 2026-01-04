"""create trade_cases, decision_events, thesis_snapshots tables

Revision ID: 0001_core_decision_tables
Revises:
Create Date: 2024-06-13
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_core_decision_tables"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------------------
    # trade_cases
    # ---------------------------------------------------------------------
    op.create_table(
        "trade_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("ticker", sa.String, nullable=False),
        sa.Column("book", sa.String, server_default=sa.text("'default'"), nullable=False),
        sa.Column("status", sa.String, server_default=sa.text("'OPEN'"), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_trade_cases_ticker", "trade_cases", ["ticker"])
    op.create_index("ix_trade_cases_status", "trade_cases", ["status"])

    # ---------------------------------------------------------------------
    # decision_events
    # ---------------------------------------------------------------------
    op.create_table(
        "decision_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("trade_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_decision_events_case_id", "decision_events", ["case_id"])
    op.create_index("ix_decision_events_event_ts", "decision_events", ["event_ts"])
    op.create_index("ix_decision_events_case_id_event_ts", "decision_events", ["case_id", "event_ts"])

    # ---------------------------------------------------------------------
    # thesis_snapshots
    # ---------------------------------------------------------------------
    op.create_table(
        "thesis_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("trade_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("asof_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("compiled_json", postgresql.JSONB, nullable=False),
        sa.Column("narrative", sa.Text, nullable=True),
        sa.Column("model", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_thesis_snapshots_case_id", "thesis_snapshots", ["case_id"])
    op.create_index("ix_thesis_snapshots_asof_ts", "thesis_snapshots", ["asof_ts"])
    op.create_index("ix_thesis_snapshots_case_id_asof_ts", "thesis_snapshots", ["case_id", "asof_ts"])


def downgrade() -> None:
    op.drop_index("ix_thesis_snapshots_case_id_asof_ts", table_name="thesis_snapshots")
    op.drop_index("ix_thesis_snapshots_asof_ts", table_name="thesis_snapshots")
    op.drop_index("ix_thesis_snapshots_case_id", table_name="thesis_snapshots")
    op.drop_table("thesis_snapshots")

    op.drop_index("ix_decision_events_case_id_event_ts", table_name="decision_events")
    op.drop_index("ix_decision_events_event_ts", table_name="decision_events")
    op.drop_index("ix_decision_events_case_id", table_name="decision_events")
    op.drop_table("decision_events")

    op.drop_index("ix_trade_cases_status", table_name="trade_cases")
    op.drop_index("ix_trade_cases_ticker", table_name="trade_cases")
    op.drop_table("trade_cases")
