"""unit_lat_lon_float

Revision ID: eb0034e50591
Revises: 1015836168e1
Create Date: 2026-03-27 03:09:37.854803
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'eb0034e50591'
down_revision: Union[str, Sequence[str], None] = '1015836168e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ✅ FIXED: add USING for BOTH columns
    op.alter_column(
        'units',
        'latitude',
        existing_type=sa.String(),
        type_=sa.Float(),
        existing_nullable=True,
        postgresql_using='latitude::double precision'
    )

    op.alter_column(
        'units',
        'longitude',
        existing_type=sa.String(),
        type_=sa.Float(),
        existing_nullable=True,
        postgresql_using='longitude::double precision'
    )

    # New GPS fields
    op.add_column('units', sa.Column('gps_accuracy_m', sa.Float(), nullable=True))
    op.add_column('units', sa.Column('gps_source', sa.String(), nullable=True))
    op.add_column('units', sa.Column('gps_updated_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    # Remove new fields
    op.drop_column('units', 'gps_updated_at')
    op.drop_column('units', 'gps_source')
    op.drop_column('units', 'gps_accuracy_m')

    # ✅ FIXED: reverse cast (float → string)
    op.alter_column(
        'units',
        'latitude',
        existing_type=sa.Float(),
        type_=sa.String(),
        existing_nullable=True,
        postgresql_using='latitude::text'
    )

    op.alter_column(
        'units',
        'longitude',
        existing_type=sa.Float(),
        type_=sa.String(),
        existing_nullable=True,
        postgresql_using='longitude::text'
    )