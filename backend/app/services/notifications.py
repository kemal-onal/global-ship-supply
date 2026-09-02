"""
Notification service — small, focused helpers for creating notification
rows. All call sites use ``create_notification`` directly; the
``notify_order_transition`` helper exists to centralise the
"who gets pinged and what does the message say" decision for the
most common trigger.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationType
from app.models.order import Order, OrderStatus


async def create_notification(
    db: AsyncSession,
    *,
    user_id: UUID | str,
    type: NotificationType,
    title: str,
    body: str | None = None,
    data: dict[str, Any] | None = None,
) -> Notification:
    """Insert a single notification row and flush (so ``id`` is populated).

    The caller is responsible for ``commit`` (we share the same session
    as the surrounding request handler, which commits once at the end).
    """
    n = Notification(
        user_id=user_id,
        type=type,
        title=title,
        body=body,
        data=data,
    )
    db.add(n)
    await db.flush()
    return n


# A small map of status -> human-readable label. Keeping it inline here
# (rather than reaching into a translation table) is fine for v1; if we
# grow more triggers we can move it to a templates module.
_ORDER_STATUS_LABEL = {
    OrderStatus.DRAFT: "draft",
    OrderStatus.PENDING_APPROVAL: "pending approval",
    OrderStatus.RFQ_IN_PROGRESS: "RFQ in progress",
    OrderStatus.BIDDING: "in bidding",
    OrderStatus.AWAITING_CONFIRMATION: "awaiting confirmation",
    OrderStatus.CONFIRMED: "confirmed",
    OrderStatus.IN_TRANSIT: "in transit",
    OrderStatus.DELIVERED: "delivered",
    OrderStatus.COMPLETED: "completed",
    OrderStatus.CANCELLED: "cancelled",
    OrderStatus.REJECTED: "rejected",
}


async def notify_order_transition(
    db: AsyncSession,
    order: Order,
    old_status: OrderStatus,
    *,
    actor_id: str | UUID | None = None,
) -> Notification | None:
    """Create a notification when ``order`` changes status.

    Recipient policy:
      * Prefer ``order.assigned_to`` (the user the order is routed to).
      * Fall back to ``order.created_by`` so the creator also sees the
        change if nobody has taken ownership.
      * If neither is set (shouldn't happen, but be defensive) we skip.

    The actor (the user who triggered the transition) is *not* notified
    for their own action — that would be self-spam. We do this by simply
    resolving the recipient and bailing out if it equals ``actor_id``.
    """
    recipient = order.assigned_to or order.created_by
    if recipient is None:
        return None

    if actor_id is not None and str(actor_id) == str(recipient):
        return None

    new_label = _ORDER_STATUS_LABEL.get(order.status, order.status.value)
    title = f"Order {order.reference} is now {new_label}"
    body = f"Status changed from {old_status.value} to {order.status.value}."

    return await create_notification(
        db,
        user_id=recipient,
        type=NotificationType.ORDER_TRANSITION,
        title=title,
        body=body,
        data={
            "order_id": str(order.id),
            "reference": order.reference,
            "old_status": old_status.value,
            "new_status": order.status.value,
        },
    )


__all__ = ["create_notification", "notify_order_transition"]
