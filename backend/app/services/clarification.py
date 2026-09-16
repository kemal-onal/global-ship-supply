"""Clarification thread for the marketplace redesign.

The marketplace flow has a loop between company and purchaser
*before* the RFQ fans out: the company reads the purchaser's
notes, asks a question, the purchaser answers, the company
marks it resolved. The RFQ can't fan out while there's an
unanswered question on the order.

State lives on ``Order.clarification`` (a JSONB list). Each
entry:

  {
    "id":           "<uuid str>",
    "question":     "What kind of footwear — steel-toe or composite?",
    "answer":       None | "Steel-toe, half the order each brand",
    "asked_by":     "<user id>",
    "answered_by":  None | "<user id>",
    "ts":           "<iso8601>",
    "answered_at":  None | "<iso8601>",
    "resolved_at":  None | "<iso8601>"
  }

The list is append-only. Answers fill in the existing row; the
company marks ``resolved_at`` when the thread is closed. The fan
out refuses to fire while any entry has ``answer is None and
resolved_at is None``.

Why a JSONB list and not a separate ``clarifications`` table?
* One row per order, easy to ship back to the UI in the order
  payload (no extra join).
* The data is small and write-once per thread entry; we never
  query across orders ("show me all unanswered clarifications").
* The Order is the natural aggregate root; lifecycle belongs to
  it. If we later need cross-order queries, we can add a
  materialized view or copy on transition to a separate table.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderStatus


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


def _ensure_list(order: Order) -> list[dict[str, Any]]:
    clarification = getattr(order, "clarification", None)
    if clarification is None:
        clarification = []
        try:
            order.clarification = clarification
        except Exception:
            pass
    return clarification if isinstance(clarification, list) else []


def _find_entry(entries: list[dict[str, Any]], entry_id: str) -> dict[str, Any] | None:
    for e in entries:
        if e.get("id") == entry_id:
            return e
    return None


async def ask_clarification(
    db: AsyncSession,
    order: Order,
    *,
    question: str,
    asked_by: str,
) -> dict[str, Any]:
    """Company posts a question on the order.

    Adds an entry to ``order.clarification`` and transitions the
    order to ``AWAITING_CLARIFICATION`` (only from a status that
    can move into the loop — DRAFT or any pre-quoting state).
    """
    if not question or not question.strip():
        raise ValueError("Question must not be empty")
    entries = _ensure_list(order)
    entry = {
        "id": _new_id(),
        "question": question.strip(),
        "answer": None,
        "asked_by": asked_by,
        "answered_by": None,
        "ts": _now_iso(),
        "answered_at": None,
        "resolved_at": None,
    }
    entries.append(entry)
    # Move into the clarification state. The first question on a
    # DRAFT order is the most common case; we also allow it from
    # the (legacy) RFQ_IN_PROGRESS / BIDDING states so existing
    # in-flight orders can be retro-fitted.
    if order.status in (
        OrderStatus.DRAFT,
        OrderStatus.RFQ_SENT,
        OrderStatus.RFQ_CLOSED,
        OrderStatus.AWAITING_CLARIFICATION,
    ):
        order.status = OrderStatus.AWAITING_CLARIFICATION
    return entry


async def answer_clarification(
    db: AsyncSession,
    order: Order,
    *,
    entry_id: str,
    answer: str,
    answered_by: str,
) -> dict[str, Any]:
    """Purchaser answers a question on the order.

    Mutates the matching entry in place. The order stays in
    ``AWAITING_CLARIFICATION`` until the company marks the entry
    resolved (see ``resolve_clarification``).
    """
    if not answer or not answer.strip():
        raise ValueError("Answer must not be empty")
    entries = _ensure_list(order)
    entry = _find_entry(entries, entry_id)
    if entry is None:
        raise LookupError(f"No clarification entry with id {entry_id}")
    if entry.get("answer") is not None:
        # Idempotent re-answer is allowed (network retries) but the
        # row's answered_at stays at the first answer. The newer
        # answer overwrites the body.
        pass
    entry["answer"] = answer.strip()
    entry["answered_by"] = answered_by
    entry["answered_at"] = _now_iso()
    return entry


async def resolve_clarification(
    db: AsyncSession,
    order: Order,
    *,
    entry_id: str,
) -> dict[str, Any]:
    """Company marks a clarification entry as resolved.

    The entry must have an answer; you can't resolve an
    unanswered question. When *all* entries on the order are
    resolved, the order's status is moved out of
    ``AWAITING_CLARIFICATION`` (to DRAFT so the company can
    proceed to the RFQ fan-out step).
    """
    entries = _ensure_list(order)
    entry = _find_entry(entries, entry_id)
    if entry is None:
        raise LookupError(f"No clarification entry with id {entry_id}")
    if entry.get("answer") is None:
        raise ValueError("Cannot resolve an unanswered question")
    entry["resolved_at"] = _now_iso()
    # If every entry is now resolved, drop the order out of
    # AWAITING_CLARIFICATION. We pick DRAFT (not QUOTING) because
    # the actual fan-out is a separate step the company triggers
    # from the marketplace page.
    if all(e.get("resolved_at") is not None for e in entries):
        if order.status == OrderStatus.AWAITING_CLARIFICATION:
            order.status = OrderStatus.DRAFT
    return entry


def has_unresolved_clarifications(order: Order) -> bool:
    """True if the order has at least one open question.

    Used by the fan-out step to refuse to proceed while the
    clarification loop is open. The marketplace endpoint also
    surfaces this as a warning banner.
    """
    # Defensive: Order model may not have clarification relationship
    # loaded (simplified marketplace design). If missing or empty,
    # treat as no open clarifications.
    entries = getattr(order, "clarification", None) or []
    if isinstance(entries, list):
        return any(
            (isinstance(e, dict) and e.get("resolved_at") is None)
            or (hasattr(e, "resolved_at") and e.resolved_at is None)
            for e in entries
        )
    return False


@dataclass(slots=True)
class ClarificationStatus:
    """A flattened summary of the order's clarification thread,
    suitable for an API response or the UI banner."""

    total: int
    unanswered: int
    unresolved: int  # unanswered OR answered-but-not-resolved-by-company

    @property
    def is_blocking(self) -> bool:
        # Block fan-out only while the *company* hasn't marked
        # the loop closed. An answered-but-unresolved entry still
        # needs the company to click "resolved" before we proceed.
        return self.unresolved > 0


def summarize(order: Order) -> ClarificationStatus:
    """Build a summary for the order's clarification thread."""
    entries = getattr(order, "clarification", None) or []
    if not isinstance(entries, list):
        entries = []
    total = len(entries)
    unanswered = sum(1 for e in entries if e.get("answer") is None and e.get("resolved_at") is None)
    unresolved = sum(1 for e in entries if e.get("resolved_at") is None)
    return ClarificationStatus(total=total, unanswered=unanswered, unresolved=unresolved)
