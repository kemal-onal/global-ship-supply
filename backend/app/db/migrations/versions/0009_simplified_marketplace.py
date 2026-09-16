"""simplified_marketplace

Revision ID: 0009_simplified_marketplace
Revises: 0008_auditaction_values
Create Date: 2026-09-09 10:00:00.000000

Simplifies the marketplace flow by removing the complex per-line
decision / 24h acceptance / clarification layers. The new flow:

1. Order created by purchaser -> PENDING_APPROVAL
2. Admin sends RFQ to all active suppliers at port (fan-out)
3. Suppliers submit quotes — single form with all lines (full/partial/none
   + custom quantity + unit price) + lead_time_days + payment_terms
4. Admin applies uniform markup % to ALL quotes
5. Admin sends marked-up quotes to purchaser (RFQ -> CLOSED)
6. Purchaser approves/rejects entire proposal:
   - Approve: Order -> APPROVED, RFQ -> AWARDED
   - Reject: Order -> DRAFT, RFQ -> CANCELLED

Removed tables:
- order_decisions (per-line supplier selection)
- supplier_line_assignments (24h slice acceptance)
- bid_comparisons (sealed-bid engine)
- market_sim_events (simulator timeline)

Removed columns from supplier_quotes:
- score, is_awarded, is_rejected, rejection_reason, decision_method
- can_deliver_in_window, declined_at, decline_reason
- preparation_deadline, confirmed_at

Removed columns from orders:
- company_margin_pct, eta_at_port, etd_at_port, clarification

New columns on RFQ:
- markup_pct (float, default 0) — admin's markup percentage
- status enum simplified: draft -> sent -> closed -> awarded/cancelled
  (removed: open, ready_for_compose, expired)

New columns on supplier_quotes:
- marked_up_total (float) — total after markup applied
- customer_facing_total (float) — same as marked_up_total for purchaser view

Simplified OrderStatus: keep DRAFT, PENDING_APPROVAL, APPROVED, REJECTED,
CANCELLED. Add RFQ_SENT, RFQ_CLOSED, AWARDED (or track via RFQ status).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "0009_simplified_marketplace"
down_revision: Union[str, None] = "0008_auditaction_values"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_RFQ_STATUSES = (
    "draft",
    "sent",
    "closed",
    "awarded",
    "cancelled",
)


_NEW_ORDER_STATUSES = (
    "RFQ_SENT",
    "RFQ_CLOSED",
    "AWARDED",
)


def upgrade() -> None:
    # 1) Extend the RFQStatus enum (add new simplified values)
    # The old values (OPEN, READY_FOR_COMPOSE, EXPIRED) stay for legacy data
    for label in _NEW_RFQ_STATUSES:
        op.execute(f"ALTER TYPE rfqstatus ADD VALUE IF NOT EXISTS '{label}'")

    # 2) Extend the OrderStatus enum
    for label in _NEW_ORDER_STATUSES:
        op.execute(f"ALTER TYPE orderstatus ADD VALUE IF NOT EXISTS '{label}'")

    # 3) RFQ: add markup_pct column
    op.add_column(
        "rfqs",
        sa.Column(
            "markup_pct",
            sa.Numeric(5, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
    )

    # 4) SupplierQuote: add marked_up_total and customer_facing_total
    op.add_column(
        "supplier_quotes",
        sa.Column(
            "marked_up_total",
            sa.Numeric(14, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "supplier_quotes",
        sa.Column(
            "customer_facing_total",
            sa.Numeric(14, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    # 5) Drop the complex columns from supplier_quotes that are no longer needed
    # (Note: Postgres requires dropping constraints before columns)
    op.drop_constraint("ck_supplier_quotes_decision_method", "supplier_quotes", type_="check")
    op.drop_constraint("ck_supplier_quotes_decline_consistency", "supplier_quotes", type_="check")

    op.drop_column("supplier_quotes", "score")
    op.drop_column("supplier_quotes", "is_awarded")
    op.drop_column("supplier_quotes", "is_rejected")
    op.drop_column("supplier_quotes", "rejection_reason")
    op.drop_column("supplier_quotes", "decision_method")
    op.drop_column("supplier_quotes", "can_deliver_in_window")
    op.drop_column("supplier_quotes", "declined_at")
    op.drop_column("supplier_quotes", "decline_reason")
    op.drop_column("supplier_quotes", "preparation_deadline")
    op.drop_column("supplier_quotes", "confirmed_at")

    # 6) Drop the index on preparation_deadline
    op.drop_index("ix_supplier_quotes_prep_deadline", table_name="supplier_quotes")

    # 7) Drop the check constraint on quote_items.line_status (keep the column for line_status)
    # We keep line_status and quoted_quantity as they're still useful for the simplified flow
    # op.drop_constraint("ck_quote_items_line_status", "quote_items", type_="check")
    # op.drop_column("quote_items", "line_status")
    # op.drop_column("quote_items", "quoted_quantity")

    # 8) Drop order_decisions table
    op.drop_index("ix_order_decisions_order_rfq_item", table_name="order_decisions")
    op.drop_table("order_decisions")

    # 9) Drop supplier_line_assignments table
    op.drop_index("ix_supplier_line_assignments_deadline", table_name="supplier_line_assignments")
    op.drop_index("ix_supplier_line_assignments_order", table_name="supplier_line_assignments")
    op.drop_table("supplier_line_assignments")

    # 10) Drop bid_comparisons table
    op.drop_table("bid_comparisons")

    # 11) Drop market_sim_events table
    op.drop_table("market_sim_events")

    # 12) Remove columns from orders that are no longer needed
    op.drop_column("orders", "company_margin_pct")
    op.drop_column("orders", "eta_at_port")
    op.drop_column("orders", "etd_at_port")
    op.drop_column("orders", "clarification")

    # 13) Drop the index on orders.status + order_date
    op.drop_index("ix_orders_status_order_date", table_name="orders")


def downgrade() -> None:
    # Note: Postgres doesn't support removing enum values, so we leave
    # the new enum values in place. The column/table drops are
    # reversible but would need the enum values to exist for any
    # legacy rows.

    # Recreate the columns on orders
    op.add_column(
        "orders",
        sa.Column(
            "clarification",
            postgresql.JSONB,
            nullable=True,
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "etd_at_port",
            sa.DateTime(timezone=True),
            nullable=True,
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
            "company_margin_pct",
            sa.Numeric(5, 2),
            nullable=True,
            server_default=sa.text("8.00"),
        ),
    )

    # Recreate the index
    op.create_index(
        "ix_orders_status_order_date",
        "orders",
        ["status", "order_date"],
    )

    # Recreate market_sim_events table
    op.create_table(
        "market_sim_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("visibility", sa.String(length=20), nullable=False, server_default=sa.text("'all'")),
    )

    # Recreate bid_comparisons table
    op.create_table(
        "bid_comparisons",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("rfq_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rfqs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("weights", postgresql.JSONB, nullable=False),
        sa.Column("results", postgresql.JSONB, nullable=False),
        sa.Column("winner_quote_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )

    # Recreate supplier_line_assignments table
    op.create_table(
        "supplier_line_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("rfq_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rfq_items.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("quote_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("supplier_quotes.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("order_decisions.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("line_status", sa.String(length=10), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dropped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("drop_reason", sa.String(length=100), nullable=True),
        sa.Column("preparation_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("line_status IN ('pending', 'confirmed', 'dropped')", name="ck_supplier_line_assignments_status"),
    )
    op.create_index("ix_supplier_line_assignments_order", "supplier_line_assignments", ["order_id", "line_status"])
    op.create_index("ix_supplier_line_assignments_deadline", "supplier_line_assignments", ["preparation_deadline"])

    # Recreate order_decisions table
    op.create_table(
        "order_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("rfq_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rfq_items.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("quote_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("supplier_quotes.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("decision", sa.String(length=10), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("used_quantity", sa.Integer(), nullable=False),
        sa.Column("line_total", sa.Numeric(14, 4), nullable=False),
        sa.Column("margin_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("customer_facing_total", sa.Numeric(14, 4), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("decision IN ('use_full', 'use_half', 'drop')", name="ck_order_decisions_decision"),
        sa.CheckConstraint("used_quantity > 0", name="ck_order_decisions_used_qty_positive"),
    )
    op.create_index("ix_order_decisions_order_rfq_item", "order_decisions", ["order_id", "rfq_item_id"])

    # Recreate columns on supplier_quotes
    op.add_column("supplier_quotes", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("supplier_quotes", sa.Column("preparation_deadline", sa.DateTime(timezone=True), nullable=True))
    op.add_column("supplier_quotes", sa.Column("decline_reason", sa.String(length=200), nullable=True))
    op.add_column("supplier_quotes", sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("supplier_quotes", sa.Column("can_deliver_in_window", sa.Boolean(), nullable=True))
    op.add_column("supplier_quotes", sa.Column("decision_method", sa.String(length=20), nullable=True))
    op.add_column("supplier_quotes", sa.Column("rejection_reason", sa.Text(), nullable=True))
    op.add_column("supplier_quotes", sa.Column("is_rejected", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("supplier_quotes", sa.Column("is_awarded", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("supplier_quotes", sa.Column("score", sa.Float(), nullable=False, server_default=sa.text("0.0")))

    # Recreate constraints and index
    op.create_check_constraint(
        "ck_supplier_quotes_decision_method",
        "supplier_quotes",
        "decision_method IS NULL OR decision_method IN ('full', 'partial')",
    )
    op.create_check_constraint(
        "ck_supplier_quotes_decline_consistency",
        "supplier_quotes",
        "(can_deliver_in_window IS NULL AND declined_at IS NULL) OR "
        "(can_deliver_in_window = true AND declined_at IS NULL) OR "
        "(can_deliver_in_window = false)",
    )
    op.create_index("ix_supplier_quotes_prep_deadline", "supplier_quotes", ["preparation_deadline"])

    # Drop the new columns
    op.drop_column("supplier_quotes", "customer_facing_total")
    op.drop_column("supplier_quotes", "marked_up_total")

    # Drop markup_pct from rfqs
    op.drop_column("rfqs", "markup_pct")

    # Note: enum values are not removed in downgrade (Postgres limitation)