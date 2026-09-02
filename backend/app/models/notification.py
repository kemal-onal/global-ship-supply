"""
Notifications — per-user inbox items.

Each row is a single message addressed to a specific ``user_id``. The
frontend polls ``/notifications/unread-count`` every 30s and refetches
``/notifications`` when the bell panel opens. Read state is tracked with
a nullable ``read_at`` timestamp (NULL = unread).

Created automatically by ``app/services/notifications.py`` when the
``Order`` state machine transitions; future call sites (RFQ awards,
system messages) can write to the same table.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class NotificationType(str, enum.Enum):
    """Discriminator for the source/event that produced a notification.

    Kept small and stable. If a row's ``type`` is no longer recognised
    by the frontend, it should still render with a generic icon.
    """

    ORDER_TRANSITION = "order_transition"
    RFQ_AWARDED = "rfq_awarded"
    SYSTEM = "system"


class Notification(Base):
    """One notification row in a user's inbox.

    ``data`` carries event-type-specific structured data used by the
    frontend to deeplink and to render icons / formatting — for an
    ``order_transition`` row it holds
    ``{"order_id", "reference", "old_status", "new_status"}``.
    """

    __tablename__ = "notifications"

    user_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # ``values_callable`` keeps the Postgres enum values lowercase
    # (matches the model pattern in ``app/models/ais.py``).
    type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.utcnow(),
        server_default=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship("User", lazy="joined")

    __table_args__ = (
        # Common query: "latest notifications for user X".
        Index("ix_notifications_user_created", "user_id", "created_at"),
        # Common query: "unread count for user X" (also covered by the
        # composite above, but Postgres can use this when the planner
        # skips the created_at sort).
        Index("ix_notifications_user_read", "user_id", "read_at"),
    )

    def __repr__(self) -> str:
        return f"<Notification {self.id} type={self.type.value} user={self.user_id}>"

    @property
    def is_unread(self) -> bool:
        return self.read_at is None


__all__ = ["Notification", "NotificationType"]
