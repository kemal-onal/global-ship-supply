"""
User, Role, and Permission models for RBAC.
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
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, AuditMixin, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.vessel import Vessel


class UserStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    PENDING_VERIFICATION = "pending_verification"
    LOCKED = "locked"


class Permission(Base, TimestampMixin):
    """Granular permissions for RBAC."""

    __tablename__ = "permissions"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # e.g., "orders", "products", "vessels"
    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # e.g., "create", "read", "update", "delete", "approve"
    scope: Mapped[str] = mapped_column(
        String(20), default="own", nullable=False
    )  # own, vessel, fleet, global

    # Relationships
    roles: Mapped[list["RolePermission"]] = relationship(back_populates="permission")

    __table_args__ = (
        Index("ix_permissions_resource_action", "resource", "action"),
        Index("ix_permissions_resource_action_scope", "resource", "action", "scope"),
    )

    def __repr__(self) -> str:
        return f"<Permission {self.resource}:{self.action}:{self.scope}>"


class Role(Base, TimestampMixin):
    """Roles for grouping permissions."""

    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    priority: Mapped[int] = mapped_column(default=0, nullable=False)  # Higher = more privileges

    # Relationships
    permissions: Mapped[list["RolePermission"]] = relationship(back_populates="role")
    users: Mapped[list["UserRole"]] = relationship(back_populates="role")

    def __repr__(self) -> str:
        return f"<Role {self.name}>"


class RolePermission(Base, TimestampMixin):
    """Many-to-many relationship between roles and permissions."""

    __tablename__ = "role_permissions"

    role_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    role: Mapped["Role"] = relationship(back_populates="permissions")
    permission: Mapped["Permission"] = relationship(back_populates="roles")

    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
    )


class User(Base, TimestampMixin, SoftDeleteMixin, AuditMixin):
    """User accounts with authentication and profile data."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus), default=UserStatus.PENDING_VERIFICATION, nullable=False, index=True
    )

    # Authentication
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    two_factor_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    two_factor_secret: Mapped[str | None] = mapped_column(String(32), nullable=True)
    backup_codes: Mapped[list[str] | None] = mapped_column(Text, nullable=True)  # JSON array

    # Session management
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    failed_login_attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Password management
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_reset_token: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    password_reset_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Vessel association (for vessel-scoped users)
    vessel_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vessels.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Preferences
    language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC", nullable=False)
    theme: Mapped[str] = mapped_column(String(20), default="system", nullable=False)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    roles: Mapped[list["UserRole"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    vessel: Mapped["Vessel | None"] = relationship(back_populates="crew_members")
    orders_created: Mapped[list["Order"]] = relationship(back_populates="created_by_user", foreign_keys="Order.created_by")
    orders_assigned: Mapped[list["Order"]] = relationship(back_populates="assigned_to_user", foreign_keys="Order.assigned_to")
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="user")
    security_events: Mapped[list["SecurityEvent"]] = relationship(back_populates="user")
    device_registrations: Mapped[list["DeviceRegistration"]] = relationship(back_populates="user")

    __table_args__ = (
        Index("ix_users_email_status", "email", "status"),
        Index("ix_users_vessel_status", "vessel_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<User {self.email}>"

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE and not self.is_deleted

    def get_permissions(self) -> set[str]:
        """Get all permissions for this user through their roles."""
        perms = set()
        for user_role in self.roles:
            if user_role.role:
                for rp in user_role.role.permissions:
                    if rp.permission:
                        perms.add(f"{rp.permission.resource}:{rp.permission.action}:{rp.permission.scope}")
        return perms

    def get_roles(self) -> list[str]:
        return [ur.role.name for ur in self.roles if ur.role]

    def has_permission(self, resource: str, action: str, scope: str = "own") -> bool:
        perm = f"{resource}:{action}:{scope}"
        return perm in self.get_permissions()

    def has_role(self, role_name: str) -> bool:
        return role_name in self.get_roles()


class UserRole(Base, TimestampMixin):
    """Many-to-many relationship between users and roles with vessel/fleet scoping."""

    __tablename__ = "user_roles"

    user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vessel_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vessels.id", ondelete="SET NULL"), nullable=True, index=True
    )
    fleet_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)  # Future: fleet model
    assigned_by: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="roles")
    role: Mapped["Role"] = relationship(back_populates="users")
    vessel: Mapped["Vessel | None"] = relationship()

    __table_args__ = (
        UniqueConstraint("user_id", "role_id", "vessel_id", name="uq_user_role_vessel"),
        Index("ix_user_roles_user_vessel", "user_id", "vessel_id"),
        Index("ix_user_roles_expires", "expires_at"),
    )


# Predefined system roles
SYSTEM_ROLES = [
    {
        "name": "super_admin",
        "description": "Full system access across all vessels and fleets",
        "is_system": True,
        "priority": 100,
    },
    {
        "name": "fleet_admin",
        "description": "Administrative access to assigned fleet",
        "is_system": True,
        "priority": 80,
    },
    {
        "name": "vessel_captain",
        "description": "Command authority on assigned vessel",
        "is_system": True,
        "priority": 70,
    },
    {
        "name": "purchasing_officer",
        "description": "Manages procurement and orders for vessel/fleet",
        "is_system": True,
        "priority": 60,
    },
    {
        "name": "chief_steward",
        "description": "Manages catering, provisions, and crew welfare",
        "is_system": True,
        "priority": 55,
    },
    {
        "name": "supplier",
        "description": "External supplier portal access",
        "is_system": True,
        "priority": 30,
    },
    {
        "name": "port_authority",
        "description": "Port customs and regulatory access",
        "is_system": True,
        "priority": 40,
    },
    {
        "name": "viewer",
        "description": "Read-only access to assigned scope",
        "is_system": True,
        "priority": 10,
    },
]

# Predefined permissions
SYSTEM_PERMISSIONS = [
    # User management
    ("users", "create", "global"),
    ("users", "read", "global"),
    ("users", "update", "global"),
    ("users", "delete", "global"),
    ("users", "manage_roles", "global"),
    # Vessel management
    ("vessels", "create", "global"),
    ("vessels", "read", "global"),
    ("vessels", "update", "global"),
    ("vessels", "delete", "global"),
    ("vessels", "read", "fleet"),
    ("vessels", "update", "fleet"),
    ("vessels", "read", "own"),
    ("vessels", "update", "own"),
    # Port management
    ("ports", "create", "global"),
    ("ports", "read", "global"),
    ("ports", "update", "global"),
    # Product/Catalog management
    ("products", "create", "global"),
    ("products", "read", "global"),
    ("products", "update", "global"),
    ("products", "delete", "global"),
    ("products", "read", "own"),
    ("impa_codes", "manage", "global"),
    ("issa_codes", "manage", "global"),
    # Order management
    ("orders", "create", "own"),
    ("orders", "read", "own"),
    ("orders", "update", "own"),
    ("orders", "delete", "own"),
    ("orders", "approve", "own"),
    ("orders", "create", "vessel"),
    ("orders", "read", "vessel"),
    ("orders", "update", "vessel"),
    ("orders", "approve", "vessel"),
    ("orders", "read", "fleet"),
    ("orders", "approve", "fleet"),
    ("orders", "read", "global"),
    ("orders", "manage", "global"),
    # Catering
    ("catering", "create", "own"),
    ("catering", "read", "own"),
    ("catering", "update", "own"),
    ("catering", "manage", "vessel"),
    ("catering", "manage", "fleet"),
    ("menus", "create", "own"),
    ("menus", "read", "own"),
    ("menus", "update", "own"),
    ("provisioning", "create", "own"),
    ("provisioning", "read", "own"),
    ("provisioning", "manage", "vessel"),
    # Supplier management
    ("suppliers", "create", "global"),
    ("suppliers", "read", "global"),
    ("suppliers", "update", "global"),
    ("suppliers", "manage", "global"),
    ("rfq", "create", "own"),
    ("rfq", "read", "own"),
    ("rfq", "manage", "vessel"),
    ("rfq", "manage", "fleet"),
    ("rfq", "simulate", "own"),
    ("quotes", "submit", "own"),
    ("quotes", "read", "own"),
    ("quotes", "compare", "own"),
    # Regulations
    ("regulations", "read", "global"),
    ("regulations", "manage", "global"),
    ("customs", "check", "own"),
    # Sync/Offline
    ("sync", "manage", "own"),
    ("sync", "manage", "vessel"),
    ("offline_queue", "read", "own"),
    ("offline_queue", "manage", "own"),
    # Reports
    ("reports", "read", "own"),
    ("reports", "read", "vessel"),
    ("reports", "read", "fleet"),
    ("reports", "read", "global"),
    ("analytics", "read", "global"),
    # Settings
    ("settings", "read", "own"),
    ("settings", "update", "own"),
    ("settings", "manage", "global"),
    # Marketplace redesign (migration 0005) — admin composes,
    # purchaser approves, company asks for clarification, admin
    # drops slow suppliers. The bid war's `rfq:*` / `quotes:*`
    # permissions stay; they're the engine's read side and don't
    # conflict with the new flow.
    ("marketplace", "compose", "global"),
    ("marketplace", "approve", "own"),
    ("marketplace", "clarify", "global"),
    ("marketplace", "drop", "global"),
    ("supplier_portal", "view", "global"),
    ("supplier_portal", "quote", "global"),
    ("supplier_portal", "accept", "global"),
]