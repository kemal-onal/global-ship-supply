"""market_sim_events

Revision ID: 0003_market_sim_events
Revises: 0002_ais_position_reports
Create Date: 2026-09-02 14:30:00.000000

Adds the ``market_sim_events`` table for the Marketplace Simulator
(see ``app/services/market_sim.py`` and ``POST /api/v1/rfq/{id}/simulate``).

Stores the audit log of a supplier bid war: each row is one event
(``run_start``, ``bid_arrived``, ``round_close``, ``counter_offer``,
``run_end``). The RFQ itself is the "run" — there is no separate
``market_sim_runs`` header table. The current round number and last
seed are tracked on ``rfqs.extra`` JSONB.

Why a separate table (and not just write to ``supplier_quotes`` /
``bid_comparisons``)?

* Sim bids are persisted as real ``SupplierQuote`` rows (so the
  existing ``compare_quotes`` engine works unchanged), but the
  *timeline* of events (bids arriving in what order, the round
  boundary, the counter-offer) has no home in those tables.
* Append-only event stream is the right shape for the timeline view
  in the frontend (poll ``WHERE rfq_id = ? AND ts > ?``).

If your deployment predates the simulator, run ``python -m
scripts.seed`` after upgrading to pick up the new
``rfq:simulate:own`` permission for purchasing officers.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "0003_market_sim_events"
down_revision: Union[str, None] = "0002_ais_position_reports"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "market_sim_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column(
            "rfq_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rfqs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("round", sa.Integer(), nullable=False, server_default=sa.text("1")),
        # VARCHAR(40) instead of a Postgres enum: keeps the schema trivial
        # and avoids enum-evolution pain when we add new event types.
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column(
            "supplier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("suppliers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("payload", postgresql.JSONB, nullable=True),
        sa.CheckConstraint(
            "round >= 1",
            name="ck_market_sim_events_round_positive",
        ),
    )
    op.create_index("ix_market_sim_events_rfq_id", "market_sim_events", ["rfq_id"])
    op.create_index("ix_market_sim_events_ts", "market_sim_events", ["ts"])
    op.create_index("ix_market_sim_events_event_type", "market_sim_events", ["event_type"])
    op.create_index("ix_market_sim_events_rfq_id_ts", "market_sim_events", ["rfq_id", "ts"])


def downgrade() -> None:
    op.drop_index("ix_market_sim_events_rfq_id_ts", table_name="market_sim_events")
    op.drop_index("ix_market_sim_events_event_type", table_name="market_sim_events")
    op.drop_index("ix_market_sim_events_ts", table_name="market_sim_events")
    op.drop_index("ix_market_sim_events_rfq_id", table_name="market_sim_events")
    op.drop_table("market_sim_events")
