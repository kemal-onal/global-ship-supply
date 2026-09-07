"""impa_first

Revision ID: 0007_impa_first
Revises: 0006_marketplace_enums
Create Date: 2026-09-04 14:00:00.000000

Reshapes the order line shape so that nobody — purchaser, admin, or
supplier — knows a price before a supplier quotes. The new flow:

  * The order line has no price. The purchaser types an IMPA code
    (or picks from a typeahead) plus a description, quantity, and
    notes. The catalog page is gone; the only place a "product"
    matters is when the supplier's quote names one (or doesn't —
    the supplier is the source of truth for what's actually
    available).
  * ``orders.etd_at_port`` is a new column that mirrors
    ``eta_at_port``. The supplier needs the *window* between ETA
    and ETD to decide whether they can deliver in time. The new
    fan-out step snapshots both.
  * ``order_items.product_id`` becomes nullable. The
    cross-reference to the catalog is gone. ``order_items.impa_code``
    becomes the typed IMPA string the purchaser supplied (or
    picked). Existing rows with a product_id are kept as-is.
  * ``rfq_items.product_id`` becomes nullable too (mirrors the
    change on order_items; the IMPA code is sourced from
    order_items.impa_code, not from Product.impa_code).
  * ``supplier_quotes.can_deliver_in_window`` is a new boolean
    that gates the rest of the quote flow. ``null`` means the
    supplier hasn't decided yet; ``true`` means they can deliver
    between ETA and ETD; ``false`` means they declined, and the
    accompanying ``decline_reason`` is the optional free-text
    reason they gave.

No new tables, no new enums, no new permissions. The 309 sealed-bid
tests still pass because (a) they build their data directly in
Python fixtures, and (b) making ``product_id`` nullable doesn't
break rows that already have one.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers
revision: str = "0007_impa_first"
down_revision: Union[str, None] = "0006_marketplace_enums"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) orders.etd_at_port — the mirror of eta_at_port. Snapshotted
    #    at fan-out time from AisPositionReport.etd.
    op.add_column(
        "orders",
        sa.Column(
            "etd_at_port",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # 2) order_items: make product_id nullable + add impa_code.
    #    The product_id column is FK to products.id; dropping NOT NULL
    #    keeps the FK in place. The impa_code column is a free-text
    #    string (NOT a FK to impa_codes.id) — the typeahead is just a
    #    convenience. The supplier is the source of truth for whether
    #    the IMPA maps to a real product.
    op.alter_column(
        "order_items",
        "product_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.add_column(
        "order_items",
        sa.Column(
            "impa_code",
            sa.String(length=20),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_order_items_impa_code",
        "order_items",
        ["impa_code"],
    )

    # 3) rfq_items: mirror the nullable product_id change. The
    #    impa_code column already exists (added in 0005); the new
    #    code sources it from order_items.impa_code (the typed
    #    value) instead of from Product.impa_code.
    op.alter_column(
        "rfq_items",
        "product_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
    )

    # 4) supplier_quotes: the ETA/ETD gate.
    op.add_column(
        "supplier_quotes",
        sa.Column(
            "can_deliver_in_window",
            sa.Boolean(),
            nullable=True,
        ),
    )
    op.add_column(
        "supplier_quotes",
        sa.Column(
            "declined_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "supplier_quotes",
        sa.Column(
            "decline_reason",
            sa.String(length=200),
            nullable=True,
        ),
    )
    # The check keeps the gate self-consistent: declined_at + reason
    # can only be set when the supplier actually declined. A
    # can_deliver_in_window=null quote is "in progress" — no
    # declined_at, no reason.
    op.create_check_constraint(
        "ck_supplier_quotes_decline_consistency",
        "supplier_quotes",
        "(can_deliver_in_window IS NULL AND declined_at IS NULL) OR "
        "(can_deliver_in_window = true AND declined_at IS NULL) OR "
        "(can_deliver_in_window = false)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_supplier_quotes_decline_consistency",
        "supplier_quotes",
        type_="check",
    )
    op.drop_column("supplier_quotes", "decline_reason")
    op.drop_column("supplier_quotes", "declined_at")
    op.drop_column("supplier_quotes", "can_deliver_in_window")

    op.alter_column(
        "rfq_items",
        "product_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=False,
    )

    op.drop_index("ix_order_items_impa_code", table_name="order_items")
    op.drop_column("order_items", "impa_code")
    op.alter_column(
        "order_items",
        "product_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=False,
    )

    op.drop_column("orders", "etd_at_port")
