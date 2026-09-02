"""
Notifications API — list, unread count, mark-read.

All routes are scoped to the current user (read from the JWT). A user
can never see or mutate another user's notifications.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select, update

from app.deps.auth import CurrentToken, DBSession, ReadDBSession
from app.models.notification import Notification

router = APIRouter()


# --- helpers --------------------------------------------------------------

def _serialize(n: Notification) -> dict[str, Any]:
    return {
        "id": str(n.id),
        "type": n.type.value,
        "title": n.title,
        "body": n.body,
        "data": n.data,
        "read_at": n.read_at.isoformat() if n.read_at else None,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


def _coerce_user_id(token_sub: str) -> UUID:
    try:
        return UUID(token_sub)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=401,
            detail="Invalid token subject",
        ) from exc


# --- routes ---------------------------------------------------------------

@router.get("")
async def list_notifications(
    db: ReadDBSession,
    token: CurrentToken,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    unread_only: bool = Query(False),
):
    """List the current user's notifications, newest first."""
    user_id = _coerce_user_id(token.sub)
    stmt = (
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    rows = (await db.execute(stmt)).scalars().all()
    return [_serialize(n) for n in rows]


@router.get("/unread-count")
async def unread_count(
    db: ReadDBSession,
    token: CurrentToken,
) -> dict[str, int]:
    """How many of the current user's notifications are unread.

    Used by the frontend's 30s polling loop to drive the bell badge.
    Returns just the count to keep the response tiny.
    """
    user_id = _coerce_user_id(token.sub)
    n = (
        await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id)
            .where(Notification.read_at.is_(None))
        )
    ).scalar_one()
    return {"count": int(n)}


@router.patch("/{notification_id}/read")
async def mark_read(
    notification_id: str,
    db: DBSession,
    token: CurrentToken,
) -> dict[str, Any]:
    """Mark a single notification as read.

    Idempotent: if the notification is already read we still return 200
    and the same payload (no error). 404 if the id doesn't exist *or*
    if it belongs to a different user — we don't leak existence.
    """
    user_id = _coerce_user_id(token.sub)
    try:
        nid = UUID(notification_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Notification not found") from exc

    n = (
        await db.execute(
            select(Notification).where(Notification.id == nid)
        )
    ).scalar_one_or_none()
    if n is None or n.user_id != user_id:
        raise HTTPException(status_code=404, detail="Notification not found")

    if n.read_at is None:
        n.read_at = datetime.now(timezone.utc)
        await db.commit()

    return _serialize(n)


@router.patch("/read-all")
async def mark_all_read(
    db: DBSession,
    token: CurrentToken,
) -> dict[str, int]:
    """Mark every unread notification for the current user as read.

    Returns the number of rows that were updated (0 if everything was
    already read).
    """
    user_id = _coerce_user_id(token.sub)
    result = await db.execute(
        update(Notification)
        .where(Notification.user_id == user_id)
        .where(Notification.read_at.is_(None))
        .values(read_at=datetime.now(timezone.utc))
    )
    await db.commit()
    return {"updated": result.rowcount or 0}
