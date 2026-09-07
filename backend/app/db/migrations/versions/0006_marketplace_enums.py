"""marketplace_enums

Revision ID: 0006_marketplace_enums
Revises: 0005_marketplace_redesign
Create Date: 2026-09-04 12:00:00.000000

Adds new enum values to ``notificationtype`` and ``auditaction``
that the marketplace redesign introduced but which were deferred
from 0005 because the original OrderStatus changes needed to land
first.

The new values are required for:

* ``NotificationType``:
  - ``clarification_requested`` — company asked the purchaser a question
  - ``clarification_answered`` — purchaser answered the question
  - ``slice_assigned``         — supplier has a slice to confirm
  - ``slice_confirmed``        — supplier accepted
  - ``slice_dropped``          — supplier was dropped (24h timeout or admin)

* ``AuditAction``:
  - ``clarification_requested`` / ``_answered`` / ``_resolved``
  - ``proposal_composed`` / ``_approved`` / ``_rejected``
  - ``slice_assigned`` / ``_confirmed`` / ``_dropped``

These match the values already declared in
``app/models/notification.py`` and ``app/models/audit.py``.

Postgres requires that new enum values be committed before they
can be used; the migration is a simple no-op once the values
exist (``ADD VALUE IF NOT EXISTS``).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0006_marketplace_enums"
down_revision: Union[str, None] = "0005_marketplace_redesign"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_NOTIFICATION_TYPES = (
    "clarification_requested",
    "clarification_answered",
    "slice_assigned",
    "slice_confirmed",
    "slice_dropped",
)

_NEW_AUDIT_ACTIONS = (
    "clarification_requested",
    "clarification_answered",
    "clarification_resolved",
    "proposal_composed",
    "proposal_approved",
    "proposal_rejected",
    "slice_assigned",
    "slice_confirmed",
    "slice_dropped",
)


def upgrade() -> None:
    for label in _NEW_NOTIFICATION_TYPES:
        op.execute(f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{label}'")
    for label in _NEW_AUDIT_ACTIONS:
        op.execute(f"ALTER TYPE auditaction ADD VALUE IF NOT EXISTS '{label}'")


def downgrade() -> None:
    # Postgres doesn't support removing a value from an enum in
    # place. The unused labels stay in the type after the
    # application stops writing them. See 0005's downgrade comment
    # for the same caveat.
    pass
