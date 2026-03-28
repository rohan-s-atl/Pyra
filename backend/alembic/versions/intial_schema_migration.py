"""initial_schema

Revision ID: 1015836168e1
Revises: 
Create Date: 2026-03-27 02:53:05.471459

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1015836168e1'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('audit_logs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('timestamp', sa.DateTime(), nullable=False),
    sa.Column('action', sa.String(), nullable=False),
    sa.Column('actor', sa.String(), nullable=False),
    sa.Column('actor_role', sa.String(), nullable=False),
    sa.Column('incident_id', sa.String(), nullable=True),
    sa.Column('incident_name', sa.String(), nullable=True),
    sa.Column('unit_ids', sa.Text(), nullable=True),
    sa.Column('details', sa.Text(), nullable=True),
    sa.Column('checksum', sa.String(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_logs_id', 'audit_logs', ['id'], unique=False)
    op.create_index('ix_audit_logs_timestamp', 'audit_logs', ['timestamp'], unique=False)

    op.create_table('incidents',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('fire_type', sa.String(), nullable=False),
    sa.Column('severity', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('spread_risk', sa.String(), nullable=False),
    sa.Column('latitude', sa.Float(), nullable=False),
    sa.Column('longitude', sa.Float(), nullable=False),
    sa.Column('acres_burned', sa.Float(), nullable=True),
    sa.Column('spread_direction', sa.String(), nullable=True),
    sa.Column('wind_speed_mph', sa.Float(), nullable=True),
    sa.Column('humidity_percent', sa.Float(), nullable=True),
    sa.Column('containment_percent', sa.Float(), nullable=True),
    sa.Column('structures_threatened', sa.Integer(), nullable=True),
    sa.Column('started_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('notes', sa.String(), nullable=True),
    sa.Column('elevation_m', sa.Float(), nullable=True),
    sa.Column('slope_percent', sa.Float(), nullable=True),
    sa.Column('aspect_cardinal', sa.String(), nullable=True),
    sa.Column('aqi', sa.Integer(), nullable=True),
    sa.Column('aqi_category', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_incident_location', 'incidents', ['latitude', 'longitude'], unique=False)
    op.create_index('idx_incident_status_severity', 'incidents', ['status', 'severity'], unique=False)
    op.create_index('ix_incidents_fire_type', 'incidents', ['fire_type'], unique=False)
    op.create_index('ix_incidents_id', 'incidents', ['id'], unique=False)
    op.create_index('ix_incidents_severity', 'incidents', ['severity'], unique=False)
    op.create_index('ix_incidents_spread_risk', 'incidents', ['spread_risk'], unique=False)
    op.create_index('ix_incidents_started_at', 'incidents', ['started_at'], unique=False)
    op.create_index('ix_incidents_status', 'incidents', ['status'], unique=False)
    op.create_index('ix_incidents_updated_at', 'incidents', ['updated_at'], unique=False)

    op.create_table('stations',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('cad_name', sa.String(), nullable=True),
    sa.Column('unit_code', sa.String(), nullable=True),
    sa.Column('station_type', sa.String(), nullable=True),
    sa.Column('latitude', sa.Float(), nullable=False),
    sa.Column('longitude', sa.Float(), nullable=False),
    sa.Column('address', sa.String(), nullable=True),
    sa.Column('city', sa.String(), nullable=True),
    sa.Column('phone', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_stations_id', 'stations', ['id'], unique=False)

    op.create_table('users',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('username', sa.String(), nullable=False),
    sa.Column('hashed_password', sa.String(), nullable=False),
    sa.Column('role', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_users_id', 'users', ['id'], unique=False)
    op.create_index('ix_users_username', 'users', ['username'], unique=True)

    op.create_table('alerts',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('incident_id', sa.String(), nullable=False),
    sa.Column('alert_type', sa.String(), nullable=False),
    sa.Column('severity', sa.String(), nullable=False),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('description', sa.String(), nullable=False),
    sa.Column('is_acknowledged', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_alert_incident_ack', 'alerts', ['incident_id', 'is_acknowledged'], unique=False)
    op.create_index('idx_alert_severity_created', 'alerts', ['severity', 'created_at'], unique=False)
    op.create_index('ix_alerts_alert_type', 'alerts', ['alert_type'], unique=False)
    op.create_index('ix_alerts_created_at', 'alerts', ['created_at'], unique=False)
    op.create_index('ix_alerts_expires_at', 'alerts', ['expires_at'], unique=False)
    op.create_index('ix_alerts_id', 'alerts', ['id'], unique=False)
    op.create_index('ix_alerts_incident_id', 'alerts', ['incident_id'], unique=False)
    op.create_index('ix_alerts_is_acknowledged', 'alerts', ['is_acknowledged'], unique=False)
    op.create_index('ix_alerts_severity', 'alerts', ['severity'], unique=False)

    op.create_table('recommendations',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('incident_id', sa.String(), nullable=False),
    sa.Column('generated_at', sa.DateTime(), nullable=False),
    sa.Column('confidence', sa.String(), nullable=False),
    sa.Column('loadout_profile', sa.String(), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('tactical_notes', sa.Text(), nullable=True),
    sa.Column('unit_recommendations_json', sa.Text(), nullable=True),
    sa.Column('route_options_json', sa.Text(), nullable=True),
    sa.Column('resource_recommendations_json', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_recommendations_id', 'recommendations', ['id'], unique=False)
    op.create_index('ix_recommendations_incident_id', 'recommendations', ['incident_id'], unique=False)

    op.create_table('resources',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('resource_type', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('latitude', sa.Float(), nullable=False),
    sa.Column('longitude', sa.Float(), nullable=False),
    sa.Column('incident_id', sa.String(), nullable=True),
    sa.Column('capacity_notes', sa.String(), nullable=True),
    sa.Column('access_notes', sa.String(), nullable=True),
    sa.Column('contact', sa.String(), nullable=True),
    sa.Column('last_updated', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_resources_id', 'resources', ['id'], unique=False)
    op.create_index('ix_resources_incident_id', 'resources', ['incident_id'], unique=False)

    op.create_table('routes',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('incident_id', sa.String(), nullable=False),
    sa.Column('label', sa.String(), nullable=False),
    sa.Column('rank', sa.String(), nullable=False),
    sa.Column('origin_label', sa.String(), nullable=False),
    sa.Column('destination_label', sa.String(), nullable=False),
    sa.Column('origin_lat', sa.Float(), nullable=False),
    sa.Column('origin_lon', sa.Float(), nullable=False),
    sa.Column('destination_lat', sa.Float(), nullable=False),
    sa.Column('destination_lon', sa.Float(), nullable=False),
    sa.Column('estimated_travel_minutes', sa.Integer(), nullable=True),
    sa.Column('distance_miles', sa.Float(), nullable=True),
    sa.Column('terrain_accessibility', sa.String(), nullable=False),
    sa.Column('fire_exposure_risk', sa.String(), nullable=False),
    sa.Column('safety_rating', sa.String(), nullable=False),
    sa.Column('is_currently_passable', sa.Boolean(), nullable=True),
    sa.Column('notes', sa.String(), nullable=True),
    sa.Column('last_verified_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_routes_id', 'routes', ['id'], unique=False)
    op.create_index('ix_routes_incident_id', 'routes', ['incident_id'], unique=False)

    op.create_table('units',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('designation', sa.String(), nullable=False),
    sa.Column('unit_type', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('station_id', sa.String(), nullable=True),
    sa.Column('assigned_incident_id', sa.String(), nullable=True),
    sa.Column('latitude', sa.String(), nullable=True),
    sa.Column('longitude', sa.String(), nullable=True),
    sa.Column('personnel_count', sa.Integer(), nullable=True),
    sa.Column('water_capacity_gallons', sa.Integer(), nullable=True),
    sa.Column('has_structure_protection', sa.Boolean(), nullable=True),
    sa.Column('has_air_attack', sa.Boolean(), nullable=True),
    sa.Column('last_updated', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['assigned_incident_id'], ['incidents.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_unit_incident_status', 'units', ['assigned_incident_id', 'status'], unique=False)
    op.create_index('idx_unit_type_status', 'units', ['unit_type', 'status'], unique=False)
    op.create_index('ix_units_assigned_incident_id', 'units', ['assigned_incident_id'], unique=False)
    op.create_index('ix_units_has_air_attack', 'units', ['has_air_attack'], unique=False)
    op.create_index('ix_units_has_structure_protection', 'units', ['has_structure_protection'], unique=False)
    op.create_index('ix_units_id', 'units', ['id'], unique=False)
    op.create_index('ix_units_last_updated', 'units', ['last_updated'], unique=False)
    op.create_index('ix_units_station_id', 'units', ['station_id'], unique=False)
    op.create_index('ix_units_status', 'units', ['status'], unique=False)
    op.create_index('ix_units_unit_type', 'units', ['unit_type'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_unit_type_status', table_name='units')
    op.drop_index('idx_unit_incident_status', table_name='units')
    op.drop_index('ix_units_unit_type', table_name='units')
    op.drop_index('ix_units_status', table_name='units')
    op.drop_index('ix_units_station_id', table_name='units')
    op.drop_index('ix_units_last_updated', table_name='units')
    op.drop_index('ix_units_id', table_name='units')
    op.drop_index('ix_units_has_structure_protection', table_name='units')
    op.drop_index('ix_units_has_air_attack', table_name='units')
    op.drop_index('ix_units_assigned_incident_id', table_name='units')
    op.drop_table('units')

    op.drop_index('ix_routes_incident_id', table_name='routes')
    op.drop_index('ix_routes_id', table_name='routes')
    op.drop_table('routes')

    op.drop_index('ix_resources_incident_id', table_name='resources')
    op.drop_index('ix_resources_id', table_name='resources')
    op.drop_table('resources')

    op.drop_index('ix_recommendations_incident_id', table_name='recommendations')
    op.drop_index('ix_recommendations_id', table_name='recommendations')
    op.drop_table('recommendations')

    op.drop_index('idx_alert_severity_created', table_name='alerts')
    op.drop_index('idx_alert_incident_ack', table_name='alerts')
    op.drop_index('ix_alerts_severity', table_name='alerts')
    op.drop_index('ix_alerts_is_acknowledged', table_name='alerts')
    op.drop_index('ix_alerts_incident_id', table_name='alerts')
    op.drop_index('ix_alerts_id', table_name='alerts')
    op.drop_index('ix_alerts_expires_at', table_name='alerts')
    op.drop_index('ix_alerts_created_at', table_name='alerts')
    op.drop_index('ix_alerts_alert_type', table_name='alerts')
    op.drop_table('alerts')

    op.drop_index('ix_users_username', table_name='users')
    op.drop_index('ix_users_id', table_name='users')
    op.drop_table('users')

    op.drop_index('ix_stations_id', table_name='stations')
    op.drop_table('stations')

    op.drop_index('ix_incidents_updated_at', table_name='incidents')
    op.drop_index('ix_incidents_status', table_name='incidents')
    op.drop_index('ix_incidents_started_at', table_name='incidents')
    op.drop_index('ix_incidents_spread_risk', table_name='incidents')
    op.drop_index('ix_incidents_severity', table_name='incidents')
    op.drop_index('ix_incidents_id', table_name='incidents')
    op.drop_index('ix_incidents_fire_type', table_name='incidents')
    op.drop_index('idx_incident_status_severity', table_name='incidents')
    op.drop_index('idx_incident_location', table_name='incidents')
    op.drop_table('incidents')

    op.drop_index('ix_audit_logs_timestamp', table_name='audit_logs')
    op.drop_index('ix_audit_logs_id', table_name='audit_logs')
    op.drop_table('audit_logs')