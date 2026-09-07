"""market_sim_event_visibility

Revision ID: 0004_market_sim_event_visibility
Revises: 0003_market_sim_events
Create Date: 2026-09-03 14:00:00.000000

Adds two columns to ``market_sim_events`` for counter-offer
classification:

* ``visibility`` — one of ``public`` (default) or ``winner_only``.
  The buyer-side response serializer strips ``winner_only`` rows
  down to a redacted stub for non-admin, non-winner callers. The
  default ``public`` is what every existing row gets — they were
  all written before this rule existed, and changing their
  visibility retroactively would be misleading.

* ``visible_to_supplier_ids`` — a UUID[] listing the supplier ids
  that may see the full payload. The engine sets this to
  ``[winner.supplier_id]`` when writing a ``counter_offer`` event.

Why this lives on the event row (instead of a separate
classification table):

* The visibility is a property of the *event*, not the supplier or
  the RFQ. It changes per event (``bid_arrived`` is public;
  ``counter_offer`` for a buyer is winner_only). Putting it on the
  row keeps the read path simple — the serializer just looks at
  the row's own columns.

* The supplier portal doesn't exist yet, so ``visible_to_supplier_ids``
  has no consumer today. But populating it now means the rule is
  in place the moment a supplier endpoint queries the event log.

Why a VARCHAR (not a Postgres ENUM):

* Same reason as ``event_type`` in 0003: trivial to extend, no
  schema migration to add a new visibility value later. The
  CheckConstraint enforces the two valid values at the DB level.

For the supplier-portal query, the index covers the dominant
"events visible to supplier X" pattern. The ``rfq_id`` prefix keeps
the index sorted by RFQ for the polling timeline.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "0004_market_sim_event_visibility"
down_revision: Union[str, None] = "0003_market_sim_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add the visibility column. NOT NULL with a server default
    # means existing rows backfill to 'public' automatically — the
    # migration doesn't need a separate UPDATE pass.
    op.add_column(
        "market_sim_events",
        sa.Column(
            "visibility",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'public'"),
        ),
    )
    op.add_column(
        "market_sim_events",
        sa.Column(
            "visible_to_supplier_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=True,
        ),
    )
    # Belt-and-braces: enforce the two valid values at the DB level
    # so a bad write from a future code path can't smuggle a typo
    # past the application.
    op.create_check_constraint(
        "ck_market_sim_events_visibility",
        "market_sim_events",
        "visibility IN ('public', 'winner_only')",
    )
    # Composite index for the "events visible to supplier X in this
    # RFQ" query pattern. When the supplier portal exists, this
    # becomes the dominant read.
    op.create_index(
        "ix_market_sim_events_visibility",
        "market_sim_events",
        ["rfq_id", "visibility"],
    )


def downgrade() -> None:
    op.drop_index("ix_market_sim_events_visibility", table_name="market_sim_events")
    op.drop_constraint(
        "ck_market_sim_events_visibility",
        "market_sim_events",
        type_="check",
    )
    op.drop_column("market_sim_events", "visible_to_supplier_ids")
    op.drop_column("market_sim_events", "visibility")
