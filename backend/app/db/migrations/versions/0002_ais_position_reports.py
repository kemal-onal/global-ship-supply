"""ais_position_reports

Revision ID: 0002_ais_position_reports
Revises: 0001_initial
Create Date: 2026-09-01 15:00:00.000000

Adds the ``ais_position_reports`` table for the AIS data simulator
(see ``backend/sim/`` and ``app/api/v1/internal/ais.py``).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "0002_ais_position_reports"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ais_position_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column(
            "event_type",
            sa.Enum(
                "position_report", "eta_change", "port_arrival",
                "port_departure", "weather_delay", "route_deviation",
                name="aiseventtype",
            ),
            nullable=False,
        ),
        sa.Column("event_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "source",
            sa.Enum("sim", "unknown", name="aissource"),
            nullable=False,
        ),
        sa.Column("mmsi", sa.String(length=9), nullable=False),
        sa.Column("scenario", sa.String(length=100), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("imo", sa.String(length=7), nullable=True),
        sa.Column("vessel_name", sa.String(length=200), nullable=True),
        sa.Column("vessel_type", sa.String(length=50), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("sog", sa.Float(), nullable=True),
        sa.Column("cog", sa.Float(), nullable=True),
        sa.Column("heading", sa.Float(), nullable=True),
        sa.Column("nav_status", sa.String(length=50), nullable=True),
        sa.Column("destination_port_id", sa.String(length=5), nullable=True),
        sa.Column("eta", sa.DateTime(timezone=True), nullable=True),
        sa.Column("draught", sa.Float(), nullable=True),
        sa.Column("flag", sa.String(length=2), nullable=True),
        sa.Column("length", sa.Float(), nullable=True),
        sa.Column("beam", sa.Float(), nullable=True),
        sa.Column("payload", postgresql.JSONB, nullable=True),
        sa.CheckConstraint(
            "lat IS NULL OR (lat >= -90 AND lat <= 90)",
            name="ck_ais_position_reports_lat_in_range",
        ),
        sa.CheckConstraint(
            "lon IS NULL OR (lon >= -180 AND lon <= 180)",
            name="ck_ais_position_reports_lon_in_range",
        ),
        sa.CheckConstraint(
            "mmsi ~ '^[0-9]{9}$'",
            name="ck_ais_position_reports_mmsi_9_digits",
        ),
    )
    op.create_index(
        "ix_ais_position_reports_event_type", "ais_position_reports", ["event_type"]
    )
    op.create_index(
        "ix_ais_position_reports_event_ts", "ais_position_reports", ["event_ts"]
    )
    op.create_index(
        "ix_ais_position_reports_source", "ais_position_reports", ["source"]
    )
    op.create_index(
        "ix_ais_position_reports_mmsi", "ais_position_reports", ["mmsi"]
    )
    op.create_index(
        "ix_ais_position_reports_imo", "ais_position_reports", ["imo"]
    )
    op.create_index(
        "ix_ais_position_reports_scenario", "ais_position_reports", ["scenario"]
    )
    op.create_index(
        "ix_ais_position_reports_destination_port_id",
        "ais_position_reports",
        ["destination_port_id"],
    )
    op.create_index(
        "ix_ais_position_reports_mmsi_event_ts",
        "ais_position_reports",
        ["mmsi", "event_ts"],
    )
    op.create_index(
        "ix_ais_position_reports_event_ts_event_type",
        "ais_position_reports",
        ["event_ts", "event_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_ais_position_reports_event_ts_event_type", table_name="ais_position_reports")
    op.drop_index("ix_ais_position_reports_mmsi_event_ts", table_name="ais_position_reports")
    op.drop_index("ix_ais_position_reports_destination_port_id", table_name="ais_position_reports")
    op.drop_index("ix_ais_position_reports_scenario", table_name="ais_position_reports")
    op.drop_index("ix_ais_position_reports_imo", table_name="ais_position_reports")
    op.drop_index("ix_ais_position_reports_mmsi", table_name="ais_position_reports")
    op.drop_index("ix_ais_position_reports_source", table_name="ais_position_reports")
    op.drop_index("ix_ais_position_reports_event_ts", table_name="ais_position_reports")
    op.drop_index("ix_ais_position_reports_event_type", table_name="ais_position_reports")
    op.drop_table("ais_position_reports")
    op.execute("DROP TYPE IF EXISTS aiseventtype")
    op.execute("DROP TYPE IF EXISTS aissource")
