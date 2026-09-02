"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-01 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create all tables. SQLAlchemy generates DDL from Base.metadata."""
    bind = op.get_bind()
    from app.db.base import Base
    from app import models  # noqa: F401
    Base.metadata.create_all(bind)


def downgrade() -> None:
    from app.db.base import Base
    from app import models  # noqa: F401
    bind = op.get_bind()
    Base.metadata.drop_all(bind)
