"""
Offline-first sync models.

When a vessel is at sea, VSAT connectivity drops. The mobile/desktop client queues
changes locally and replays them when the link is restored. The server tracks:

* SyncQueue       — per-device background sync job
* SyncConflict    — conflicts detected during replay
* OfflineAction   — every mutation performed offline (immutable audit)
* DeviceRegistration — issued device IDs / push tokens
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
    from app.models.vessel import Vessel


class SyncStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class ConflictResolution(str, enum.Enum):
    SERVER_WINS = "server_wins"
    CLIENT_WINS = "client_wins"
    MERGED = "merged"
    MANUAL = "manual"
    PENDING = "pending"


class DeviceRegistration(Base, TimestampMixin, SoftDeleteMixin):
    """A registered offline-capable device (laptop on board, mobile, etc.)."""

    __tablename__ = "device_registrations"

    device_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vessel_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vessels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False)  # web, ios, android, desktop
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    push_token: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Sync state
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cursor: Mapped[str | None] = mapped_column(String(255), nullable=True)  # Last server version seen
    is_online: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    vsat_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vsat_quality: Mapped[str | None] = mapped_column(String(20), nullable=True)  # good, fair, poor

    # Capabilities
    supports_indexeddb: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    supports_service_worker: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    storage_quota_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)

    user: Mapped["User"] = relationship(back_populates="device_registrations")
    vessel: Mapped["Vessel"] = relationship(back_populates="device_registrations")

    __table_args__ = (
        Index("ix_devices_user_vessel", "user_id", "vessel_id"),
        Index("ix_devices_last_sync", "last_sync_at"),
    )


class OfflineAction(Base, TimestampMixin):
    """An immutable record of a mutation that happened while offline.

    The mobile client writes one row per change to its local IndexedDB; on
    reconnect it POSTs the batch here for replay.
    """

    __tablename__ = "offline_actions"

    device_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Stable id assigned by the client; used for idempotency
    client_action_id: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    resource: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # orders, products, ...
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # create, update, delete
    entity_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    client_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sync_queue_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sync_queues.id", ondelete="SET NULL"), nullable=True, index=True
    )

    sync_queue: Mapped["SyncQueue | None"] = relationship(back_populates="actions")

    __table_args__ = (
        Index("ix_offline_actions_device_resource", "device_id", "resource"),
        Index("ix_offline_actions_received", "received_at"),
    )


class SyncQueue(Base, TimestampMixin, AuditMixin):
    """A batch sync job from a device."""

    __tablename__ = "sync_queues"

    device_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vessel_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vessels.id", ondelete="CASCADE"), nullable=False, index=True
    )

    status: Mapped[SyncStatus] = mapped_column(
        Enum(SyncStatus), default=SyncStatus.PENDING, nullable=False, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_actions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    applied_actions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_actions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    conflicts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    actions: Mapped[list["OfflineAction"]] = relationship(back_populates="sync_queue")
    conflict_records: Mapped[list["SyncConflict"]] = relationship(back_populates="sync_queue")

    __table_args__ = (
        Index("ix_sync_queues_device_status", "device_id", "status"),
    )


class SyncConflict(Base, TimestampMixin):
    """A conflict surfaced during replay (server version != client version)."""

    __tablename__ = "sync_conflicts"

    sync_queue_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sync_queues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resource: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    client_version: Mapped[dict] = mapped_column(JSONB, nullable=False)
    server_version: Mapped[dict] = mapped_column(JSONB, nullable=False)
    resolution: Mapped[ConflictResolution] = mapped_column(
        Enum(ConflictResolution), default=ConflictResolution.PENDING, nullable=False, index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    sync_queue: Mapped["SyncQueue"] = relationship(back_populates="conflict_records")

    __table_args__ = (
        Index("ix_sync_conflicts_entity", "resource", "entity_id"),
    )
