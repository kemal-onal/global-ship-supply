"""Clarification loop routes — marketplace redesign.

The company (admin) asks a question on an order, the purchaser
answers, the company marks the thread resolved. Until that loop
is closed, the RFQ fan-out step refuses to proceed.

Routes:
  POST  /api/v1/orders/{order_id}/clarify            [admin]
  POST  /api/v1/orders/{order_id}/answer             [purchaser]
  POST  /api/v1/orders/{order_id}/resolve-clarification  [admin]
  GET   /api/v1/orders/{order_id}/clarification      [admin or purchaser]

The clarify/answer/resolve routes are split per-action because
the body shape differs (different IDs + different role checks).
A single "PATCH" with an action discriminator would compress
them but makes the openapi less searchable, so we keep them
split.

The status transition is owned by the service layer
(``app.services.clarification``); the routes just translate
HTTP into service calls and write the audit log.
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.deps.auth import (
    CurrentToken,
    DBSession,
    assert_vessel_access,
    require_permission,
)
from app.models.audit import AuditAction, AuditLog
from app.models.order import Order
from app.services import clarification as clarification_svc
from app.services.notifications import create_notification
from app.models.notification import NotificationType

router = APIRouter()


class ClarifyIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class AnswerIn(BaseModel):
    clarification_id: str = Field(min_length=1)
    answer: str = Field(min_length=1, max_length=2000)


class ResolveIn(BaseModel):
    clarification_id: str = Field(min_length=1)


async def _load_order_or_404(db, order_id: UUID, token) -> Order:
    o = (await db.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    await assert_vessel_access(token, o.vessel_id)
    return o


@router.post("/orders/{order_id}/clarify")
async def ask(
    order_id: UUID,
    payload: ClarifyIn,
    db: DBSession,
    token: Annotated[CurrentToken, Depends(require_permission("marketplace", "clarify", "global"))],
):
    order = await _load_order_or_404(db, order_id, token)
    try:
        entry = await clarification_svc.ask_clarification(
            db, order, question=payload.question, asked_by=str(token.sub)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Notify the order's creator (the purchaser) so they see the
    # question in the notification list. The notification service
    # no-ops if the recipient is the actor (self-spam guard).
    await create_notification(
        db,
        user_id=order.created_by,
        type=NotificationType.CLARIFICATION_REQUESTED,
        title=f"Clarification requested on {order.reference}",
        body=payload.question[:200],
        data={"order_id": str(order.id), "clarification_id": entry["id"]},
    )
    db.add(AuditLog(
        user_id=token.sub,
        # Bind the value (lowercase) explicitly. The PG enum
        # was extended by migration 0006 with the *value* of
        # each new audit action, but the model column is
        # `Enum(AuditAction)` without `values_callable`
        # (see app/models/audit.py), so the default bind goes
        # via the *name* (uppercase) — which is not in the PG
        # enum for these entries. Even with `values_callable`
        # added to the model (migration 0008), binding the
        # value here keeps this row's behaviour independent
        # of the column's serialization choice.
        action=AuditAction.CLARIFICATION_REQUESTED.value,
        resource="orders",
        resource_id=str(order.id),
        description=f"Clarification asked on {order.reference}",
        extra={"clarification_id": entry["id"]},
    ))
    await db.commit()
    return {"order_id": str(order.id), "entry": entry, "status": order.status.value}


@router.post("/orders/{order_id}/answer")
async def answer(
    order_id: UUID,
    payload: AnswerIn,
    db: DBSession,
    token: Annotated[CurrentToken, Depends(require_permission("marketplace", "approve", "own"))],
):
    order = await _load_order_or_404(db, order_id, token)
    try:
        entry = await clarification_svc.answer_clarification(
            db, order, entry_id=payload.clarification_id, answer=payload.answer, answered_by=str(token.sub)
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Notify the company (admins). We broadcast to all super_admins
    # by fanning out notifications; the notification service keeps
    # a per-user inbox so a single fan-out is fine.
    from app.models.user import Role, UserRole
    admins = (await db.execute(
        select(UserRole.user_id).join(Role, Role.id == UserRole.role_id).where(Role.name == "super_admin")
    )).scalars().all()
    for admin_id in admins:
        await create_notification(
            db,
            user_id=admin_id,
            type=NotificationType.CLARIFICATION_ANSWERED,
            title=f"Clarification answered on {order.reference}",
            body=payload.answer[:200],
            data={"order_id": str(order.id), "clarification_id": entry["id"]},
        )
    db.add(AuditLog(
        user_id=token.sub,
        action=AuditAction.UPDATE,
        resource="orders",
        resource_id=str(order.id),
        description=f"Clarification answered on {order.reference}",
        extra={"clarification_id": entry["id"]},
    ))
    await db.commit()
    return {"order_id": str(order.id), "entry": entry, "status": order.status.value}


@router.post("/orders/{order_id}/resolve-clarification")
async def resolve(
    order_id: UUID,
    payload: ResolveIn,
    db: DBSession,
    token: Annotated[CurrentToken, Depends(require_permission("marketplace", "clarify", "global"))],
):
    order = await _load_order_or_404(db, order_id, token)
    try:
        entry = await clarification_svc.resolve_clarification(
            db, order, entry_id=payload.clarification_id
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.add(AuditLog(
        user_id=token.sub,
        action=AuditAction.UPDATE,
        resource="orders",
        resource_id=str(order.id),
        description=f"Clarification resolved on {order.reference}",
        extra={"clarification_id": entry["id"]},
    ))
    await db.commit()
    summary = clarification_svc.summarize(order)
    return {
        "order_id": str(order.id),
        "entry": entry,
        "status": order.status.value,
        "summary": {
            "total": summary.total,
            "unanswered": summary.unanswered,
            "unresolved": summary.unresolved,
        },
    }


@router.get("/orders/{order_id}/clarification")
async def get_thread(
    order_id: UUID,
    db: DBSession,
    token: CurrentToken,
):
    """Read-only view of the order's clarification thread.

    Visible to anyone with read access to the order (the purchaser
    and the company both need it for the UI banner).
    """
    order = await _load_order_or_404(db, order_id, token)
    summary = clarification_svc.summarize(order)
    return {
        "order_id": str(order.id),
        "status": order.status.value,
        "entries": getattr(order, "clarification", None) or [],
        "summary": {
            "total": summary.total,
            "unanswered": summary.unanswered,
            "unresolved": summary.unresolved,
            "is_blocking": summary.is_blocking,
        },
    }
