"""add on_scene_since to units

Revision ID: add_on_scene_since
Revises: add_sprint_features
Create Date: 2026-03-28
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_on_scene_since'
down_revision = 'f7a9c2e1d3b5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('units', sa.Column('on_scene_since', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('units', 'on_scene_since')