"""
Order and OrderItem models — the central transactional entity of the platform.

An Order captures the lifecycle from RFQ → Bidding → Approval → Delivery. The
status field is the single source of truth for the current state and is driven
by the orders service (see app/services/orders.py).

Simplified status flow for the new marketplace:
DRAFT -> PENDING_APPROVAL -> (admin sends RFQ) -> RFQ_SENT -> (suppliers quote) ->
RFQ_CLOSED -> (purchaser decides) -> APPROVED / DRAFT (on reject)
"""
import enum
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, AuditMixin, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.vessel import Vessel
    from app.models.port import Port
    from app.models.product import Product
    from app.models.supplier import RFQ, SupplierQuote


class OrderStatus(str, enum.Enum):
    """Simplified order statuses for the new marketplace flow.

    DRAFT -> PENDING_APPROVAL -> RFQ_SENT -> RFQ_CLOSED -> APPROVED / DRAFT (reject)

    Legacy statuses kept for backward compatibility with existing data:
    - (old statuses removed; simplified flow kept)
    - CONFIRMED, IN_TRANSIT, DELIVERED, COMPLETED, CANCELLED, REJECTED
    """
    # Core simplified flow
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    RFQ_SENT = "rfq_sent"
    RFQ_CLOSED = "rfq_closed"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"

    # Legacy statuses (kept for existing data, not written by new code)
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    COMPLETED = "completed"


class OrderPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"  # Drives RFQ timeout shrinking & port-side alerts


class Order(Base, TimestampMixin, SoftDeleteMixin, AuditMixin):
    """An order placed by a vessel, target a port."""

    __tablename__ = "orders"

    # Public reference number, e.g. "AVS-2026-000123"
    reference: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    vessel_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vessels.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    port_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ports.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus), default=OrderStatus.DRAFT, nullable=False, index=True
    )
    priority: Mapped[OrderPriority] = mapped_column(
        Enum(OrderPriority), default=OrderPriority.NORMAL, nullable=False, index=True
    )

    # Order dates
    order_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )
    required_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    estimated_delivery: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actual_delivery: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Money
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    subtotal: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    tax_total: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    shipping_total: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    grand_total: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False, index=True)

    # Notes
    customer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Compliance
    customs_clearance_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    customs_cleared: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    inspection_passed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    regulation_warnings: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)

    # Offline / sync metadata
    source: Mapped[str] = mapped_column(String(20), default="web", nullable=False)  # web, mobile, api, offline
    client_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)  # Offline client UUID
    client_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # People
    created_by: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    assigned_to: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    approved_by: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    vessel: Mapped["Vessel"] = relationship(back_populates="orders")
    port: Mapped["Port"] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin"
    )
    created_by_user: Mapped["User"] = relationship(foreign_keys=[created_by], back_populates="orders_created")
    assigned_to_user: Mapped["User | None"] = relationship(foreign_keys=[assigned_to], back_populates="orders_assigned")
    rfqs: Mapped[list["RFQ"]] = relationship(back_populates="order")
    chosen_quote: Mapped["SupplierQuote | None"] = relationship(foreign_keys="[SupplierQuote.order_id]")

    __table_args__ = (
        Index("ix_orders_vessel_status", "vessel_id", "status"),
        Index("ix_orders_port_status", "port_id", "status"),
        Index("ix_orders_status_date", "status", "order_date"),
        CheckConstraint("grand_total >= 0", name="ck_orders_total_positive"),
    )

    def __repr__(self) -> str:
        return f"<Order {self.reference} ({self.status.value})>"

    @property
    def item_count(self) -> int:
        return sum(item.quantity for item in self.items)


class OrderItem(Base, TimestampMixin):
    """Line item belonging to an order."""

    __tablename__ = "order_items"

    order_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Nullable: the purchaser's order is now a typed IMPA code, not a catalog
    # reference. The supplier is the source of truth for whether the IMPA
    # maps to a real product. Legacy rows with a product_id keep theirs.
    product_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    # The IMPA code the purchaser typed or picked from the typeahead.
    # Free-text (NOT a FK) — the ImpaCode table is just the typeahead
    # source. Index for the supplier portal / lattice lookups.
    impa_code: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), default="pcs", nullable=False)
    # The order line carries no price. unit_price is kept on the
    # row (always 0 for new orders) for legacy compatibility with
    # the existing subtotal/grand_total machinery and sealed-bid
    # tests; the field is internal-only and never surfaced to any
    # role.
    unit_price: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Fulfillment
    quantity_fulfilled: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    order: Mapped["Order"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship(back_populates="order_items")

    __table_args__ = (
        Index("ix_order_items_order_product", "order_id", "product_id"),
        CheckConstraint("quantity > 0", name="ck_order_items_qty_positive"),
        CheckConstraint("line_total >= 0", name="ck_order_items_total_positive"),
    )