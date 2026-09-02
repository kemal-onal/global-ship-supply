"""
Product catalog with IMPA/ISSA cross-reference, full-text search and B+ tree indexing.

The catalog must scale to millions of rows. We use PostgreSQL tsvector columns and
GIN indexes (the production equivalent of a B+ tree over token postings) for sub-50ms
Full-Text Search, and standard B+ tree indexes for SKUs, categories and price ranges.
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
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, AuditMixin, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.order import OrderItem
    from app.models.supplier import ProductSupplier


class ProductCategoryEnum(str, enum.Enum):
    """Top-level IMPA/ISSA categories — mirrors the printed catalog chapters."""

    DECK_STORES = "deck_stores"
    ENGINE_STORES = "engine_stores"
    CABIN_STORES = "cabin_stores"
    MEDICAL = "medical"
    PROVISIONS = "provisions"
    BOND_STORE = "bond_store"
    SAFETY = "safety"
    NAVIGATION = "navigation"
    ELECTRICAL = "electrical"
    CONSUMABLES = "consumables"
    LUBRICANTS = "lubricants"
    PAINT_CHEMICALS = "paint_chemicals"


class ProductStatus(str, enum.Enum):
    ACTIVE = "active"
    DISCONTINUED = "discontinued"
    HAZARDOUS = "hazardous"  # Treated specially by customs/regulation filter
    RESTRICTED = "restricted"


class UnitOfMeasure(str, enum.Enum):
    PIECE = "pcs"
    KILOGRAM = "kg"
    GRAM = "g"
    LITER = "l"
    METER = "m"
    SQUARE_METER = "m2"
    ROLL = "roll"
    BOX = "box"
    DRUM = "drum"
    BOTTLE = "bottle"
    CAN = "can"
    BAG = "bag"
    PAIR = "pair"
    SET = "set"
    PAIL = "pail"


class ProductCategory(Base, TimestampMixin):
    """Hierarchical category for products (deck, engine, provisions, ...)."""

    __tablename__ = "product_categories"

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_unit: Mapped[UnitOfMeasure] = mapped_column(
        Enum(UnitOfMeasure), default=UnitOfMeasure.PIECE, nullable=False
    )
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    children: Mapped[list["ProductCategory"]] = relationship()
    products: Mapped[list["Product"]] = relationship(back_populates="category")

    def __repr__(self) -> str:
        return f"<ProductCategory {self.code}: {self.name}>"


class ImpaCode(Base, TimestampMixin):
    """IMPA (International Marine Purchasing Association) 6-digit code cross-reference."""

    __tablename__ = "impa_codes"

    code: Mapped[str] = mapped_column(String(6), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    group_code: Mapped[str | None] = mapped_column(String(2), nullable=True, index=True)  # First 2 digits

    products: Mapped[list["Product"]] = relationship(back_populates="impa_code")

    __table_args__ = ()

    def __repr__(self) -> str:
        return f"<ImpaCode {self.code}: {self.name}>"


class IssaCode(Base, TimestampMixin):
    """ISSA (International Ship Suppliers Association) code cross-reference."""

    __tablename__ = "issa_codes"

    code: Mapped[str] = mapped_column(String(8), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    products: Mapped[list["Product"]] = relationship(back_populates="issa_code")

    def __repr__(self) -> str:
        return f"<IssaCode {self.code}: {self.name}>"


class Product(Base, TimestampMixin, SoftDeleteMixin, AuditMixin):
    """Catalog product — the heart of the search engine.

    Notes on indexing:
    * `sku`, `barcode` — B+ tree unique indexes (point lookups)
    * `name_tsv` / `description_tsv` — GIN indexes over tsvector (full-text search)
    * `unit_price` — B+ tree for range queries
    * `category_id`, `status` — composite B+ tree for filtered listing
    """

    __tablename__ = "products"

    sku: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    short_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    category_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_categories.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[ProductStatus] = mapped_column(
        Enum(ProductStatus), default=ProductStatus.ACTIVE, nullable=False, index=True
    )

    # Cross references
    impa_code_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("impa_codes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    issa_code_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("issa_codes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    hs_code: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)  # Harmonized Tariff
    barcode: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    manufacturer: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    part_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Units & measurements
    unit: Mapped[UnitOfMeasure] = mapped_column(Enum(UnitOfMeasure), default=UnitOfMeasure.PIECE, nullable=False)
    weight_kg: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    volume_m3: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    dimensions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # {l, w, h}

    # Pricing
    unit_price: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    min_order_qty: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Inventory
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    stock_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, default=14, nullable=False)

    # Compliance & metadata
    is_hazardous: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_perishable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    shelf_life_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requires_certificates: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    # Tags for fast filtering (e.g. ["halal", "kosher", "vegan"])
    tags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Full-text search vectors — kept in sync by application code (simpler than triggers).
    # For high-volume sync we recommend a trigger; the application writes both columns
    # when content changes.
    name_tsv: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)
    description_tsv: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)
    full_tsv: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)

    # Relationships
    category: Mapped["ProductCategory"] = relationship(back_populates="products")
    impa_code: Mapped["ImpaCode | None"] = relationship(back_populates="products")
    issa_code: Mapped["IssaCode | None"] = relationship(back_populates="products")
    specifications: Mapped[list["ProductSpecification"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    suppliers: Mapped[list["ProductSupplier"]] = relationship(back_populates="product")
    order_items: Mapped[list["OrderItem"]] = relationship(back_populates="product")

    __table_args__ = (
        # B+ tree composite indexes
        Index("ix_products_status_category", "status", "category_id"),
        # GIN indexes over tsvector — these are the workhorses of the FTS engine
        Index("ix_products_name_tsv", "name_tsv", postgresql_using="gin"),
        Index("ix_products_full_tsv", "full_tsv", postgresql_using="gin"),
        # GIN over JSONB tags so we can filter by tag efficiently
        Index("ix_products_tags", "tags", postgresql_using="gin"),
        CheckConstraint("unit_price >= 0", name="ck_products_price_positive"),
        CheckConstraint("min_order_qty > 0", name="ck_products_min_qty_positive"),
    )

    def __repr__(self) -> str:
        return f"<Product {self.sku}: {self.name}>"


class ProductSpecification(Base, TimestampMixin):
    """Free-form spec fields per product (e.g. "thread size": "M10")."""

    __tablename__ = "product_specifications"

    product_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    product: Mapped["Product"] = relationship(back_populates="specifications")

    __table_args__ = (
        UniqueConstraint("product_id", "key", name="uq_product_spec"),
    )
