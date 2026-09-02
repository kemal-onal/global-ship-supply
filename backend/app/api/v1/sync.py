"""Sync routes — receive offline batches, list queues, resolve conflicts."""
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.deps.auth import CurrentToken, DBSession, ReadDBSession
from app.models.sync import SyncConflict, SyncQueue
from app.models.user import User
from app.services.sync import replay_actions

router = APIRouter()


class OfflineActionIn(BaseModel):
    client_action_id: str
    resource: str
    action: str  # create | update | delete
    entity_id: str | None = None
    payload: dict[str, Any]
    client_timestamp: str  # ISO 8601


class SyncBatchIn(BaseModel):
    device_id: str
    actions: list[OfflineActionIn]


@router.post("/replay")
async def replay(
    payload: SyncBatchIn,
    db: DBSession,
    token: CurrentToken,
):
    user = (await db.execute(select(User).where(User.id == token.sub))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    queue = await replay_actions(
        db, user=user, device_id=payload.device_id,
        actions=[a.model_dump() for a in payload.actions],
    )
    await db.commit()
    return {
        "id": str(queue.id),
        "status": queue.status.value,
        "applied_actions": queue.applied_actions,
        "failed_actions": queue.failed_actions,
        "conflicts": queue.conflicts,
        "total": queue.total_actions,
    }


@router.get("/queues")
@router.get("/queue")
async def list_queues(
    db: ReadDBSession,
    token: CurrentToken,
    device_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    stmt = select(SyncQueue).order_by(SyncQueue.created_at.desc())
    if device_id:
        stmt = stmt.where(SyncQueue.device_id == device_id)
    stmt = stmt.limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(q.id),
            "device_id": q.device_id,
            "resource": "sync_queue",
            "action": "replay",
            "status": q.status.value,
            "queued_at": q.created_at.isoformat() if q.created_at else None,
            "started_at": q.started_at.isoformat() if q.started_at else None,
            "finished_at": q.finished_at.isoformat() if q.finished_at else None,
            "total_actions": q.total_actions,
            "applied_actions": q.applied_actions,
            "failed_actions": q.failed_actions,
            "conflicts": q.conflicts,
            "error": None,
        }
        for q in rows
    ]


@router.get("/conflicts")
async def list_conflicts(
    db: ReadDBSession,
    token: CurrentToken,
    queue_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    stmt = select(SyncConflict).order_by(SyncConflict.created_at.desc())
    if queue_id:
        stmt = stmt.where(SyncConflict.sync_queue_id == queue_id)
    stmt = stmt.limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(c.id),
            "queue_id": str(c.sync_queue_id),
            "resource": c.resource,
            "entity_id": c.entity_id,
            "resolution": c.resolution.value,
            "client_version": c.client_version,
            "server_version": c.server_version,
            "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
        }
        for c in rows
    ]
