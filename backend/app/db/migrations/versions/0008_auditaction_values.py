"""auditaction_values

Revision ID: 0008_auditaction_values
Revises: 0007_impa_first
Create Date: 2026-09-07 12:00:00.000000

Adds the lowercase *value* counterparts for the 16 original
``AuditAction`` enum members to the PostgreSQL ``auditaction``
enum. The originals were created in migration 0001 using the
Python enum *names* (uppercase: ``CREATE, READ, UPDATE, ...``).
The marketplace redesign (migration 0006) added 9 more values
as lowercase *values* (``clarification_requested, ...``).

With ``values_callable=lambda enum_cls: [e.value for e in enum_cls]``
now set on the ``Enum(AuditAction)`` column type in
``app/models/audit.py``, every audit write binds the lowercase
value. But the lowercase values for the 16 originals don't exist
in the PG enum yet — the next ``CREATE`` or ``RFQ_SENT`` write
would raise ``invalid input value for enum auditaction:
'create'``.

This migration adds those 16 lowercase values so the model fix
can be applied without breaking the existing writes.

Alembic runs each migration in a single transaction, but
Postgres requires ``ALTER TYPE ... ADD VALUE`` to be committed
before the next ``ADD VALUE`` in the same transaction. The
``autocommit=True`` on the ``ALTER TYPE`` statements below gets
around that — Alembic uses the engine's normal transactional
behaviour for everything else, but the ``ADD VALUE`` itself
runs outside the transaction.

Reverse: Postgres doesn't support removing a value from an
enum, so downgrade is a no-op. The unused labels stay in the
type after the application stops writing them.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0008_auditaction_values"
down_revision: Union[str, None] = "0007_impa_first"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The 16 AuditAction members that pre-date the marketplace
# redesign. The names are uppercase (the Python enum names);
# the values are lowercase (the actual action string we want
# to bind). The PG enum only has the names today; this
# migration adds the values.
_LOWERCASE_AUDIT_ACTIONS = (
    "create",
    "read",
    "update",
    "delete",
    "login",
    "logout",
    "login_failed",
    "export",
    "import",
    "approve",
    "reject",
    "sync",
    "rfq_sent",
    "quote_submitted",
    "order_placed",
    "other",
)


def upgrade() -> None:
    # ``autocommit=True`` so each ADD VALUE is its own
    # transaction. Postgres won't let you ADD a new value
    # inside the same transaction as a previous ADD VALUE
    # unless the previous one has been committed. With
    # autocommit each statement is its own commit and the
    # next one sees the previous one.
    with op.get_context().autocommit_block():
        for label in _LOWERCASE_AUDIT_ACTIONS:
            op.execute(f"ALTER TYPE auditaction ADD VALUE IF NOT EXISTS '{label}'")


def downgrade() -> None:
    # Postgres doesn't support removing a value from an enum
    # in place. The unused labels stay in the type after the
    # application stops writing them. See 0005 and 0006
    # downgrade comments for the same caveat.
    pass
