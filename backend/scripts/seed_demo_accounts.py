"""
seed_demo_accounts.py — add only the IMPA-first demo accounts.

Idempotent. Inserts (or skips, if already present):

  Users:
    fleetadmin@avsglobal.com  / demo123  — fleet_admin
    supplier1@avsglobal.com   / demo123  — supplier (Rotterdam)
    supplier2@avsglobal.com   / demo123  — supplier (Singapore)
    supplier3@avsglobal.com   / demo123  — supplier (Dubai)

  Suppliers (linked to the three supplier users by contact_email
  so the supplier portal automatically wires them up):
    Rotterdam Demo Supplies B.V.  (NLRTM)
    Singapore Demo Supplies Pte Ltd (SGSIN)
    Dubai Demo Supplies LLC        (AEDXB)

Run with: `python -m scripts.seed_demo_accounts` from backend/.
"""
from __future__ import annotations

import asyncio
import random
import sys
from pathlib import Path

# Make sure `app.*` imports resolve when run as a module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash
from app.db.session import async_session_factory
from app.models import (
    Port,
    Product,
    ProductSupplier,
    Role,
    Supplier,
    SupplierPort,
    SupplierStatus,
    User,
    UserRole,
    UserStatus,
)


NEW_USERS = [
    # (email, username, full_name, password, role_name)
    ("fleetadmin@avsglobal.com", "fleetadmin", "Fleet Admin (Demo)", "demo123", "fleet_admin"),
    ("supplier1@avsglobal.com", "supplier1", "Rotterdam Demo Supplies", "demo123", "supplier"),
    ("supplier2@avsglobal.com", "supplier2", "Singapore Demo Supplies", "demo123", "supplier"),
    ("supplier3@avsglobal.com", "supplier3", "Dubai Demo Supplies", "demo123", "supplier"),
]

# Each demo supplier's primary port by unlocode. The supplier
# portal invitation filter matches User.email == Supplier.contact_email,
# so as long as both exist with matching emails the supplier
# account is auto-wired.
NEW_SUPPLIERS = [
    {
        "company_name": "Rotterdam Demo Supplies",
        "legal_name": "Rotterdam Demo Supplies B.V.",
        "contact_email": "supplier1@avsglobal.com",
        "country_code": "NL",
        "city": "Rotterdam",
        "primary_unlocode": "NLRTM",
        "categories": ["provisions", "deck_stores", "engine_stores", "safety", "consumables"],
        "currency": "EUR",
    },
    {
        "company_name": "Singapore Demo Supplies",
        "legal_name": "Singapore Demo Supplies Pte Ltd",
        "contact_email": "supplier2@avsglobal.com",
        "country_code": "SG",
        "city": "Singapore",
        "primary_unlocode": "SGSIN",
        "categories": ["provisions", "deck_stores", "engine_stores", "safety", "consumables"],
        "currency": "USD",
    },
    {
        "company_name": "Dubai Demo Supplies",
        "legal_name": "Dubai Demo Supplies LLC",
        "contact_email": "supplier3@avsglobal.com",
        "country_code": "AE",
        "city": "Dubai",
        "primary_unlocode": "AEDXB",
        "categories": ["provisions", "deck_stores", "engine_stores", "safety", "consumables"],
        "currency": "USD",
    },
]


async def add_users(db: AsyncSession) -> None:
    """Insert demo users if they don't exist. Idempotent on email."""
    role_map = {
        r.name: r
        for r in (await db.execute(select(Role))).scalars().all()
    }
    for email, username, full_name, password, role_name in NEW_USERS:
        # Skip if email already taken.
        existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if existing:
            print(f"  · user {email} already exists, skipping")
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
        role = role_map.get(role_name)
        if role is None:
            print(f"  ! role {role_name!r} not found, user {email} created without role")
            continue
        db.add(UserRole(user_id=user.id, role_id=role.id))
        print(f"  + user {email} ({role_name})")
    await db.commit()


async def add_suppliers(db: AsyncSession) -> None:
    """Insert demo suppliers + anchor them to a primary port. Idempotent."""
    port_by_unlocode = {
        p.unlocode: p
        for p in (await db.execute(select(Port))).scalars().all()
    }
    all_ports = list(port_by_unlocode.values())

    for s in NEW_SUPPLIERS:
        # Idempotent on contact_email (the unique index).
        existing = (await db.execute(
            select(Supplier).where(Supplier.contact_email == s["contact_email"])
        )).scalar_one_or_none()
        if existing:
            sup = existing
            print(f"  · supplier {s['contact_email']} already exists, skipping insert")
        else:
            stmt = insert(Supplier).values(
                company_name=s["company_name"],
                legal_name=s["legal_name"],
                contact_email=s["contact_email"],
                country_code=s["country_code"],
                city=s["city"],
                categories=s["categories"],
                currency=s["currency"],
                status=SupplierStatus.ACTIVE,
                rating_overall=round(random.uniform(3.5, 5.0), 2),
                rating_reliability=round(random.uniform(3.5, 5.0), 2),
                rating_quality=round(random.uniform(3.5, 5.0), 2),
                rating_communication=round(random.uniform(3.0, 5.0), 2),
                rating_count=random.randint(5, 200),
                on_time_pct=round(random.uniform(85, 99), 1),
                avg_response_hours=round(random.uniform(2, 24), 1),
                supports_api=random.random() > 0.5,
            ).on_conflict_do_nothing(index_elements=["contact_email"])
            await db.execute(stmt)
            sup = (await db.execute(
                select(Supplier).where(Supplier.contact_email == s["contact_email"])
            )).scalar_one()
            print(f"  + supplier {s['contact_email']} ({s['company_name']})")

        # Anchor to the primary port + 2 random others so they
        # see RFQs from neighboring ports too.
        primary = port_by_unlocode.get(s["primary_unlocode"])
        chosen = []
        if primary is not None:
            chosen.append(primary)
        others = [p for p in all_ports if p.id != (primary.id if primary else None)]
        for p in random.sample(others, k=min(2, len(others))):
            chosen.append(p)
        for p in chosen:
            existing_link = (await db.execute(
                select(SupplierPort).where(
                    SupplierPort.supplier_id == sup.id,
                    SupplierPort.port_id == p.id,
                )
            )).scalar_one_or_none()
            if existing_link:
                continue
            db.add(SupplierPort(supplier_id=sup.id, port_id=p.id, is_primary=True))
        print(f"    · anchored to {', '.join(p.unlocode for p in chosen)}")

        # Give each demo supplier a small product catalog (15 random
        # products) so they can quote. The original seed gave the
        # other 10 suppliers 20 each.
        existing_offers = (await db.execute(
            select(ProductSupplier).where(ProductSupplier.supplier_id == sup.id)
        )).scalars().all()
        if existing_offers:
            print(f"    · {len(existing_offers)} existing product offers, skipping catalog")
        else:
            product_ids = [
                r[0] for r in (await db.execute(
                    select(Product.id).order_by(Product.sku).limit(200)
                )).all()
            ]
            random.shuffle(product_ids)
            for pid in product_ids[:15]:
                db.add(ProductSupplier(
                    supplier_id=sup.id, product_id=pid,
                    unit_price=round(random.uniform(1.0, 500.0), 4),
                    currency=sup.currency,
                    lead_time_days=random.choice([3, 5, 7, 14]),
                    in_stock=True,
                ))
            print(f"    · added 15 product offers")

    await db.commit()


async def main():
    print("============================================================")
    print("AVS Global — demo accounts seed (idempotent)")
    print("============================================================")
    print("-> Seeding users")
    async with async_session_factory() as db:
        await add_users(db)
    print("-> Seeding suppliers")
    async with async_session_factory() as db:
        await add_suppliers(db)
    print()
    print("✅ Demo accounts ready")
    print()
    print("Demo logins:")
    for email, username, full_name, password, role_name in NEW_USERS:
        print(f"  · {email:30s}  /  {password}     ({role_name})")


if __name__ == "__main__":
    asyncio.run(main())
