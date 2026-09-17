"""Add missing demo users from readme.md that aren't in the DB."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash
from app.db.session import async_session_factory
from app.models import Role, User, UserRole, UserStatus

MISSING_USERS = [
    # (email, username, full_name, password, role_name)
    ("captain@avsglobal.com", "captain", "Captain Mehmet Yılmaz", "demo123", "vessel_captain"),
    ("steward@avsglobal.com", "steward", "Carlos Reyes", "demo123", "chief_steward"),
    ("fleetadmin@avsglobal.com", "fleetadmin", "Fleet Admin (Demo)", "demo123", "fleet_admin"),
]


async def main():
    async with async_session_factory() as db:
        # Build role map
        role_map = {
            r.name: r for r in (await db.execute(select(Role))).scalars().all()
        }

        # Check existing users
        existing = {
            u.email: u for u in (await db.execute(select(User))).scalars().all()
        }

        for email, username, full_name, password, role_name in MISSING_USERS:
            if email in existing:
                print(f"  · {email} already exists, skipping")
                continue

            role = role_map.get(role_name)
            if not role:
                print(f"  ! role {role_name} not found, skipping {email}")
                continue

            user = User(
                email=email,
                username=username,
                full_name=full_name,
                hashed_password=get_password_hash(password),
                status=UserStatus.ACTIVE,
                email_verified=True,
            )
            db.add(user)
            await db.flush()
            db.add(UserRole(user_id=user.id, role_id=role.id))
            print(f"  + {email} ({role_name})")

        await db.commit()


if __name__ == "__main__":
    asyncio.run(main())
