"""
Audit and security event models.

These tables are the foundation of the IDS/IPS layer described in the spec:
every request is fingerprinted and recorded; rate-limiting decisions and
authentication failures land here for the SOC dashboard.
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
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class AuditAction(str, enum.Enum):
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    LOGIN = "login"
    LOGOUT = "logout"
    LOGIN_FAILED = "login_failed"
    EXPORT = "export"
    IMPORT = "import"
    APPROVE = "approve"
    REJECT = "reject"
    SYNC = "sync"
    RFQ_SENT = "rfq_sent"
    QUOTE_SUBMITTED = "quote_submitted"
    ORDER_PLACED = "order_placed"
    OTHER = "other"


class AuditLog(Base, TimestampMixin):
    """Append-only audit trail — every mutation by a user."""

    __tablename__ = "audit_logs"

    user_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[AuditAction] = mapped_column(Enum(AuditAction), nullable=False, index=True)
    resource: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    resource_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Diff
    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Request context
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True, index=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    method: Mapped[str | None] = mapped_column(String(10), nullable=True)
    path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    user: Mapped["User | None"] = relationship(back_populates="audit_logs")

    __table_args__ = (
        Index("ix_audit_logs_user_action", "user_id", "action"),
    )


class SecurityEventType(str, enum.Enum):
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILURE = "login_failure"
    PASSWORD_RESET_REQUESTED = "password_reset_requested"
    PASSWORD_CHANGED = "password_changed"
    TWO_FA_ENABLED = "2fa_enabled"
    TWO_FA_FAILED = "2fa_failed"
    TOKEN_REFRESH = "token_refresh"
    TOKEN_REVOKED = "token_revoked"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    SUSPICIOUS_REQUEST = "suspicious_request"
    UNAUTHORIZED_ACCESS = "unauthorized_access"
    PERMISSION_DENIED = "permission_denied"
    BRUTE_FORCE_DETECTED = "brute_force_detected"
    PORT_SCAN_DETECTED = "port_scan_detected"
    SQL_INJECTION_ATTEMPT = "sql_injection_attempt"
    XSS_ATTEMPT = "xss_attempt"
    SESSION_HIJACK_SUSPECTED = "session_hijack_suspected"
    IP_BLOCKED = "ip_blocked"
    ACCOUNT_LOCKED = "account_locked"
    DEVICE_REGISTERED = "device_registered"
    SUSPICIOUS_GEO_MOVEMENT = "suspicious_geo_movement"


class SecuritySeverity(str, enum.Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SecurityEvent(Base, TimestampMixin):
    """IDS/IPS-like event log — for the SOC dashboard and alerting."""

    __tablename__ = "security_events"

    event_type: Mapped[SecurityEventType] = mapped_column(
        Enum(SecurityEventType), nullable=False, index=True
    )
    severity: Mapped[SecuritySeverity] = mapped_column(
        Enum(SecuritySeverity), default=SecuritySeverity.INFO, nullable=False, index=True
    )
    user_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True, index=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    user: Mapped["User | None"] = relationship(back_populates="security_events")

    __table_args__ = (
        Index("ix_security_events_type_severity", "event_type", "severity"),
        Index("ix_security_events_created", "created_at"),
    )
