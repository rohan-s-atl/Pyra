"""add_sprint_features

New tables and columns added in this development sprint:

  Tables:
    - shift_briefings          — stores AI shift handoff briefings
    - recommendation_feedback  — stores dispatcher accept/reject/override feedback

  Columns:
    - units.ics_type           — ICS resource type string (Type 1, Type 2, etc.)

  Indexes:
    - idx_shift_briefing_incident_time
    - idx_rec_feedback_incident
    - idx_rec_feedback_outcome

Revision ID: f7a9c2e1d3b5
Revises: a1b2c3d4e5f6
Create Date: 2026-03-28 00:00:00
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'f7a9c2e1d3b5'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── shift_briefings table ──────────────────────────────────────────────────
    op.create_table(
        'shift_briefings',
        sa.Column('id',           sa.String(), nullable=False),
        sa.Column('incident_id',  sa.String(), nullable=False),
        sa.Column('generated_at', sa.DateTime(), nullable=False),
        sa.Column('generated_by', sa.String(), nullable=True),
        sa.Column('trigger',      sa.String(), nullable=False, server_default='manual'),
        sa.Column('period_hours', sa.String(), nullable=False, server_default='12'),
        sa.Column('content',      sa.Text(),   nullable=False),
        sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_shift_briefing_incident_time', 'shift_briefings',
                    ['incident_id', 'generated_at'])
    op.create_index(op.f('ix_shift_briefings_id'), 'shift_briefings', ['id'])
    op.create_index(op.f('ix_shift_briefings_incident_id'), 'shift_briefings', ['incident_id'])
    op.create_index(op.f('ix_shift_briefings_generated_at'), 'shift_briefings', ['generated_at'])

    # ── recommendation_feedback table ─────────────────────────────────────────
    op.create_table(
        'recommendation_feedback',
        sa.Column('id',                   sa.String(), nullable=False),
        sa.Column('incident_id',          sa.String(), nullable=False),
        sa.Column('recommendation_id',    sa.String(), nullable=True),
        sa.Column('actor',                sa.String(), nullable=False),
        sa.Column('actor_role',           sa.String(), nullable=True),
        sa.Column('outcome',              sa.String(), nullable=False),
        sa.Column('override_unit_ids',    sa.Text(),   nullable=True),
        sa.Column('reason',               sa.Text(),   nullable=True),
        sa.Column('confidence_reported',  sa.String(), nullable=True),
        sa.Column('recorded_at',          sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['incident_id'], ['incidents.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_rec_feedback_incident', 'recommendation_feedback',
                    ['incident_id', 'recorded_at'])
    op.create_index('idx_rec_feedback_outcome', 'recommendation_feedback', ['outcome'])
    op.create_index(op.f('ix_recommendation_feedback_id'), 'recommendation_feedback', ['id'])
    op.create_index(op.f('ix_recommendation_feedback_recorded_at'),
                    'recommendation_feedback', ['recorded_at'])

    # ── units.ics_type column ──────────────────────────────────────────────────
    op.add_column('units', sa.Column('ics_type', sa.String(), nullable=True))
    op.create_index(op.f('ix_units_ics_type'), 'units', ['ics_type'])

    # ── Additional performance indexes (safe, idempotent) ──────────────────────
    conn = op.get_bind()
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_recommendations_incident_generated "
        "ON recommendations (incident_id, generated_at)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_alert_incident_ack "
        "ON alerts (incident_id, is_acknowledged)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_audit_actor_action "
        "ON audit_logs (actor, action)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_unit_position "
        "ON units (latitude, longitude)"
    ))


def downgrade() -> None:
    # Remove indexes first
    op.drop_index('idx_shift_briefing_incident_time', table_name='shift_briefings')
    op.drop_index(op.f('ix_shift_briefings_generated_at'), table_name='shift_briefings')
    op.drop_index(op.f('ix_shift_briefings_incident_id'), table_name='shift_briefings')
    op.drop_index(op.f('ix_shift_briefings_id'), table_name='shift_briefings')
    op.drop_table('shift_briefings')

    op.drop_index('idx_rec_feedback_outcome', table_name='recommendation_feedback')
    op.drop_index('idx_rec_feedback_incident', table_name='recommendation_feedback')
    op.drop_index(op.f('ix_recommendation_feedback_recorded_at'), table_name='recommendation_feedback')
    op.drop_index(op.f('ix_recommendation_feedback_id'), table_name='recommendation_feedback')
    op.drop_table('recommendation_feedback')

    op.drop_index(op.f('ix_units_ics_type'), table_name='units')
    op.drop_column('units', 'ics_type')

    try:
        op.drop_index('idx_recommendations_incident_generated', table_name='recommendations')
        op.drop_index('idx_alert_incident_ack', table_name='alerts')
        op.drop_index('idx_audit_actor_action', table_name='audit_logs')
        op.drop_index('idx_unit_position', table_name='units')
    except Exception:
        pass