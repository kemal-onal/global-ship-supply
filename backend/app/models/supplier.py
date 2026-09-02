"""
Supplier, RFQ (Request For Quotation) and Bid Comparison models.

Drives the dynamic bidding engine: when a vessel places an order, the system
sends an RFQ to every registered supplier at the destination port. Suppliers
respond with quotes; the engine scores and ranks them.
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
    DRAFT = "draft"
    SENT = "sent"
    OPEN = "open"
    CLOSED = "closed"
    AWARDED = "awarded"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


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
    product_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), default="pcs", nullable=False)
    target_unit_price: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    rfq: Mapped["RFQ"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()


class SupplierQuote(Base, TimestampMixin, AuditMixin):
    """A supplier's response to an RFQ — the unit of the bidding engine."""

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

    # Engine-computed score (0..1) used for ranking
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False, index=True)
    is_awarded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_rejected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Source
    source: Mapped[str] = mapped_column(String(20), default="email", nullable=False)  # email, portal, api

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

    quote: Mapped["SupplierQuote"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()


class BidComparison(Base, TimestampMixin, AuditMixin):
    """Snapshot of a bid evaluation — keeps history of how the engine ranked quotes."""

    __tablename__ = "bid_comparisons"

    rfq_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rfqs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    weights: Mapped[dict] = mapped_column(JSONB, nullable=False)  # {price, lead_time, reliability, quality}
    results: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)  # [{supplier_id, scores, weighted}]
    winner_quote_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
