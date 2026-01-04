# alembic/versions/0002_decision_events_status.py
from alembic import op
import sqlalchemy as sa

revision = "0002_decision_events_status"
down_revision = "0001_core_decision_tables"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "decision_events",
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'FINAL'")),
    )
    op.add_column(
        "decision_events",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # Backfill deterministically (harmless even if no NULLs exist)
    op.execute("UPDATE decision_events SET updated_at = created_at;")

    op.create_index(
        "ix_decision_events_case_type_status",
        "decision_events",
        ["case_id", "event_type", "status"],
        unique=False,
    )

    # Optional but recommended: enforce one draft per (case_id, event_type)
    op.create_index(
        "ux_decision_events_one_draft",
        "decision_events",
        ["case_id", "event_type"],
        unique=True,
        postgresql_where=sa.text("status = 'DRAFT'"),
    )


def downgrade():
    op.drop_index("ux_decision_events_one_draft", table_name="decision_events")
    op.drop_index("ix_decision_events_case_type_status", table_name="decision_events")
    op.drop_column("decision_events", "updated_at")
    op.drop_column("decision_events", "status")
