"""fix_alert_ids_and_indexes

Changes:
  - alerts.id: VARCHAR(32) -> TEXT  (UUID-based IDs are 40 chars; TEXT is unconstrained)
  - alerts.created_at / expires_at: ensure timezone-aware TIMESTAMPTZ
  - Add composite index idx_alert_dedup for simulation dedup query performance
  - existing indexes preserved

Revision ID: a1b2c3d4e5f6
Revises: eb0034e50591
Create Date: 2026-03-27
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "eb0034e50591"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Widen the id column so UUID-based IDs (40 chars) fit without truncation
    op.alter_column(
        "alerts", "id",
        existing_type=sa.String(length=32),
        type_=sa.Text(),
        existing_nullable=False,
    )

    # Make timestamps timezone-aware
    op.alter_column(
        "alerts", "created_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=False,
    )
    op.alter_column(
        "alerts", "expires_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=True,
    )

    # Add composite dedup index (the hot path in every simulation tick)
    op.create_index(
        "idx_alert_dedup",
        "alerts",
        ["incident_id", "alert_type", "is_acknowledged"],
    )


def downgrade() -> None:
    op.drop_index("idx_alert_dedup", table_name="alerts")

    op.alter_column(
        "alerts", "expires_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        existing_nullable=True,
    )
    op.alter_column(
        "alerts", "created_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        existing_nullable=False,
    )
    op.alter_column(
        "alerts", "id",
        existing_type=sa.Text(),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
