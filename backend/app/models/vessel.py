"""
Vessel models with specifications and fleet management.
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
    from app.models.user import User
    from app.models.order import Order
    from app.models.catering import ProvisioningPlan
    from app.models.sync import DeviceRegistration


class VesselTypeEnum(str, enum.Enum):
    CONTAINER = "container"
    BULK_CARRIER = "bulk_carrier"
    TANKER = "tanker"
    GENERAL_CARGO = "general_cargo"
    RO_RO = "ro_ro"
    REEFER = "reefer"
    LNG_CARRIER = "lng_carrier"
    LPG_CARRIER = "lpg_carrier"
    CHEMICAL_TANKER = "chemical_tanker"
    OFFSHORE = "offshore"
    PASSENGER = "passenger"
    FISHING = "fishing"
    RESEARCH = "research"
    NAVY = "navy"
    OTHER = "other"


class VesselStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    MAINTENANCE = "maintenance"
    DECOMMISSIONED = "decommissioned"
    LAID_UP = "laid_up"


class VesselType(Base, TimestampMixin):
    """Vessel type classifications with default specifications."""

    __tablename__ = "vessel_types"

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    typical_crew_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    typical_loa: Mapped[float | None] = mapped_column(nullable=True)  # Length overall (meters)
    typical_beam: Mapped[float | None] = mapped_column(nullable=True)  # Beam (meters)
    typical_draft: Mapped[float | None] = mapped_column(nullable=True)  # Draft (meters)
    typical_dwt: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Deadweight tonnage
    default_specifications: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    vessels: Mapped[list["Vessel"]] = relationship(back_populates="vessel_type_obj")

    def __repr__(self) -> str:
        return f"<VesselType {self.code}>"


class Vessel(Base, TimestampMixin, SoftDeleteMixin, AuditMixin):
    """Vessel/ship entity with full specifications."""

    __tablename__ = "vessels"

    imo_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    mmsi: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True, index=True)
    call_sign: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    vessel_type: Mapped[VesselTypeEnum] = mapped_column(Enum(VesselTypeEnum), nullable=False, index=True)
    vessel_type_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vessel_types.id", ondelete="SET NULL"), nullable=True
    )

    # Ownership/Operation
    owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    operator: Mapped[str | None] = mapped_column(String(200), nullable=True)
    flag_state: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    home_port: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fleet_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)  # Future: fleet model

    # Specifications
    loa: Mapped[float | None] = mapped_column(nullable=True)  # Length overall (meters)
    lbp: Mapped[float | None] = mapped_column(nullable=True)  # Length between perpendiculars
    beam: Mapped[float | None] = mapped_column(nullable=True)
    depth: Mapped[float | None] = mapped_column(nullable=True)
    draft_summer: Mapped[float | None] = mapped_column(nullable=True)
    draft_winter: Mapped[float | None] = mapped_column(nullable=True)
    dwt: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Deadweight tonnage
    gt: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Gross tonnage
    nt: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Net tonnage
    teu_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)  # For container ships

    # Crew & Operations
    crew_capacity: Mapped[int] = mapped_column(Integer, default=25, nullable=False)
    current_crew_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    min_safe_manning: Mapped[int] = mapped_column(Integer, default=10, nullable=False)

    # Communication
    vsat_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vsat_plan: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email_domain: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone_satellite: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Status & Tracking
    status: Mapped[VesselStatus] = mapped_column(Enum(VesselStatus), default=VesselStatus.ACTIVE, nullable=False, index=True)
    last_position_lat: Mapped[float | None] = mapped_column(nullable=True)
    last_position_lon: Mapped[float | None] = mapped_column(nullable=True)
    last_position_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_port_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    next_port_eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Certificates & Compliance
    certificates: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # SOLAS, MARPOL, ISM, etc.
    certificate_expiry_dates: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_ism_certified: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_mlc_certified: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    vessel_type_obj: Mapped["VesselType | None"] = relationship(back_populates="vessels")
    crew_members: Mapped[list["User"]] = relationship(back_populates="vessel")
    orders: Mapped[list["Order"]] = relationship(back_populates="vessel")
    provisioning_plans: Mapped[list["ProvisioningPlan"]] = relationship(back_populates="vessel")
    device_registrations: Mapped[list["DeviceRegistration"]] = relationship(back_populates="vessel")
    specifications: Mapped[list["VesselSpecification"]] = relationship(back_populates="vessel", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_vessels_fleet_status", "fleet_id", "status"),
        Index("ix_vessels_flag_status", "flag_state", "status"),
        Index("ix_vessels_next_port", "next_port_id", "next_port_eta"),
    )

    def __repr__(self) -> str:
        return f"<Vessel {self.name} (IMO: {self.imo_number})>"


class VesselSpecification(Base, TimestampMixin):
    """Detailed vessel specifications and equipment."""

    __tablename__ = "vessel_specifications"

    vessel_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vessels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # engine, navigation, cargo, safety, accommodation
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)  # manual, certificate, survey
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    vessel: Mapped["Vessel"] = relationship(back_populates="specifications")

    __table_args__ = (
        UniqueConstraint("vessel_id", "category", "key", name="uq_vessel_spec"),
        Index("ix_vessel_spec_vessel_category", "vessel_id", "category"),
    )


# Predefined vessel types
DEFAULT_VESSEL_TYPES = [
    {
        "code": "container",
        "name": "Container Ship",
        "description": "Designed to carry containerized cargo",
        "typical_crew_size": 22,
        "typical_loa": 350,
        "typical_beam": 48,
        "typical_draft": 15,
        "typical_dwt": 150000,
    },
    {
        "code": "bulk_carrier",
        "name": "Bulk Carrier",
        "description": "Designed to carry unpackaged bulk cargo",
        "typical_crew_size": 20,
        "typical_loa": 290,
        "typical_beam": 45,
        "typical_draft": 18,
        "typical_dwt": 180000,
    },
    {
        "code": "tanker",
        "name": "Oil Tanker",
        "description": "Designed to carry liquid cargo in bulk",
        "typical_crew_size": 24,
        "typical_loa": 330,
        "typical_beam": 60,
        "typical_draft": 20,
        "typical_dwt": 300000,
    },
    {
        "code": "general_cargo",
        "name": "General Cargo Ship",
        "description": "Carries packaged goods of various types",
        "typical_crew_size": 18,
        "typical_loa": 150,
        "typical_beam": 23,
        "typical_draft": 10,
        "typical_dwt": 15000,
    },
    {
        "code": "ro_ro",
        "name": "Roll-on/Roll-off Ship",
        "description": "Carries wheeled cargo",
        "typical_crew_size": 22,
        "typical_loa": 200,
        "typical_beam": 32,
        "typical_draft": 7,
        "typical_dwt": 20000,
    },
    {
        "code": "reefer",
        "name": "Refrigerated Cargo Ship",
        "description": "Carries perishable goods requiring temperature control",
        "typical_crew_size": 20,
        "typical_loa": 180,
        "typical_beam": 28,
        "typical_draft": 9,
        "typical_dwt": 12000,
    },
]