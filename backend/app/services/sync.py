"""
Offline sync service.

Receives a batch of OfflineAction records from a vessel, replays them in order,
detects conflicts, and produces a SyncQueue summary.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.audit import AuditAction, AuditLog
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product
from app.models.sync import (
    ConflictResolution,
    DeviceRegistration,
    OfflineAction,
    SyncConflict,
    SyncQueue,
    SyncStatus,
)
from app.models.user import User

log = get_logger("avs.sync")


def _coerce_uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except (TypeError, ValueError):
        return None


async def replay_actions(
    db: AsyncSession,
    *,
    user: User,
    device_id: str,
    actions: list[dict[str, Any]],
) -> SyncQueue:
    """Replay a batch of offline actions in order, detecting conflicts.

    `actions` is a list of {client_action_id, resource, action, entity_id, payload, client_timestamp}.
    """
    # 1) Register / refresh device
    device = (await db.execute(
        select(DeviceRegistration).where(DeviceRegistration.device_id == device_id)
    )).scalar_one_or_none()
    if not device:
        device = DeviceRegistration(
            device_id=device_id,
            user_id=user.id,
            vessel_id=user.vessel_id,
            platform="web",
        )
        db.add(device)
    device.last_seen_at = datetime.now(timezone.utc)
    device.last_sync_at = datetime.now(timezone.utc)

    queue = SyncQueue(
        device_id=device_id,
        user_id=user.id,
        vessel_id=user.vessel_id,
        total_actions=len(actions),
    )
    db.add(queue)
    await db.flush()

    applied = 0
    failed = 0
    conflicts = 0
    for act in actions:
        try:
            offline = OfflineAction(
                device_id=device_id,
                user_id=user.id,
                client_action_id=act["client_action_id"],
                resource=act["resource"],
                action=act["action"],
                entity_id=act.get("entity_id"),
                payload=act["payload"],
                client_timestamp=datetime.fromisoformat(act["client_timestamp"].replace("Z", "+00:00")),
                sync_queue_id=queue.id,
            )
            db.add(offline)
            await db.flush()

            resource = act["resource"]
            payload = act["payload"]

            if resource == "orders":
                await _replay_order(db, user, act, payload, offline)
            elif resource == "order_items":
                await _replay_order_item(db, user, act, payload, offline)
            else:
                raise ValueError(f"Unsupported resource: {resource}")

            offline.applied_at = datetime.now(timezone.utc)
            applied += 1
        except _ConflictError as ce:
            offline.error = str(ce)
            db.add(SyncConflict(
                sync_queue_id=queue.id,
                resource=act["resource"],
                entity_id=act.get("entity_id") or "",
                client_version=act["payload"],
                server_version=ce.server_version,
                resolution=ConflictResolution.PENDING,
                notes=str(ce),
            ))
            conflicts += 1
        except Exception as exc:  # noqa: BLE001
            offline.error = f"{type(exc).__name__}: {exc}"
            failed += 1
            log.warning("sync.replay_failed", action_id=act.get("client_action_id"), error=str(exc))

    queue.applied_actions = applied
    queue.failed_actions = failed
    queue.conflicts = conflicts
    queue.status = (
        SyncStatus.COMPLETED if failed == 0 and conflicts == 0
        else SyncStatus.PARTIAL if applied > 0
        else SyncStatus.FAILED
    )
    queue.finished_at = datetime.now(timezone.utc)

    # Audit
    db.add(AuditLog(
        user_id=user.id,
        action=AuditAction.SYNC,
        resource="sync_queue",
        resource_id=str(queue.id),
        description=f"Offline sync replay: {applied}/{len(actions)} applied, {conflicts} conflicts, {failed} failed",
    ))

    return queue


class _ConflictError(Exception):
    def __init__(self, message: str, server_version: dict):
        super().__init__(message)
        self.server_version = server_version


async def _replay_order(
    db: AsyncSession, user: User, act: dict, payload: dict, offline: OfflineAction
) -> None:
    """Replay an order create/update. Conflict if server's updated_at is newer
    than the client's `client_updated_at` payload field."""
    client_updated = payload.get("client_updated_at")
    if act["action"] == "create":
        # Map a few fields; the rest is up to the route handler
        vessel_uuid = _coerce_uuid(payload.get("vessel_id")) or user.vessel_id
        port_uuid = _coerce_uuid(payload.get("port_id"))
        if not vessel_uuid or not port_uuid:
            raise ValueError("vessel_id and port_id are required for offline order create")
        order = Order(
            reference=f"OFF-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{offline.client_action_id[:6]}",
            vessel_id=vessel_uuid,
            port_id=port_uuid,
            status=OrderStatus.DRAFT,
            customer_notes=payload.get("customer_notes"),
            source="offline",
            client_id=offline.client_action_id,
            client_created_at=offline.client_timestamp,
            created_by=user.id,
        )
        db.add(order)
        await db.flush()
        for li in payload.get("items", []):
            db.add(OrderItem(
                order_id=order.id,
                product_id=_coerce_uuid(li["product_id"]),
                quantity=int(li["quantity"]),
                unit=li.get("unit", "pcs"),
                unit_price=float(li.get("unit_price", 0)),
                line_total=float(li.get("unit_price", 0)) * int(li["quantity"]),
            ))
    elif act["action"] == "update":
        entity_uuid = _coerce_uuid(act.get("entity_id"))
        if not entity_uuid:
            raise ValueError("entity_id required for update")
        existing = (await db.execute(select(Order).where(Order.id == entity_uuid))).scalar_one_or_none()
        if not existing:
            raise ValueError("Order not found")
        if client_updated and existing.updated_at and existing.updated_at > datetime.fromisoformat(client_updated.replace("Z", "+00:00")):
            raise _ConflictError(
                "Server version newer than client",
                server_version={"updated_at": existing.updated_at.isoformat()},
            )
        for k in ("status", "customer_notes", "internal_notes"):
            if k in payload and payload[k] is not None:
                setattr(existing, k, payload[k])
        existing.synced_at = datetime.now(timezone.utc)
    else:
        raise ValueError(f"Unsupported order action: {act['action']}")


async def _replay_order_item(
    db: AsyncSession, user: User, act: dict, payload: dict, offline: OfflineAction
) -> None:
    if act["action"] != "create":
        raise ValueError(f"Unsupported order_item action: {act['action']}")
    order_uuid = _coerce_uuid(payload.get("order_id"))
    if not order_uuid:
        raise ValueError("order_id required")
    order = (await db.execute(select(Order).where(Order.id == order_uuid))).scalar_one_or_none()
    if not order:
        raise ValueError("Order not found")
    db.add(OrderItem(
        order_id=order.id,
        product_id=_coerce_uuid(payload["product_id"]),
        quantity=int(payload["quantity"]),
        unit=payload.get("unit", "pcs"),
        unit_price=float(payload.get("unit_price", 0)),
        line_total=float(payload.get("unit_price", 0)) * int(payload["quantity"]),
    ))
