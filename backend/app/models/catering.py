"""
Catering, crew nutrition and provisioning models.

Domain: when a vessel is at sea, the chief steward plans daily menus around the
crew's nationalities, calculates required calories, and builds a provisioning
plan (a bill of materials) for the voyage. This module powers those workflows.
"""
import enum
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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
    from app.models.vessel import Vessel
    from app.models.product import Product


class CrewNationalityEnum(str, enum.Enum):
    FILIPINO = "filipino"
    INDIAN = "indian"
    EUROPEAN = "european"
    CHINESE = "chinese"
    TURKISH = "turkish"
    MYANMAR = "myanmar"
    UKRAINIAN = "ukrainian"
    AFRICAN = "african"
    OTHER = "other"


class MealType(str, enum.Enum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"
    MIDNIGHT = "midnight"


class DietFlag(str, enum.Enum):
    HALAL = "halal"
    KOSHER = "kosher"
    VEGETARIAN = "vegetarian"
    VEGAN = "vegan"
    GLUTEN_FREE = "gluten_free"
    LOW_SODIUM = "low_sodium"


class CrewNationality(Base, TimestampMixin):
    """Profile of how a nationality typically eats — drives the menu generator."""

    __tablename__ = "crew_nationalities"

    code: Mapped[CrewNationalityEnum] = mapped_column(Enum(CrewNationalityEnum), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Daily target calories per person (kcal)
    calorie_target: Mapped[int] = mapped_column(Integer, nullable=False)
    # Macros (% of calories). Defaults to a balanced 50/30/20 if not set.
    protein_pct: Mapped[float] = mapped_column(Float, default=0.20, nullable=False)
    carb_pct: Mapped[float] = mapped_column(Float, default=0.50, nullable=False)
    fat_pct: Mapped[float] = mapped_column(Float, default=0.30, nullable=False)
    # Default meal slots (JSON list of {type, time})
    default_meal_slots: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    # Diet flags that are typical for this cuisine
    preferred_diet_flags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    # Typical preferred product categories
    preferred_categories: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    # Notes for the chief steward
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("protein_pct + carb_pct + fat_pct = 1.0", name="ck_nationality_macros"),
        CheckConstraint("calorie_target > 0", name="ck_nationality_calories_positive"),
    )

    def __repr__(self) -> str:
        return f"<CrewNationality {self.code.value}: {self.calorie_target} kcal>"


class NutritionalInfo(Base, TimestampMixin):
    """Per-100g nutrition reference for products — used to compute menu calories."""

    __tablename__ = "nutritional_info"

    product_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    kcal_per_100g: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    protein_g: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    carbs_g: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    fat_g: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    fiber_g: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    sodium_mg: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    # Vegetarian / vegan / halal / kosher
    allergens: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    diet_flags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint("kcal_per_100g >= 0", name="ck_nutrition_kcal_positive"),
    )


class MenuTemplate(Base, TimestampMixin):
    """A reusable menu template per nationality + meal type."""

    __tablename__ = "menu_templates"

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    nationality: Mapped[CrewNationalityEnum] = mapped_column(
        Enum(CrewNationalityEnum), nullable=False, index=True
    )
    meal_type: Mapped[MealType] = mapped_column(Enum(MealType), nullable=False, index=True)
    target_kcal: Mapped[int] = mapped_column(Integer, nullable=False)
    diet_flags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    items: Mapped[list["MenuItem"]] = relationship(back_populates="template", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("nationality", "meal_type", "is_default", name="uq_menu_default_per_nationality"),
    )


class MenuItem(Base, TimestampMixin):
    """A single item within a menu template — references a product + serving size."""

    __tablename__ = "menu_items"

    template_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Grams per serving
    serving_grams: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    template: Mapped["MenuTemplate"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()


class DailyMenu(Base, TimestampMixin, AuditMixin):
    """A concrete menu used on a specific day for a vessel."""

    __tablename__ = "daily_menus"

    vessel_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vessels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    menu_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Computed totals for the day
    total_kcal: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    total_protein_g: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    total_carbs_g: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    total_fat_g: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)

    items: Mapped[list["MenuItem"] ] = []  # placeholder, populated via MealServing below

    __table_args__ = (
        UniqueConstraint("vessel_id", "menu_date", name="uq_daily_menu_vessel_date"),
    )


class MealServing(Base, TimestampMixin):
    """A specific (daily menu x menu template x meal type) serving record."""

    __tablename__ = "meal_servings"

    daily_menu_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("daily_menus.id", ondelete="CASCADE"), nullable=False, index=True
    )
    template_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_templates.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    meal_type: Mapped[MealType] = mapped_column(Enum(MealType), nullable=False)
    planned_servings: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_servings: Mapped[int | None] = mapped_column(Integer, nullable=True)

    daily_menu: Mapped["DailyMenu"] = relationship()
    template: Mapped["MenuTemplate"] = relationship()


class ProvisioningPlan(Base, TimestampMixin, AuditMixin):
    """A voyage provisioning plan — a bill of materials for the trip."""

    __tablename__ = "provisioning_plans"

    vessel_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vessels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    voyage_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    voyage_end: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    crew_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # Crew breakdown by nationality, e.g. {"filipino": 12, "indian": 8}
    crew_breakdown: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    buffer_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    buffer_pct: Mapped[float] = mapped_column(Float, default=0.15, nullable=False)

    total_kcal: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    estimated_cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    vessel: Mapped["Vessel"] = relationship(back_populates="provisioning_plans")
    items: Mapped[list["ProvisioningItem"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint("voyage_end >= voyage_start", name="ck_provisioning_dates"),
        CheckConstraint("crew_count > 0", name="ck_provisioning_crew_positive"),
    )


class ProvisioningItem(Base, TimestampMixin):
    """One product line in a provisioning plan with computed quantity."""

    __tablename__ = "provisioning_items"

    plan_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("provisioning_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    required_qty: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    per_day_grams: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    plan: Mapped["ProvisioningPlan"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()

    __table_args__ = (
        Index("ix_provisioning_items_plan_product", "plan_id", "product_id"),
        CheckConstraint("required_qty > 0", name="ck_provisioning_qty_positive"),
    )
