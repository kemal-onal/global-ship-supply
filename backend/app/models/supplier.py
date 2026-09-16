"""
Supplier, RFQ (Request For Quotation) and Quote models — Simplified Marketplace.

The simplified flow:
1. Order created by purchaser
2. Admin sends RFQ to all active suppliers at port (fan-out)
3. Suppliers submit quotes — single form with all lines (full/partial/none
   + custom quantity + unit price) + lead_time_days + payment_terms
4. Admin applies uniform markup % to ALL quotes
5. Admin sends marked-up quotes to purchaser (RFQ -> CLOSED)
6. Purchaser approves/rejects entire proposal:
   - Approve: Order -> APPROVED, RFQ -> AWARDED
   - Reject: Order -> DRAFT, RFQ -> CANCELLED
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
    from app.models.order import Order
    from app.models.product import Product
    from app.models.port import Port


class SupplierStatus(str, enum.Enum):
    ACTIVE = "active"
    PENDING = "pending"
    SUSPENDED = "suspended"
    BLACKLISTED = "blacklisted"


class RFQStatus(str, enum.Enum):
    """Simplified RFQ statuses for the new marketplace flow.

    DRAFT -> SENT -> CLOSED -> AWARDED / CANCELLED
    OPEN is an alias for SENT (RFQ out to suppliers, awaiting quotes).
    """
    DRAFT = "draft"
    OPEN = "open"  # Alias for SENT — RFQ out for bidding
    SENT = "sent"
    CLOSED = "closed"
    AWARDED = "awarded"
    CANCELLED = "cancelled"
    EXPIRED = "expired"  # Response deadline passed with <2/2 suppliers responded


class QuoteLineStatus(str, enum.Enum):
    """A supplier's per-line answer to the RFQ.

    * ``full``    — we can supply the full requested quantity
    * ``partial`` — we can supply a custom quantity (< requested)
    * ``none``    — we don't carry this product
    """
    FULL = "full"
    PARTIAL = "partial"
    NONE = "none"


class Supplier(Base, TimestampMixin, SoftDeleteMixin, AuditMixin):
    """Local/regional supplier of provisions, deck/engine stores, etc."""

    __tablename__ = "suppliers"

    company_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    legal_name: Mapped[str | None] = mapped_column(String(250), nullable=True)
    tax_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    registration_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Contact
    contact_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Address
    address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True, index=True)

    # Capabilities
    categories: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    certifications: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)  # ISO 9001, halal cert, etc.
    payment_terms: Mapped[str | None] = mapped_column(String(100), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)

    status: Mapped[SupplierStatus] = mapped_column(
        Enum(SupplierStatus), default=SupplierStatus.PENDING, nullable=False, index=True
    )

    # Ratings — cached from SupplierRating history
    rating_overall: Mapped[float] = mapped_column(Float, default=0.0, nullable=False, index=True)
    rating_reliability: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    rating_quality: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    rating_communication: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    rating_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    on_time_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    avg_response_hours: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # API integration
    api_endpoint: Mapped[str | None] = mapped_column(String(500), nullable=True)
    api_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    supports_api: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Notification
    notify_by_email: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_by_sms: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notify_by_api: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    ports: Mapped[list["SupplierPort"]] = relationship(back_populates="supplier", cascade="all, delete-orphan")
    products: Mapped[list["ProductSupplier"]] = relationship(back_populates="supplier", cascade="all, delete-orphan")
    ratings: Mapped[list["SupplierRating"]] = relationship(back_populates="supplier", cascade="all, delete-orphan")
    quotes: Mapped[list["SupplierQuote"]] = relationship(back_populates="supplier")

    __table_args__ = (
        Index("ix_suppliers_status_rating", "status", "rating_overall"),
    )

    def __repr__(self) -> str:
        return f"<Supplier {self.company_name}>"


class SupplierPort(Base, TimestampMixin):
    """A supplier's service coverage for a specific port."""

    __tablename__ = "supplier_ports"

    supplier_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    port_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    lead_time_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    minimum_order: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    delivery_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    supplier: Mapped["Supplier"] = relationship(back_populates="ports")
    port: Mapped["Port"] = relationship(back_populates="supplier_ports")

    __table_args__ = (
        UniqueConstraint("supplier_id", "port_id", name="uq_supplier_port"),
    )


class ProductSupplier(Base, TimestampMixin):
    """A product offered by a supplier at a given price and lead time."""

    __tablename__ = "product_suppliers"

    supplier_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sku_supplier: Mapped[str | None] = mapped_column(String(100), nullable=True)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    min_order_qty: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_price_update: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    supplier: Mapped["Supplier"] = relationship(back_populates="products")
    product: Mapped["Product"] = relationship(back_populates="suppliers")

    __table_args__ = (
        UniqueConstraint("supplier_id", "product_id", name="uq_product_supplier"),
        Index("ix_product_suppliers_price", "unit_price"),
    )


class SupplierRating(Base, TimestampMixin, AuditMixin):
    """Per-order rating a vessel gives a supplier."""

    __tablename__ = "supplier_ratings"

    supplier_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    rating_overall: Mapped[int] = mapped_column(Integer, nullable=False)
    rating_reliability: Mapped[int] = mapped_column(Integer, nullable=False)
    rating_quality: Mapped[int] = mapped_column(Integer, nullable=False)
    rating_communication: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    on_time: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    response_hours: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    supplier: Mapped["Supplier"] = relationship(back_populates="ratings")

    __table_args__ = (
        CheckConstraint("rating_overall BETWEEN 1 AND 5", name="ck_rating_overall"),
        CheckConstraint("rating_reliability BETWEEN 1 AND 5", name="ck_rating_reliability"),
        CheckConstraint("rating_quality BETWEEN 1 AND 5", name="ck_rating_quality"),
        CheckConstraint("rating_communication BETWEEN 1 AND 5", name="ck_rating_communication"),
    )


class RFQ(Base, TimestampMixin, SoftDeleteMixin, AuditMixin):
    """A Request For Quotation issued to a set of suppliers for an order."""

    __tablename__ = "rfqs"

    reference: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    order_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    port_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ports.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    status: Mapped[RFQStatus] = mapped_column(Enum(RFQStatus), default=RFQStatus.DRAFT, nullable=False, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    awarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    awarded_quote_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)

    # Admin's uniform markup percentage applied to all quotes
    markup_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=0, nullable=False)

    invited_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    responded_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    order: Mapped["Order"] = relationship(back_populates="rfqs")
    items: Mapped[list["RFQItem"]] = relationship(back_populates="rfq", cascade="all, delete-orphan")
    quotes: Mapped[list["SupplierQuote"]] = relationship(back_populates="rfq", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_rfqs_status_deadline", "status", "response_deadline"),
    )


class RFQItem(Base, TimestampMixin):
    """A line item in an RFQ — mirrors the order's items."""

    __tablename__ = "rfq_items"

    rfq_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rfqs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Nullable: mirrors the change on order_items. The IMPA code is the
    # typed string the purchaser supplied, and the supplier is the
    # source of truth for the product. Legacy rows with a product_id
    # keep theirs.
    product_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), default="pcs", nullable=False)
    target_unit_price: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Denormalized from Product.impa_code at RFQ build time so the
    # supplier portal renders the IMPA reference without a join.
    impa_code: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)

    rfq: Mapped["RFQ"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()


class SupplierQuote(Base, TimestampMixin, AuditMixin):
    """A supplier's response to an RFQ — simplified single-form quote."""

    __tablename__ = "supplier_quotes"

    rfq_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rfqs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    supplier_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True
    )

    reference: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    subtotal: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    tax: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    shipping: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    total: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)

    lead_time_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    payment_terms: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Simplified flow: markup applied by admin
    # The supplier's original total (before markup)
    # marked_up_total = total * (1 + rfq.markup_pct / 100)
    marked_up_total: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    # What the purchaser sees (same as marked_up_total in this simplified flow)
    customer_facing_total: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)

    # Source
    source: Mapped[str] = mapped_column(String(20), default="portal", nullable=False)  # portal, email, api

    rfq: Mapped["RFQ"] = relationship(back_populates="quotes")
    supplier: Mapped["Supplier"] = relationship(back_populates="quotes")
    items: Mapped[list["QuoteItem"]] = relationship(back_populates="quote", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("rfq_id", "supplier_id", name="uq_rfq_supplier_quote"),
    )


class QuoteItem(Base, TimestampMixin):
    """A single line item in a supplier quote."""

    __tablename__ = "quote_items"

    quote_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("supplier_quotes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Supplier's per-line answer: full / partial / none
    line_status: Mapped[str] = mapped_column(String(10), nullable=False, default="full")
    # When partial, the custom quantity the supplier can supply
    quoted_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    quote: Mapped["SupplierQuote"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()

    __table_args__ = (
        CheckConstraint("line_status IN ('full', 'partial', 'none')", name="ck_quote_items_line_status"),
        CheckConstraint("quoted_quantity IS NULL OR quoted_quantity > 0", name="ck_quote_items_quoted_qty_positive"),
    )


# Note: The following tables have been REMOVED in the simplified marketplace:
# - OrderDecision (per-line supplier selection)
# - SupplierLineAssignment (24h slice acceptance)
# - BidComparison (sealed-bid engine)
# - market_sim_events (simulator timeline)