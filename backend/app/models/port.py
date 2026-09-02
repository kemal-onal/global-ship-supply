"""
Port, Country, and Customs Regulation models.
"""
import enum
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
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
    from app.models.supplier import SupplierPort


class RegionEnum(str, enum.Enum):
    AFRICA = "africa"
    ANTARCTICA = "antarctica"
    ASIA = "asia"
    EUROPE = "europe"
    NORTH_AMERICA = "north_america"
    OCEANIA = "oceania"
    SOUTH_AMERICA = "south_america"


class PortTypeEnum(str, enum.Enum):
    SEAPORT = "seaport"
    RIVER_PORT = "river_port"
    DRY_PORT = "dry_port"
    FISHING_PORT = "fishing_port"
    MARINA = "marina"
    OFFSHORE_TERMINAL = "offshore_terminal"
    ANCHORAGE = "anchorage"


class PortStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    RESTRICTED = "restricted"
    CLOSED = "closed"


class Country(Base, TimestampMixin, SoftDeleteMixin):
    """Country with regulatory and customs information."""

    __tablename__ = "countries"

    code_iso2: Mapped[str] = mapped_column(String(2), unique=True, nullable=False, index=True)
    code_iso3: Mapped[str] = mapped_column(String(3), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    official_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    region: Mapped[RegionEnum] = mapped_column(Enum(RegionEnum), nullable=False)
    subregion: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Customs & Trade
    customs_union: Mapped[str | None] = mapped_column(String(100), nullable=True)  # EU, GCC, ASEAN, etc.
    hs_code_length: Mapped[int] = mapped_column(Integer, default=8, nullable=False)  # HS code digits used
    de_minimis_value: Mapped[float | None] = mapped_column(nullable=True)  # Duty-free threshold (USD)
    vat_rate: Mapped[float | None] = mapped_column(nullable=True)  # Standard VAT rate

    # Restrictions
    prohibited_categories: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)  # e.g., ["pork", "alcohol", "narcotics"]
    restricted_categories: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)  # Require special permits
    requires_halal_cert: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_kosher_cert: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Logistics
    major_ports: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)  # List of port codes
    timezone: Mapped[str] = mapped_column(String(50), default="UTC", nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    languages: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    ports: Mapped[list["Port"]] = relationship(back_populates="country")
    regulations: Mapped[list["PortRegulation"]] = relationship(back_populates="country")
    customs_rules: Mapped[list["CustomsRule"]] = relationship(back_populates="country")

    __table_args__ = (
        Index("ix_countries_region", "region"),
        Index("ix_countries_customs_union", "customs_union"),
    )

    def __repr__(self) -> str:
        return f"<Country {self.code_iso2}: {self.name}>"


class Port(Base, TimestampMixin, SoftDeleteMixin, AuditMixin):
    """Port with facilities, services, and operational details."""

    __tablename__ = "ports"

    unlocode: Mapped[str] = mapped_column(String(5), unique=True, nullable=False, index=True)  # UN/LOCODE
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    country_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("countries.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    port_type: Mapped[PortTypeEnum] = mapped_column(Enum(PortTypeEnum), default=PortTypeEnum.SEAPORT, nullable=False)

    # Location
    latitude: Mapped[float] = mapped_column(nullable=False)
    longitude: Mapped[float] = mapped_column(nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC", nullable=False)

    # Operational
    status: Mapped[PortStatus] = mapped_column(Enum(PortStatus), default=PortStatus.ACTIVE, nullable=False, index=True)
    operating_hours: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # {day: {open, close}}
    max_vessel_loa: Mapped[float | None] = mapped_column(nullable=True)
    max_vessel_beam: Mapped[float | None] = mapped_column(nullable=True)
    max_draft: Mapped[float | None] = mapped_column(nullable=True)
    max_dwt: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Facilities
    has_bunkering: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_fresh_water: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_provisions: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_chandler: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_repair: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_medical: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_waste_reception: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_shore_power: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_cold_storage: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cranes_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_crane_capacity: Mapped[float | None] = mapped_column(nullable=True)

    # Services
    pilotage_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tugs_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    vts_mandatory: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    isps_level: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1, 2, or 3

    # Contact
    port_authority: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Time windows
    average_berth_wait_hours: Mapped[float | None] = mapped_column(nullable=True)
    average_turnaround_hours: Mapped[float | None] = mapped_column(nullable=True)
    working_days: Mapped[list[int] | None] = mapped_column(JSONB, nullable=True)  # 0=Mon, 6=Sun
    holidays: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)  # [{date, name}]

    # Relationships
    country: Mapped["Country"] = relationship(back_populates="ports")
    orders: Mapped[list["Order"]] = relationship(back_populates="port")
    regulations: Mapped[list["PortRegulation"]] = relationship(back_populates="port")
    supplier_ports: Mapped[list["SupplierPort"]] = relationship(back_populates="port")

    __table_args__ = (
        Index("ix_ports_country_status", "country_id", "status"),
        Index("ix_ports_location", "latitude", "longitude"),
        Index("ix_ports_type_status", "port_type", "status"),
    )

    def __repr__(self) -> str:
        return f"<Port {self.unlocode}: {self.name}>"


class RegulationCategory(str, enum.Enum):
    CUSTOMS = "customs"
    SANITARY_PHYTOSANITARY = "sanitary_phytosanitary"
    DANGEROUS_GOODS = "dangerous_goods"
    ENVIRONMENTAL = "environmental"
    CREW_WELFARE = "crew_welfare"
    SECURITY = "security"
    DOCUMENTATION = "documentation"
    QUARANTINE = "quarantine"
    OTHER = "other"


class RegulationSeverity(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    RESTRICTED = "restricted"
    PROHIBITED = "prohibited"
    BLOCKING = "blocking"


class PortRegulation(Base, TimestampMixin, SoftDeleteMixin, AuditMixin):
    """Port-specific regulations and restrictions."""

    __tablename__ = "port_regulations"

    port_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    country_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("countries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[RegulationCategory] = mapped_column(Enum(RegulationCategory), nullable=False, index=True)
    severity: Mapped[RegulationSeverity] = mapped_column(Enum(RegulationSeverity), default=RegulationSeverity.WARNING, nullable=False)

    # Regulation details
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    legal_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Applicability
    applies_to_categories: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)  # Product categories
    applies_to_hs_codes: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)  # HS code prefixes
    applies_to_impa_codes: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    applies_to_vessel_types: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    applies_to_flags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    # Conditions
    condition_expression: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSONLogic or similar
    requires_permit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    permit_authority: Mapped[str | None] = mapped_column(String(200), nullable=True)
    permit_lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Validity
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    is_permanent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Override
    can_override: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    override_roles: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)  # Roles that can override
    override_reason_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Metadata
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Relationships
    port: Mapped["Port"] = relationship(back_populates="regulations")
    country: Mapped["Country"] = relationship(back_populates="regulations")

    __table_args__ = (
        Index("ix_port_regulations_port_category", "port_id", "category"),
        Index("ix_port_regulations_effective", "effective_from", "effective_until"),
        Index("ix_port_regulations_severity", "severity"),
        Index("ix_port_regulations_applies", "applies_to_categories"),
    )

    def __repr__(self) -> str:
        return f"<PortRegulation {self.port_id}: {self.title}>"


class CustomsRule(Base, TimestampMixin, SoftDeleteMixin, AuditMixin):
    """Country-level customs rules for product classification."""

    __tablename__ = "customs_rules"

    country_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("countries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[RegulationCategory] = mapped_column(Enum(RegulationCategory), nullable=False, index=True)
    severity: Mapped[RegulationSeverity] = mapped_column(Enum(RegulationSeverity), default=RegulationSeverity.WARNING, nullable=False)

    # Rule details
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    hs_code_pattern: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)  # e.g., "0203.%" for pork
    impa_code_pattern: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    product_categories: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    # Rule logic (JSONLogic)
    condition: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)  # block, warn, require_permit, require_cert, tax_rate

    # Action parameters
    action_params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # e.g., {"tax_rate": 0.15, "permit_type": "health"}

    # Validity
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    # Metadata
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    country: Mapped["Country"] = relationship(back_populates="customs_rules")

    __table_args__ = (
        Index("ix_customs_rules_country_category", "country_id", "category"),
        Index("ix_customs_rules_effective", "effective_from", "effective_until"),
    )

    def __repr__(self) -> str:
        return f"<CustomsRule {self.country_id}: {self.name}>"