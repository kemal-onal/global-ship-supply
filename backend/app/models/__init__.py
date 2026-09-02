"""
Database models package.
"""
from app.db.base import Base

# Import all models to register them with Base.metadata
from app.models.user import User, UserStatus, Role, Permission, UserRole, RolePermission
from app.models.vessel import Vessel, VesselType, VesselTypeEnum, VesselSpecification
from app.models.product import (
    Product,
    ProductCategory,
    ProductStatus,
    ImpaCode,
    IssaCode,
    ProductSpecification,
    UnitOfMeasure,
)
from app.models.order import Order, OrderItem, OrderStatus, OrderPriority
from app.models.catering import (
    CrewNationality,
    CrewNationalityEnum,
    MealType,
    DietFlag,
    MenuTemplate,
    MenuItem,
    NutritionalInfo,
    ProvisioningPlan,
    ProvisioningItem,
    DailyMenu,
    MealServing,
)
from app.models.supplier import (
    Supplier,
    SupplierStatus,
    SupplierPort,
    SupplierRating,
    ProductSupplier,
    RFQ,
    RFQItem,
    SupplierQuote,
    QuoteItem,
    BidComparison,
)
from app.models.port import (
    Country,
    Port,
    PortStatus,
    PortTypeEnum,
    RegionEnum,
    RegulationCategory,
    RegulationSeverity,
    PortRegulation,
    CustomsRule,
)
from app.models.sync import (
    SyncQueue,
    SyncConflict,
    OfflineAction,
    DeviceRegistration,
)
from app.models.audit import AuditLog, SecurityEvent
from app.models.ais import AisPositionReport, AisEventType, AisSource
from app.models.notification import Notification, NotificationType

__all__ = [
    "Base",
    "User", "Role", "Permission", "UserRole", "RolePermission",
    "Vessel", "VesselType", "VesselSpecification",
    "Port", "Country", "PortRegulation", "CustomsRule",
    "Product", "ProductCategory", "ImpaCode", "IssaCode",
    "ProductSpecification", "ProductSupplier",
    "Order", "OrderItem", "OrderStatus", "OrderPriority",
    "CrewNationality", "MenuTemplate", "MenuItem", "NutritionalInfo",
    "ProvisioningPlan", "ProvisioningItem", "DailyMenu", "MealServing",
    "Supplier", "SupplierPort", "SupplierRating",
    "RFQ", "RFQItem", "SupplierQuote", "QuoteItem", "BidComparison",
    "SyncQueue", "SyncConflict", "OfflineAction", "DeviceRegistration",
    "AuditLog", "SecurityEvent",
    "AisPositionReport", "AisEventType", "AisSource",
    "Notification", "NotificationType",
]
