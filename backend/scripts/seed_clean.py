"""
Clean reseed — backup only (mock-up-backup).
Truncates reference seed tables and inserts minimal correct rows.
Leaves users / RBAC intact (already fixed).
No lazy-load patches — pure data.
Attribution: Co-Authored-By: Claude Code <noreply@anthropic.com>
🤖 Generated with [Claude Code](https://claude.com/claude-code)
"""
from __future__ import annotations
import asyncio, os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://avs:avs-dev-password@localhost:5432/avs")

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DB = os.getenv("DATABASE_URL", "postgresql+asyncpg://avs:avs-dev-password@localhost:5432/avs")

MINIMAL = {
    "countries": [
        ("SG","SGP","Singapore","Asia",2),
        ("DE","DEU","Germany","Europe",2),
        ("GR","GRC","Greece","Europe",2),
    ],
    "ports": [
        ("SGP","Singapore","SG"),
        ("HAM","Hamburg","DE"),
        ("PIR","Piraeus","GR"),
    ],
    "suppliers": [
        ("APC Marine","apcmarine@apcmarine.sg","SG"),
        ("Maritime Provisions","mp@maritime.sg","DE"),
        ("Hellas Supply","hellas@supply.gr","GR"),
    ],
    "vessels": [
        ("MV Test I","IMO9876543","SG"),
        ("MV Test II","IMO9876544","DE"),
    ],
    "products": [
        ("Fuel Oil","FUE-001"),
        ("Lubricant","LUB-002"),
        ("Provision","PRO-003"),
    ],
}

async def main():
    eng = create_async_engine(DB, future=True, echo=False)
    async with eng.begin() as conn:
        # Truncate only reference tables (safe, no FKs to users/rbac)
        await conn.execute(text("TRUNCATE TABLE supplier_ports, products, vessels, suppliers, ports, countries RESTART IDENTITY CASCADE;"))
        # Countries
        for code_iso2, code_iso3, name, region, hs in MINIMAL["countries"]:
            await conn.execute(text("""
                INSERT INTO countries (id, code_iso2, code_iso3, name, region, hs_code_length, created_at, updated_at)
                VALUES (gen_random_uuid(), :a, :b, :c, :d, :e, now(), now())
                ON CONFLICT DO NOTHING
            """), {"a": code_iso2, "b": code_iso3, "c": name, "d": region, "e": hs})
        # Ports (need country_ids; use subselect by code_iso2)
        for unloc, name, country_code in MINIMAL["ports"]:
            await conn.execute(text("""
                INSERT INTO ports (id, unlocode, name, country_id, status, created_at, updated_at)
                SELECT gen_random_uuid(), :u, :n, id, 'ACTIVE', now(), now()
                FROM countries WHERE code_iso2 = :c
                ON CONFLICT DO NOTHING
            """), {"u": unloc, "n": name, "c": country_code})
        # Suppliers (simple insert; supplier_port links below)
        for sname, email, port_code in MINIMAL["suppliers"]:
            await conn.execute(text("""
                INSERT INTO suppliers (id, name, contact_email, status, created_at, updated_at)
                VALUES (gen_random_uuid(), :n, :e, 'ACTIVE', now(), now())
                ON CONFLICT DO NOTHING
            """), {"n": sname, "e": email})
        # Supplier port links (link supplier to port by matching email/port)
        # Skip detailed linkage for minimal clean state; seed script handles full links
        # Vessels
        for vname, imo, port_code in MINIMAL["vessels"]:
            await conn.execute(text("""
                INSERT INTO vessels (id, name, imo, status, created_at, updated_at)
                VALUES (gen_random_uuid(), :n, :i, 'ACTIVE', now(), now())
                ON CONFLICT DO NOTHING
            """), {"n": vname, "i": imo})
        # Products
        for pname, code in MINIMAL["products"]:
            await conn.execute(text("""
                INSERT INTO products (id, name, code, is_deleted, created_at, updated_at)
                VALUES (gen_random_uuid(), :n, :c, false, now(), now())
                ON CONFLICT DO NOTHING
            """), {"n": pname, "c": code})
    await eng.dispose()
    print("Clean reseed done — reference tables rebuilt. Users/RBAC untouched.")

if __name__ == "__main__":
    asyncio.run(main())
