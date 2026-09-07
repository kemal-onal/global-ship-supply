"""marketplace_redesign

Revision ID: 0005_marketplace_redesign
Revises: 0004_market_sim_event_visibility
Create Date: 2026-09-04 10:00:00.000000

Replaces the sealed-bid Marketplace Simulator with a fan-out /
per-line decision / approval flow. The new flow:

  1. Purchaser drafts an order (vessel, port, lines, notes).
  2. Company may ask clarifying questions (clarification loop).
  3. ETA snapshot is taken from the vessel's recent AIS positions
     for the destination port.
  4. Company builds an RFQ and fans it out to ALL active suppliers
     at the destination port (not just the ones carrying every line
     — suppliers can return "none" for what they don't have).
  5. Each supplier submits a per-line decision: full / partial / none,
     with a unit price when they offer.
  6. Company composes a proposal (per line: which supplier(s), full
     or half), applies a margin %, and sends to the purchaser.
  7. Purchaser approves or rejects.
  8. On approve, each winning supplier has 24h to confirm. Slow
     suppliers are dropped (a background sweeper task handles this).

The bid war engine (see ``app/services/market_sim.py``) and the
``market_sim_events`` table stay untouched — they're a sealed-bid
demo that any future bid-style demo can revive. New code never
writes to ``market_sim_events``.

New ``OrderStatus`` values:

  - ``AWAITING_CLARIFICATION``   company asked a question
  - ``QUOTING``                  RFQ sent, suppliers are responding
  - ``READY_FOR_COMPOSE``        deadline passed or all invited responded
  - ``AWAITING_PURCHASER_APPROVAL`` proposal sent, purchaser hasn't replied

The old ``PENDING_APPROVAL`` / ``RFQ_IN_PROGRESS`` / ``BIDDING`` /
``AWAITING_CONFIRMATION`` enum values stay in the schema for legacy
data and tests; new code never writes them. The dashboard treats
``RFQ_IN_PROGRESS`` and ``BIDDING`` as ``QUOTING`` for display.

New columns:

  - ``orders.company_margin_pct`` — Numeric(5,2) default 8.00, nullable
  - ``orders.eta_at_port``         — DateTime(timezone), nullable
  - ``orders.clarification``       — JSONB, nullable
  - ``rfq_items.impa_code``        — String(20), nullable (denormalized
    for the supplier portal — avoids a join to display)
  - ``supplier_quotes.decision_method`` — String(20), nullable ("full"/"partial")
  - ``supplier_quotes.confirmed_at``    — DateTime(timezone), nullable
  - ``supplier_quotes.preparation_deadline`` — DateTime(timezone), nullable
  - ``quote_items.line_status``    — String(10), default "full"
    ("full" / "partial" / "none")
  - ``quote_items.quoted_quantity`` — Integer, nullable
    (when partial, equals ``ceil(requested/2)``; equals ``quantity``
    when full)

New tables:

  - ``order_decisions`` — one row per (line, supplier) the company
    chose to use. Carries the supplier's unit_price and the margin
    that was applied to produce the customer-facing total. The
    purchaser sees the ``customer_facing_total``; the company sees
    the whole row.

  - ``supplier_line_assignments`` — one row per (line, supplier) that
    was selected. Carries the supplier's confirmation status and
    the 24h preparation deadline. The background sweeper drops
    rows whose deadline has passed without confirmation.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "0005_marketplace_redesign"
down_revision: Union[str, None] = "0004_market_sim_event_visibility"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# New OrderStatus enum values. The migration adds them to the existing
# `orderstatus` Postgres enum (created in 0001_initial). Old values
# stay — legacy data + tests still reference them.
_NEW_ORDER_STATUSES = (
    "AWAITING_CLARIFICATION",
    "QUOTING",
    "READY_FOR_COMPOSE",
    "AWAITING_PURCHASER_APPROVAL",
)


def upgrade() -> None:
    # 1) Extend the OrderStatus enum. Postgres requires that new
    # enum values be committed before they can be referenced in the
    # same transaction (e.g. in a partial-index predicate). We
    # handle that by:
    #   a) issuing the ALTER TYPE statements on the alembic
    #      connection *first* (these are no-ops in PG 12+ if the
    #      values are added but not yet usable in the same tx)
    #   b) avoiding any partial-index predicate or check constraint
    #      that names a new value
    #   c) doing all the rest of the migration in this same
    #      transaction; the new values become usable when the
    #      transaction commits
    # Note: PG 12+ does NOT actually allow referencing a new enum
    # value in the same transaction it was added, even via CREATE
    # INDEX. We avoid that by dropping the partial-index predicate
    # and the new check-constraints from this migration; the
    # constraints are added by application code (and a future
    # revision if needed).
    for label in _NEW_ORDER_STATUSES:
        op.execute(f"ALTER TYPE orderstatus ADD VALUE IF NOT EXISTS '{label}'")

    # 2) Orders: company margin, ETA snapshot, clarification thread.
    op.add_column(
        "orders",
        sa.Column(
            "company_margin_pct",
            sa.Numeric(5, 2),
            nullable=True,
            server_default=sa.text("8.00"),
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "eta_at_port",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "clarification",
            postgresql.JSONB,
            nullable=True,
        ),
    )
    # The composite index supports the dashboard's "orders awaiting
    # approval" query: WHERE status = AWAITING_PURCHASER_APPROVAL
    # ORDER BY order_date DESC. We don't add a partial-index
    # predicate here because the new enum value can't be referenced
    # in the same transaction. The plain (status, order_date)
    # composite is still highly selective; once the migration
    # commits, a follow-up can rewrite it as a partial index.
    op.create_index(
        "ix_orders_status_order_date",
        "orders",
        ["status", "order_date"],
    )

    # 3) RFQ items: denormalized IMPA code for the supplier portal.
    op.add_column(
        "rfq_items",
        sa.Column(
            "impa_code",
            sa.String(length=20),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_rfq_items_impa_code",
        "rfq_items",
        ["impa_code"],
    )

    # 4) Supplier quotes: per-line decision method, confirmation
    #    timestamp, 24h preparation deadline.
    op.add_column(
        "supplier_quotes",
        sa.Column(
            "decision_method",
            sa.String(length=20),
            nullable=True,
        ),
    )
    op.add_column(
        "supplier_quotes",
        sa.Column(
            "confirmed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "supplier_quotes",
        sa.Column(
            "preparation_deadline",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_supplier_quotes_decision_method",
        "supplier_quotes",
        "decision_method IS NULL OR decision_method IN ('full', 'partial')",
    )
    # The sweeper's query: WHERE preparation_deadline < now() AND
    # confirmed_at IS NULL. Plain index on the deadline column
    # (the partial-index predicate would reference the
    # preparation_deadline column itself, but the cost of the
    # non-partial version is negligible given how few rows will
    # have a non-null deadline at any one time).
    op.create_index(
        "ix_supplier_quotes_prep_deadline",
        "supplier_quotes",
        ["preparation_deadline"],
    )

    # 5) Quote items: per-line status (full/partial/none) and the
    #    actual quoted quantity (when partial, this is ceil(qty/2)).
    op.add_column(
        "quote_items",
        sa.Column(
            "line_status",
            sa.String(length=10),
            nullable=False,
            server_default=sa.text("'full'"),
        ),
    )
    op.add_column(
        "quote_items",
        sa.Column(
            "quoted_quantity",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_quote_items_line_status",
        "quote_items",
        "line_status IN ('full', 'partial', 'none')",
    )

    # 6) order_decisions — the company's per-line choice of supplier.
    op.create_table(
        "order_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "rfq_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rfq_items.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "supplier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("suppliers.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "quote_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("supplier_quotes.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        # 'use_full' | 'use_half' | 'drop' — what fraction of the
        # supplier's offered list we're actually using. The supplier
        # may have offered full or partial; the decision records the
        # fraction we're taking from that offer.
        sa.Column("decision", sa.String(length=10), nullable=False),
        # The supplier's unit price for this line (what the company
        # sees in the marketplace lattice). Used to compute
        # customer_facing_total = unit_price * used_quantity * (1 + margin/100).
        sa.Column("unit_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("used_quantity", sa.Integer(), nullable=False),
        sa.Column("line_total", sa.Numeric(14, 4), nullable=False),
        # The margin % that was applied for the purchaser's view.
        # Stored on the row so changing the order's margin later
        # doesn't rewrite history.
        sa.Column("margin_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("customer_facing_total", sa.Numeric(14, 4), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('use_full', 'use_half', 'drop')",
            name="ck_order_decisions_decision",
        ),
        sa.CheckConstraint(
            "used_quantity > 0",
            name="ck_order_decisions_used_qty_positive",
        ),
    )
    op.create_index(
        "ix_order_decisions_order_rfq_item",
        "order_decisions",
        ["order_id", "rfq_item_id"],
    )

    # 7) supplier_line_assignments — winning slices + 24h deadline.
    op.create_table(
        "supplier_line_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "rfq_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rfq_items.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "supplier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("suppliers.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "quote_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("supplier_quotes.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "decision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("order_decisions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # 'pending' | 'confirmed' | 'dropped' — the supplier's
        # acceptance state. Pending slices that miss their
        # preparation_deadline get flipped to 'dropped' by the
        # background sweeper.
        sa.Column("line_status", sa.String(length=10), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dropped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("drop_reason", sa.String(length=100), nullable=True),
        # When the company approved the proposal, this is set to
        # now + 24h. The supplier has until this timestamp to confirm.
        sa.Column("preparation_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "line_status IN ('pending', 'confirmed', 'dropped')",
            name="ck_supplier_line_assignments_status",
        ),
    )
    op.create_index(
        "ix_supplier_line_assignments_order",
        "supplier_line_assignments",
        ["order_id", "line_status"],
    )
    op.create_index(
        "ix_supplier_line_assignments_deadline",
        "supplier_line_assignments",
        ["preparation_deadline"],
    )


def downgrade() -> None:
    op.drop_index("ix_supplier_line_assignments_deadline", table_name="supplier_line_assignments")
    op.drop_index("ix_supplier_line_assignments_order", table_name="supplier_line_assignments")
    op.drop_table("supplier_line_assignments")

    op.drop_index("ix_order_decisions_order_rfq_item", table_name="order_decisions")
    op.drop_table("order_decisions")

    op.drop_constraint("ck_quote_items_line_status", "quote_items", type_="check")
    op.drop_column("quote_items", "quoted_quantity")
    op.drop_column("quote_items", "line_status")

    op.drop_index("ix_supplier_quotes_prep_deadline", table_name="supplier_quotes")
    op.drop_constraint("ck_supplier_quotes_decision_method", "supplier_quotes", type_="check")
    op.drop_column("supplier_quotes", "preparation_deadline")
    op.drop_column("supplier_quotes", "confirmed_at")
    op.drop_column("supplier_quotes", "decision_method")

    op.drop_index("ix_rfq_items_impa_code", table_name="rfq_items")
    op.drop_column("rfq_items", "impa_code")

    op.drop_index("ix_orders_status_order_date", table_name="orders")
    op.drop_column("orders", "clarification")
    op.drop_column("orders", "eta_at_port")
    op.drop_column("orders", "company_margin_pct")

    # Postgres doesn't support removing a value from an enum in
    # place. The cleanest rollback is to leave the values in place
    # and let the next migration re-narrow if needed. The values are
    # unused after the column drops, so it's just a few extra labels
    # in pg_enum.
    # If a hard revert is required, recreate the type: rename to
    # orderstatus_old, create orderstatus with the old labels only,
    # ALTER TABLE orders ALTER COLUMN status TYPE orderstatus USING
    # status::text::orderstatus, DROP TYPE orderstatus_old. Skipping
    # here because it's risky in a downgrade and the unused labels
    # don't break anything.
