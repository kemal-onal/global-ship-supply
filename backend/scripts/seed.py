"""
Seed script — populates the database with a realistic sample dataset.

Run with: `python -m scripts.seed` from the backend/ directory.

What gets seeded:
  * Roles & permissions (matches SYSTEM_ROLES / SYSTEM_PERMISSIONS in models)
  * 5 demo users (captain, purchasing, steward, admin, supplier)
  * 8 vessel types and 12 vessels
  * 30+ countries and 30+ ports
  * 12 product categories, 5000 IMPA-coded products, 1000 ISSA-coded products
  * Sample regulations / customs rules
  * 10 suppliers spread across major ports
  * 5 crew nationalities with calorie profiles
  * Demo menu templates per nationality/meal
"""
from __future__ import annotations

import asyncio
import random
import string
from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash
from app.db.session import async_session_factory, engine, init_db
from app.models import (
    CrewNationality,
    CrewNationalityEnum,
    CustomsRule,
    ImpaCode,
    IssaCode,
    MealType,
    MenuItem,
    MenuTemplate,
    Permission,
    Port,
    Country,
    PortRegulation,
    PortStatus,
    PortTypeEnum,
    Product,
    ProductCategory,
    ProductStatus,
    ProductSupplier,
    RegionEnum,
    RegulationCategory,
    RegulationSeverity,
    Role,
    RolePermission,
    Supplier,
    SupplierPort,
    SupplierStatus,
    UnitOfMeasure,
    User,
    UserRole,
    UserStatus,
    Vessel,
    VesselTypeEnum,
)
from app.models.user import SYSTEM_PERMISSIONS, SYSTEM_ROLES
from app.models.vessel import DEFAULT_VESSEL_TYPES

# ---- Seed data ---------------------------------------------------------------

COUNTRIES = [
    ("TR", "TUR", "Türkiye", RegionEnum.EUROPE, "TRY", ["alcohol_restricted"], True, False),
    ("US", "USA", "United States", RegionEnum.NORTH_AMERICA, "USD", [], False, False),
    ("NL", "NLD", "Netherlands", RegionEnum.EUROPE, "EUR", [], False, False),
    ("DE", "DEU", "Germany", RegionEnum.EUROPE, "EUR", [], False, False),
    ("SG", "SGP", "Singapore", RegionEnum.ASIA, "SGD", ["pork"], False, False),
    ("CN", "CHN", "China", RegionEnum.ASIA, "CNY", [], False, False),
    ("AE", "ARE", "United Arab Emirates", RegionEnum.ASIA, "AED", ["pork", "alcohol"], False, True),
    ("SA", "SAU", "Saudi Arabia", RegionEnum.ASIA, "SAR", ["pork", "alcohol"], False, True),
    ("GB", "GBR", "United Kingdom", RegionEnum.EUROPE, "GBP", [], False, False),
    ("FR", "FRA", "France", RegionEnum.EUROPE, "EUR", [], False, False),
    ("IN", "IND", "India", RegionEnum.ASIA, "INR", [], False, False),
    ("JP", "JPN", "Japan", RegionEnum.ASIA, "JPY", [], False, False),
    ("BR", "BRA", "Brazil", RegionEnum.SOUTH_AMERICA, "BRL", [], False, False),
    ("ZA", "ZAF", "South Africa", RegionEnum.AFRICA, "ZAR", [], False, False),
    ("AU", "AUS", "Australia", RegionEnum.OCEANIA, "AUD", [], False, False),
    ("EG", "EGY", "Egypt", RegionEnum.AFRICA, "EGP", ["alcohol"], False, True),
    ("ES", "ESP", "Spain", RegionEnum.EUROPE, "EUR", [], False, False),
    ("IT", "ITA", "Italy", RegionEnum.EUROPE, "EUR", [], False, False),
    ("KR", "KOR", "South Korea", RegionEnum.ASIA, "KRW", [], False, False),
    ("RU", "RUS", "Russia", RegionEnum.EUROPE, "RUB", ["alcohol"], False, False),
]

PORTS = [
    ("TRGEM", "Gemlik", "TR", 40.43, 29.15, PortTypeEnum.SEAPORT, "Europe/Istanbul"),
    ("TRIZM", "Izmir", "TR", 38.42, 27.14, PortTypeEnum.SEAPORT, "Europe/Istanbul"),
    ("NLRTM", "Rotterdam", "NL", 51.95, 4.14, PortTypeEnum.SEAPORT, "Europe/Amsterdam"),
    ("DEHAM", "Hamburg", "DE", 53.55, 9.99, PortTypeEnum.SEAPORT, "Europe/Berlin"),
    ("SGSIN", "Singapore", "SG", 1.29, 103.85, PortTypeEnum.SEAPORT, "Asia/Singapore"),
    ("CNSHA", "Shanghai", "CN", 31.22, 121.48, PortTypeEnum.SEAPORT, "Asia/Shanghai"),
    ("AEDXB", "Dubai", "AE", 25.27, 55.30, PortTypeEnum.SEAPORT, "Asia/Dubai"),
    ("SADMM", "Dammam", "SA", 26.42, 50.10, PortTypeEnum.SEAPORT, "Asia/Riyadh"),
    ("GBFXT", "Felixstowe", "GB", 51.96, 1.35, PortTypeEnum.SEAPORT, "Europe/London"),
    ("FRLEH", "Le Havre", "FR", 49.49, 0.10, PortTypeEnum.SEAPORT, "Europe/Paris"),
    ("INMUN", "Mundra", "IN", 22.74, 69.72, PortTypeEnum.SEAPORT, "Asia/Kolkata"),
    ("JPYOK", "Yokohama", "JP", 35.44, 139.64, PortTypeEnum.SEAPORT, "Asia/Tokyo"),
    ("BRSSZ", "Santos", "BR", -23.96, -46.33, PortTypeEnum.SEAPORT, "America/Sao_Paulo"),
    ("ZADUR", "Durban", "ZA", -29.87, 31.02, PortTypeEnum.SEAPORT, "Africa/Johannesburg"),
    ("AUSYD", "Sydney", "AU", -33.87, 151.21, PortTypeEnum.SEAPORT, "Australia/Sydney"),
    ("EGSUZ", "Suez", "EG", 29.97, 32.55, PortTypeEnum.SEAPORT, "Africa/Cairo"),
    ("ESVLC", "Valencia", "ES", 39.45, -0.32, PortTypeEnum.SEAPORT, "Europe/Madrid"),
    ("ITGOA", "Genoa", "IT", 44.41, 8.93, PortTypeEnum.SEAPORT, "Europe/Rome"),
    ("KRPUS", "Busan", "KR", 35.10, 129.04, PortTypeEnum.SEAPORT, "Asia/Seoul"),
    ("RUVVO", "Vladivostok", "RU", 43.13, 131.92, PortTypeEnum.SEAPORT, "Asia/Vladivostok"),
    ("TRMER", "Mersin", "TR", 36.80, 34.64, PortTypeEnum.SEAPORT, "Europe/Istanbul"),
    ("NLAMS", "Amsterdam", "NL", 52.42, 4.85, PortTypeEnum.SEAPORT, "Europe/Amsterdam"),
    ("USLAX", "Los Angeles", "US", 33.74, -118.27, PortTypeEnum.SEAPORT, "America/Los_Angeles"),
    ("USNYC", "New York", "US", 40.67, -74.05, PortTypeEnum.SEAPORT, "America/New_York"),
    ("USSEA", "Seattle", "US", 47.61, -122.34, PortTypeEnum.SEAPORT, "America/Los_Angeles"),
    ("GBLON", "London", "GB", 51.51, -0.08, PortTypeEnum.RIVER_PORT, "Europe/London"),
    ("FRMAR", "Marseille", "FR", 43.30, 5.37, PortTypeEnum.SEAPORT, "Europe/Paris"),
    ("DEBRE", "Bremerhaven", "DE", 53.55, 8.59, PortTypeEnum.SEAPORT, "Europe/Berlin"),
    ("CNNGB", "Ningbo", "CN", 29.87, 121.55, PortTypeEnum.SEAPORT, "Asia/Shanghai"),
    ("CNSZN", "Shenzhen", "CN", 22.54, 114.06, PortTypeEnum.SEAPORT, "Asia/Shanghai"),
    ("INNSA", "Mumbai", "IN", 19.08, 72.88, PortTypeEnum.SEAPORT, "Asia/Kolkata"),
    ("JPTYO", "Tokyo", "JP", 35.65, 139.84, PortTypeEnum.SEAPORT, "Asia/Tokyo"),
    ("AUFRE", "Fremantle", "AU", -32.05, 115.74, PortTypeEnum.SEAPORT, "Australia/Perth"),
    ("BRRIO", "Rio de Janeiro", "BR", -22.90, -43.17, PortTypeEnum.SEAPORT, "America/Sao_Paulo"),
    ("TRIST", "Istanbul", "TR", 41.01, 28.97, PortTypeEnum.SEAPORT, "Europe/Istanbul"),
    ("EGPSD", "Port Said", "EG", 31.26, 32.30, PortTypeEnum.SEAPORT, "Africa/Cairo"),
]

VESSELS = [
    ("9464567", "MV Marmara", VesselTypeEnum.CONTAINER, "TR", "Maersk Line", 350, 48, 15.5, 150000, 22),
    ("9789123", "MV Aegean", VesselTypeEnum.BULK_CARRIER, "GR", "Star Bulk", 290, 45, 18.0, 180000, 20),
    ("9598231", "MV Bosphorus", VesselTypeEnum.TANKER, "PA", "Turkish Petroleum", 330, 60, 20.5, 300000, 24),
    ("9843210", "MV Antalya", VesselTypeEnum.CONTAINER, "TR", "Arkas Line", 300, 42, 14.0, 100000, 21),
    ("9711234", "MV Pacific Voyager", VesselTypeEnum.CONTAINER, "LR", "Pacific Shipping", 360, 51, 16.0, 165000, 23),
    ("9634567", "MV North Star", VesselTypeEnum.BULK_CARRIER, "MH", "Ocean Bulk Co", 280, 43, 17.5, 170000, 19),
    ("9754321", "MV Istanbul", VesselTypeEnum.GENERAL_CARGO, "TR", "Turkish Cargo", 150, 23, 9.5, 15000, 18),
    ("9823456", "MV Rotterdam Express", VesselTypeEnum.CONTAINER, "NL", "Rotterdam Line", 340, 47, 15.0, 140000, 22),
    ("9987654", "MV Singapore Pearl", VesselTypeEnum.CONTAINER, "SG", "Pacific Orient", 320, 46, 14.5, 130000, 21),
    ("9645123", "MV Dubai Star", VesselTypeEnum.LNG_CARRIER, "AE", "Gulf Energy", 290, 47, 12.0, 95000, 26),
    ("9543210", "MV Hamburg", VesselTypeEnum.CONTAINER, "DE", "Hapag-Lloyd", 335, 48, 15.2, 145000, 22),
    ("9734567", "MV Yokohama", VesselTypeEnum.REEFER, "JP", "Japan Reefer Co", 180, 28, 9.0, 12000, 20),
]

# IMPA 6-digit code book (sample, structure matches the real IMPA catalog)
# Format: (group_code, code, name, category_code)
IMPA_SAMPLE = [
    ("33", "330101", "Paint - Anti-fouling", "paint_chemicals"),
    ("33", "330201", "Paint - Anti-corrosive", "paint_chemicals"),
    ("31", "310101", "Wire Rope 6mm", "deck_stores"),
    ("31", "310201", "Wire Rope 8mm", "deck_stores"),
    ("31", "310301", "Wire Rope 10mm", "deck_stores"),
    ("37", "370101", "Hose - Water 1/2\"", "engine_stores"),
    ("37", "370201", "Hose - Oil Resistant 3/4\"", "engine_stores"),
    ("37", "370301", "Hose - Steam 1\"", "engine_stores"),
    ("45", "450101", "Piston Ring Set - MAN B&W", "engine_stores"),
    ("45", "450201", "Piston Ring Set - Wartsila", "engine_stores"),
    ("47", "470101", "Air Filter Element", "consumables"),
    ("47", "470201", "Oil Filter Element", "consumables"),
    ("47", "470301", "Fuel Filter Element", "consumables"),
    ("47", "470401", "Water Separator", "consumables"),
    ("65", "650101", "Rope - Manila 24mm", "deck_stores"),
    ("65", "650201", "Rope - Polypropylene 20mm", "deck_stores"),
    ("79", "790101", "Brush - Steel Wire", "deck_stores"),
    ("79", "790201", "Brush - Paint 100mm", "paint_chemicals"),
    ("85", "850101", "Lifebuoy 30\"", "safety"),
    ("85", "850201", "Life Jacket Adult", "safety"),
    ("85", "850301", "Life Jacket Child", "safety"),
    ("85", "850401", "Immersion Suit", "safety"),
]

CATEGORIES = [
    ("deck_stores", "Deck Stores", "🪢", "pcs"),
    ("engine_stores", "Engine Stores", "⚙️", "pcs"),
    ("cabin_stores", "Cabin Stores", "🛏️", "pcs"),
    ("medical", "Medical / First Aid", "🩺", "pcs"),
    ("provisions", "Provisions (Food)", "🥫", "kg"),
    ("bond_store", "Bond Store (Duty-Free)", "🥃", "bottle"),
    ("safety", "Safety Equipment", "🦺", "pcs"),
    ("navigation", "Navigation", "🧭", "pcs"),
    ("electrical", "Electrical", "🔌", "pcs"),
    ("consumables", "Consumables", "🧴", "pcs"),
    ("lubricants", "Lubricants", "🛢️", "l"),
    ("paint_chemicals", "Paint & Chemicals", "🎨", "l"),
]

SUPPLIERS = [
    ("Maritime Provisions B.V.", "Rotterdam Provisions", "contact@marprov.nl", "NL", "Rotterdam", ["provisions", "bond_store"], "EUR"),
    ("Hellas Supply Co.", "Hellas Marine", "sales@hellas-supply.gr", "GR", "Piraeus", ["deck_stores", "engine_stores", "lubricants"], "EUR"),
    ("Asia Pacific Chandlers", "APC Marine", "info@apcmarine.sg", "SG", "Singapore", ["provisions", "deck_stores", "safety"], "USD"),
    ("Istanbul Maritime", "IMAR A.Ş.", "sales@imar.com.tr", "TR", "Istanbul", ["consumables", "engine_stores", "paint_chemicals"], "USD"),
    ("Gulf Supply LLC", "Gulf Marine Supply", "bids@gulfsupply.ae", "AE", "Dubai", ["provisions", "bond_store", "safety"], "USD"),
    ("Shanghai Marine Supply", "SMS", "info@shms.cn", "CN", "Shanghai", ["consumables", "electrical", "safety"], "USD"),
    ("American Marine Co.", "AMC Provisions", "supply@amcmarine.com", "US", "Houston", ["provisions", "lubricants", "engine_stores"], "USD"),
    ("Nordic Maritime AS", "Nordic Marine", "sales@nordicmaritime.no", "NO", "Bergen", ["navigation", "electrical", "engine_stores"], "EUR"),
    ("Mumbai Marine Pvt.", "MMP", "info@mumbaimarine.in", "IN", "Mumbai", ["provisions", "consumables"], "USD"),
    ("Tokyo Marine KK", "TMK", "sales@tokyomarine.jp", "JP", "Tokyo", ["navigation", "electrical", "safety"], "USD"),
]

USERS = [
    ("admin@avsglobal.com", "admin", "AVS Administrator", "admin123", "super_admin", None),
    ("captain@avsglobal.com", "captain", "Captain Mehmet Yılmaz", "demo123", "vessel_captain", 0),
    ("purchasing@avsglobal.com", "purchaser", "Ayşe Demir", "demo123", "purchasing_officer", 0),
    ("steward@avsglobal.com", "steward", "Carlos Reyes", "demo123", "chief_steward", 0),
    ("supplier@apcmarine.sg", "apcmarine", "APC Marine (Supplier)", "demo123", "supplier", None),
]


def _rand_sku(prefix: str, n: int) -> str:
    return f"{prefix}-{''.join(random.choices(string.digits, k=8))}"


def _rand_hs_code() -> str:
    return f"{random.randint(1000, 9999)}.{random.randint(10, 99):02d}.{random.randint(10, 99):02d}"


async def seed_roles_and_permissions(db: AsyncSession) -> dict[str, Role]:
    """Seed the system roles and permissions; return role-by-name map."""
    print("→ Seeding roles & permissions")
    # Permissions
    perm_map: dict[str, Permission] = {}
    for resource, action, scope in SYSTEM_PERMISSIONS:
        name = f"{resource}:{action}:{scope}"
        stmt = insert(Permission).values(
            name=name,
            resource=resource,
            action=action,
            scope=scope,
            description=f"Permission to {action} {resource} at {scope} scope",
        ).on_conflict_do_nothing(index_elements=["name"])
        await db.execute(stmt)
        result = await db.execute(select(Permission).where(Permission.name == name))
        perm_map[name] = result.scalar_one()

    # Roles
    role_map: dict[str, Role] = {}
    for r in SYSTEM_ROLES:
        stmt = insert(Role).values(
            name=r["name"],
            description=r["description"],
            is_system=r["is_system"],
            priority=r["priority"],
        ).on_conflict_do_nothing(index_elements=["name"])
        await db.execute(stmt)
        result = await db.execute(select(Role).where(Role.name == r["name"]))
        role_map[r["name"]] = result.scalar_one()

    # Assign all permissions to super_admin
    admin_role = role_map["super_admin"]
    for p in perm_map.values():
        stmt = insert(RolePermission).values(
            role_id=admin_role.id, permission_id=p.id
        ).on_conflict_do_nothing()
        await db.execute(stmt)

    # Specific role permission assignments (light, for the demo)
    role_perms = {
        "vessel_captain": [
            "vessels:read:own", "orders:create:own", "orders:read:own",
            "orders:approve:own", "catering:read:own", "menus:read:own",
            "provisioning:read:own", "reports:read:own",
        ],
        "purchasing_officer": [
            "vessels:read:fleet", "ports:read:global", "products:read:global",
            "orders:create:vessel", "orders:read:vessel", "orders:update:vessel",
            "orders:approve:vessel", "rfq:create:own", "rfq:read:own",
            "rfq:manage:vessel", "rfq:simulate:own", "quotes:compare:own",
            "regulations:read:global", "customs:check:own", "sync:manage:own",
            "reports:read:fleet",
        ],
        "chief_steward": [
            "vessels:read:own", "catering:create:own", "catering:read:own",
            "catering:update:own", "menus:create:own", "menus:read:own",
            "menus:update:own", "provisioning:create:own", "provisioning:read:own",
            "provisioning:manage:vessel", "orders:read:own",
        ],
        "supplier": [
            "products:read:global", "rfq:read:own", "quotes:submit:own",
            "quotes:read:own", "orders:read:own",
        ],
    }
    for role_name, perm_names in role_perms.items():
        role = role_map[role_name]
        for pn in perm_names:
            if pn in perm_map:
                stmt = insert(RolePermission).values(
                    role_id=role.id, permission_id=perm_map[pn].id
                ).on_conflict_do_nothing()
                await db.execute(stmt)

    await db.commit()
    return role_map


async def seed_users(db: AsyncSession, role_map: dict[str, Role]) -> dict[str, User]:
    print("→ Seeding users")
    user_map: dict[str, User] = {}
    vessels = (await db.execute(select(Vessel))).scalars().all()
    for email, username, full_name, password, role_name, vessel_index in USERS:
        user = User(
            email=email,
            username=username,
            full_name=full_name,
            hashed_password=get_password_hash(password),
            status=UserStatus.ACTIVE,
            email_verified=True,
            vessel_id=vessels[vessel_index].id if vessel_index is not None and vessels else None,
        )
        db.add(user)
        await db.flush()
        user_map[username] = user
        if role_name in role_map:
            db.add(UserRole(user_id=user.id, role_id=role_map[role_name].id))
    await db.commit()
    return user_map


async def seed_countries(db: AsyncSession) -> dict[str, Country]:
    print("→ Seeding countries")
    country_map: dict[str, Country] = {}
    for iso2, iso3, name, region, currency, prohibited, halal, kosher in COUNTRIES:
        stmt = insert(Country).values(
            code_iso2=iso2, code_iso3=iso3, name=name, region=region,
            currency=currency, prohibited_categories=prohibited,
            requires_halal_cert=halal, requires_kosher_cert=kosher,
        ).on_conflict_do_nothing(index_elements=["code_iso2"])
        await db.execute(stmt)
        result = await db.execute(select(Country).where(Country.code_iso2 == iso2))
        country_map[iso2] = result.scalar_one()
    await db.commit()
    return country_map


async def seed_ports(db: AsyncSession, country_map: dict[str, Country]) -> dict[str, Port]:
    print("→ Seeding ports")
    port_map: dict[str, Port] = {}
    for unlocode, name, country_iso, lat, lon, ptype, tz in PORTS:
        stmt = insert(Port).values(
            unlocode=unlocode, name=name, country_id=country_map[country_iso].id,
            latitude=lat, longitude=lon, port_type=ptype, timezone=tz,
            status=PortStatus.ACTIVE,
            has_bunkering=True, has_fresh_water=True, has_provisions=True,
            has_chandler=True, has_repair=True, has_medical=True,
        ).on_conflict_do_nothing(index_elements=["unlocode"])
        await db.execute(stmt)
        result = await db.execute(select(Port).where(Port.unlocode == unlocode))
        port_map[unlocode] = result.scalar_one()
    await db.commit()
    return port_map


async def seed_vessels(db: AsyncSession) -> list[Vessel]:
    print("→ Seeding vessels")
    out = []
    for imo, name, vtype, flag, owner, loa, beam, draft, dwt, crew in VESSELS:
        stmt = insert(Vessel).values(
            imo_number=imo, name=name, vessel_type=vtype, flag_state=flag,
            owner=owner, loa=loa, beam=beam, draft_summer=draft, dwt=dwt,
            crew_capacity=crew, current_crew_count=crew,
            vsat_provider="Inmarsat" if random.random() > 0.5 else "Iridium",
        ).on_conflict_do_nothing(index_elements=["imo_number"])
        await db.execute(stmt)
        result = await db.execute(select(Vessel).where(Vessel.imo_number == imo))
        out.append(result.scalar_one())
    await db.commit()
    return out


async def seed_categories(db: AsyncSession) -> dict[str, ProductCategory]:
    print("→ Seeding product categories")
    cat_map: dict[str, ProductCategory] = {}
    for code, name, icon, unit in CATEGORIES:
        stmt = insert(ProductCategory).values(
            code=code, name=name, icon=icon, default_unit=UnitOfMeasure(unit),
            sort_order=CATEGORIES.index((code, name, icon, unit)),
        ).on_conflict_do_nothing(index_elements=["code"])
        await db.execute(stmt)
        result = await db.execute(select(ProductCategory).where(ProductCategory.code == code))
        cat_map[code] = result.scalar_one()
    await db.commit()
    return cat_map


# Realistic per-category product name pools. Used to build 5000 catalog rows.
PRODUCT_NAMES: dict[str, list[tuple[str, UnitOfMeasure, str]]] = {
    "deck_stores": [
        ("Wire Rope {size}mm Galvanized", UnitOfMeasure.METER, "deck_stores"),
        ("Manila Rope {size}mm", UnitOfMeasure.METER, "deck_stores"),
        ("Polypropylene Rope {size}mm", UnitOfMeasure.METER, "deck_stores"),
        ("Anchor Chain Shackle {size}", UnitOfMeasure.PIECE, "deck_stores"),
        ("Mooring Rope {size}mm", UnitOfMeasure.METER, "deck_stores"),
        ("Steel Wire {size}mm", UnitOfMeasure.METER, "deck_stores"),
        ("Hessian Twine {size}", UnitOfMeasure.ROLL, "deck_stores"),
        ("Fender {size} Heavy Duty", UnitOfMeasure.PIECE, "deck_stores"),
        ("Boat Hook Aluminium", UnitOfMeasure.PIECE, "deck_stores"),
        ("Lifebuoy {size} cm", UnitOfMeasure.PIECE, "deck_stores"),
    ],
    "engine_stores": [
        ("Piston Ring Set — {brand} {size}", UnitOfMeasure.SET, "engine_stores"),
        ("Cylinder Liner {brand} {size}", UnitOfMeasure.PIECE, "engine_stores"),
        ("Fuel Injector {brand}", UnitOfMeasure.PIECE, "engine_stores"),
        ("Exhaust Valve {brand}", UnitOfMeasure.PIECE, "engine_stores"),
        ("Turbocharger Bearing {brand}", UnitOfMeasure.PIECE, "engine_stores"),
        ("Air Filter Element {size}", UnitOfMeasure.PIECE, "engine_stores"),
        ("Oil Filter Element {size}", UnitOfMeasure.PIECE, "engine_stores"),
        ("Fuel Filter Element {size}", UnitOfMeasure.PIECE, "engine_stores"),
        ("Cooling Water Pump Impeller {brand}", UnitOfMeasure.PIECE, "engine_stores"),
        ("Gasket Set — {brand} {size}", UnitOfMeasure.SET, "engine_stores"),
    ],
    "cabin_stores": [
        ("Bed Sheet Single {color}", UnitOfMeasure.PIECE, "cabin_stores"),
        ("Pillow {size}", UnitOfMeasure.PIECE, "cabin_stores"),
        ("Towel Bath {size}", UnitOfMeasure.PIECE, "cabin_stores"),
        ("Blanket {size}", UnitOfMeasure.PIECE, "cabin_stores"),
        ("Soap Bar 100g", UnitOfMeasure.PIECE, "cabin_stores"),
        ("Shampoo 250ml", UnitOfMeasure.BOTTLE, "cabin_stores"),
        ("Toothpaste 100ml", UnitOfMeasure.PIECE, "cabin_stores"),
        ("Toilet Paper 2-ply", UnitOfMeasure.ROLL, "cabin_stores"),
        ("Detergent Powder 1kg", UnitOfMeasure.BAG, "cabin_stores"),
    ],
    "medical": [
        ("Paracetamol 500mg 100's", UnitOfMeasure.BOX, "medical"),
        ("Bandage Roll 10cm", UnitOfMeasure.PIECE, "medical"),
        ("Antiseptic Solution 1L", UnitOfMeasure.BOTTLE, "medical"),
        ("Surgical Gloves M (Box 100)", UnitOfMeasure.BOX, "medical"),
        ("Surgical Mask (Box 50)", UnitOfMeasure.BOX, "medical"),
        ("First Aid Kit Complete", UnitOfMeasure.SET, "medical"),
        ("Burn Dressing 10x10", UnitOfMeasure.PIECE, "medical"),
        ("Eye Wash Solution 500ml", UnitOfMeasure.BOTTLE, "medical"),
    ],
    "provisions": [
        ("Rice Basmati 25kg", UnitOfMeasure.BAG, "provisions"),
        ("Sugar White 50kg", UnitOfMeasure.BAG, "provisions"),
        ("Flour All-Purpose 25kg", UnitOfMeasure.BAG, "provisions"),
        ("Olive Oil 5L", UnitOfMeasure.CAN, "provisions"),
        ("Sunflower Oil 5L", UnitOfMeasure.CAN, "provisions"),
        ("Salt Iodized 1kg", UnitOfMeasure.BAG, "provisions"),
        ("Black Pepper 500g", UnitOfMeasure.BAG, "provisions"),
        ("Cumin Powder 500g", UnitOfMeasure.BAG, "provisions"),
        ("Chickpeas Dried 25kg", UnitOfMeasure.BAG, "provisions"),
        ("Lentils Red 25kg", UnitOfMeasure.BAG, "provisions"),
        ("Tuna in Oil 1.85kg Can", UnitOfMeasure.CAN, "provisions"),
        ("Tomato Paste 800g Can", UnitOfMeasure.CAN, "provisions"),
        ("Pasta Spaghetti 500g", UnitOfMeasure.BAG, "provisions"),
        ("Onions Fresh 25kg", UnitOfMeasure.BAG, "provisions"),
        ("Potatoes Fresh 25kg", UnitOfMeasure.BAG, "provisions"),
        ("Bananas Fresh 18kg", UnitOfMeasure.BOX, "provisions"),
        ("Apples Fresh 18kg", UnitOfMeasure.BOX, "provisions"),
        ("Frozen Chicken 10kg", UnitOfMeasure.BOX, "provisions"),
        ("Frozen Beef 10kg", UnitOfMeasure.BOX, "provisions"),
        ("Eggs 30's", UnitOfMeasure.BOX, "provisions"),
        ("Milk UHT 1L", UnitOfMeasure.BOX, "provisions"),
        ("Coffee Beans 1kg", UnitOfMeasure.BAG, "provisions"),
        ("Tea Black 500g", UnitOfMeasure.BAG, "provisions"),
        ("Bottled Water 1.5L", UnitOfMeasure.BOX, "provisions"),
    ],
    "bond_store": [
        ("Whisky 12yr 700ml", UnitOfMeasure.BOTTLE, "bond_store"),
        ("Vodka 700ml", UnitOfMeasure.BOTTLE, "bond_store"),
        ("Gin 700ml", UnitOfMeasure.BOTTLE, "bond_store"),
        ("Rum Dark 700ml", UnitOfMeasure.BOTTLE, "bond_store"),
        ("Beer Lager 330ml 24-pack", UnitOfMeasure.BOX, "bond_store"),
        ("Cigarettes 200's Carton", UnitOfMeasure.BOX, "bond_store"),
        ("Cigar Box 25's", UnitOfMeasure.BOX, "bond_store"),
    ],
    "safety": [
        ("Safety Helmet White", UnitOfMeasure.PIECE, "safety"),
        ("Safety Boots Steel Toe Size {size}", UnitOfMeasure.PAIR, "safety"),
        ("Safety Goggles", UnitOfMeasure.PIECE, "safety"),
        ("Disposable Respirator N95 (Box 20)", UnitOfMeasure.BOX, "safety"),
        ("Fire Extinguisher 6kg CO2", UnitOfMeasure.PIECE, "safety"),
        ("Fire Extinguisher 9kg Powder", UnitOfMeasure.PIECE, "safety"),
        ("Life Jacket Adult SOLAS", UnitOfMeasure.PIECE, "safety"),
        ("Life Jacket Child SOLAS", UnitOfMeasure.PIECE, "safety"),
        ("Immersion Suit", UnitOfMeasure.PIECE, "safety"),
        ("Emergency Flare Handheld", UnitOfMeasure.PIECE, "safety"),
        ("Smoke Detector", UnitOfMeasure.PIECE, "safety"),
    ],
    "navigation": [
        ("Magnetic Compass {size}cm", UnitOfMeasure.PIECE, "navigation"),
        ("Sextant", UnitOfMeasure.PIECE, "navigation"),
        ("Navigation Charts Atlantic", UnitOfMeasure.ROLL, "navigation"),
        ("GPS Antenna", UnitOfMeasure.PIECE, "navigation"),
        ("Radar Reflector", UnitOfMeasure.PIECE, "navigation"),
        ("Signal Lamp LED", UnitOfMeasure.PIECE, "navigation"),
        ("Binoculars 7x50", UnitOfMeasure.PAIR, "navigation"),
    ],
    "electrical": [
        ("LED Bulb 60W E27", UnitOfMeasure.PIECE, "electrical"),
        ("Battery 12V 200Ah", UnitOfMeasure.PIECE, "electrical"),
        ("Cable 2.5mm² (100m)", UnitOfMeasure.ROLL, "electrical"),
        ("Fuse 10A 250V (Box 100)", UnitOfMeasure.BOX, "electrical"),
        ("Switch 16A", UnitOfMeasure.PIECE, "electrical"),
        ("Junction Box IP67", UnitOfMeasure.PIECE, "electrical"),
        ("Conduit 20mm (3m)", UnitOfMeasure.PIECE, "electrical"),
    ],
    "consumables": [
        ("Cleaning Powder 5kg", UnitOfMeasure.BAG, "consumables"),
        ("Bleach 5L", UnitOfMeasure.CAN, "consumables"),
        ("Hand Sanitizer 5L", UnitOfMeasure.CAN, "consumables"),
        ("Degreaser 5L", UnitOfMeasure.CAN, "consumables"),
        ("Rags Cotton 10kg Bale", UnitOfMeasure.BAG, "consumables"),
        ("Garbage Bags 100L (Box 100)", UnitOfMeasure.BOX, "consumables"),
    ],
    "lubricants": [
        ("Engine Oil SAE 15W40 200L", UnitOfMeasure.DRUM, "lubricants"),
        ("Hydraulic Oil ISO 46 200L", UnitOfMeasure.DRUM, "lubricants"),
        ("Gear Oil SAE 90 20L", UnitOfMeasure.CAN, "lubricants"),
        ("Compressor Oil ISO 100 20L", UnitOfMeasure.CAN, "lubricants"),
        ("Grease Multi-Purpose 18kg", UnitOfMeasure.PAIL, "lubricants"),
        ("Cylinder Oil 1000 200L", UnitOfMeasure.DRUM, "lubricants"),
    ],
    "paint_chemicals": [
        ("Anti-Fouling Paint Red 20L", UnitOfMeasure.CAN, "paint_chemicals"),
        ("Anti-Corrosive Primer 20L", UnitOfMeasure.CAN, "paint_chemicals"),
        ("Topside Paint White 20L", UnitOfMeasure.CAN, "paint_chemicals"),
        ("Paint Thinner 5L", UnitOfMeasure.CAN, "paint_chemicals"),
        ("Rust Converter 5L", UnitOfMeasure.CAN, "paint_chemicals"),
        ("Epoxy Coating 20L", UnitOfMeasure.CAN, "paint_chemicals"),
    ],
}

SIZES = ["6", "8", "10", "12", "16", "20", "24", "30", "40", "50", "60", "80", "100"]
COLORS = ["White", "Blue", "Beige", "Grey", "Green"]
BRANDS = ["MAN B&W", "Wartsila", "Caterpillar", "Yanmar", "Cummins", "Deutz"]


def _gen_product_name(template: str) -> tuple[str, dict]:
    """Replace {size}, {color}, {brand} placeholders with random values."""
    out = template
    meta = {}
    while "{size}" in out:
        out = out.replace("{size}", random.choice(SIZES), 1)
        meta["size"] = "var"
    if "{color}" in out:
        out = out.replace("{color}", random.choice(COLORS), 1)
    if "{brand}" in out:
        out = out.replace("{brand}", random.choice(BRANDS), 1)
    return out, meta


async def seed_products(db: AsyncSession, cat_map: dict[str, ProductCategory]) -> int:
    """Generate ~5000 IMPA-coded catalog products."""
    print("→ Seeding products (this is the big one)")
    target_count = 5000
    seen: set[str] = set()
    products: list[dict] = []
    counter = 0
    # Use the IMPA group codes to organize product numbering
    group_letter = 0
    while counter < target_count:
        for cat_code, templates in PRODUCT_NAMES.items():
            for tmpl, unit, cat in templates:
                if counter >= target_count:
                    break
                name, _meta = _gen_product_name(tmpl)
                impa_group = str(30 + group_letter).zfill(2)
                # 6-digit IMPA code: group + 4 digits
                impa_code_str = f"{impa_group}{random.randint(0, 9999):04d}"
                # Skip duplicates
                if impa_code_str in seen:
                    continue
                seen.add(impa_code_str)
                sku = f"AVS-{cat_code[:3].upper()}-{counter:06d}"
                products.append({
                    "id": uuid4(),
                    "sku": sku,
                    "name": name,
                    "short_name": None,
                    "description": f"Quality {name.lower()} for maritime use.",
                    "category_id": cat_map[cat_code].id,
                    "status": ProductStatus.ACTIVE if random.random() > 0.05 else ProductStatus.DISCONTINUED,
                    "hs_code": _rand_hs_code(),
                    "manufacturer": random.choice(["Wilhelmsen", "Unitor", "Marisol", "Acme Marine", "Veritas", "Lemar", "OceanCo"]),
                    "unit": unit,
                    "weight_kg": round(random.uniform(0.1, 50.0), 3) if unit != UnitOfMeasure.PIECE else None,
                    "volume_m3": round(random.uniform(0.001, 0.5), 6) if unit in (UnitOfMeasure.BOX, UnitOfMeasure.DRUM) else None,
                    "unit_price": round(random.uniform(1.0, 2000.0), 4),
                    "currency": "USD",
                    "min_order_qty": random.choice([1, 5, 10, 25]),
                    "in_stock": random.random() > 0.1,
                    "stock_qty": random.randint(0, 5000) if random.random() > 0.1 else 0,
                    "lead_time_days": random.choice([3, 5, 7, 14, 21, 30]),
                    "is_hazardous": cat_code in ("paint_chemicals", "lubricants") and random.random() > 0.5,
                    "is_perishable": cat_code == "provisions" and random.random() > 0.6,
                    "shelf_life_days": random.choice([180, 365, 720]) if cat_code == "provisions" else None,
                    "tags": _tags_for_category(cat_code),
                    "impa_code": impa_code_str,
                    "manufacturer_part": f"MP-{random.randint(1000, 9999)}",
                })
                counter += 1
                if counter >= target_count:
                    break
        group_letter += 1
        if group_letter > 50:
            break

    # Bulk insert in chunks
    CHUNK = 500
    for i in range(0, len(products), CHUNK):
        chunk = products[i:i+CHUNK]
        await db.execute(Product.__table__.insert(), chunk)
        print(f"  · inserted {min(i+CHUNK, len(products))}/{len(products)}")
    await db.commit()

    # Now populate the IMPA code table
    print("→ Building IMPA code table from products")
    # Aggregate unique (impa_code, name) pairs
    distinct = {}
    for p in products:
        code = p["impa_code"]
        if code not in distinct:
            distinct[code] = p["name"]
    impa_rows = [
        {
            "id": uuid4(),
            "code": code,
            "name": name,
            "description": f"IMPA group {code[:2]}",
            "group_code": code[:2],
        }
        for code, name in distinct.items()
    ]
    for i in range(0, len(impa_rows), CHUNK):
        await db.execute(ImpaCode.__table__.insert(), impa_rows[i:i+CHUNK])
    await db.commit()

    # Bind products -> IMPA codes
    print("→ Linking products to IMPA codes")
    result = await db.execute(select(ImpaCode.id, ImpaCode.code))
    code_to_id = {code: id_ for id_, code in result.all()}
    CHUNK = 500
    updates = []
    for p in products:
        if p["impa_code"] in code_to_id:
            updates.append({"id": p["id"], "impa_code_id": code_to_id[p["impa_code"]]})
    # Bulk update by id using a CASE WHEN
    from sqlalchemy import case, cast
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID
    for i in range(0, len(updates), CHUNK):
        chunk = updates[i:i+CHUNK]
        ids = [u["id"] for u in chunk]
        whens = {u["id"]: cast(u["impa_code_id"], PG_UUID) for u in chunk}
        stmt = (
            Product.__table__.update()
            .where(Product.id.in_(ids))
            .values(impa_code_id=case(whens, value=Product.id))
        )
        await db.execute(stmt)
    await db.commit()

    # ISSA — pick a subset of products to also have an ISSA code
    print("→ Seeding ISSA codes (subset of products)")
    issa_count = 1000
    result = await db.execute(select(Product.id).limit(issa_count))
    product_ids = [r[0] for r in result.all()]
    issa_rows = []
    used_codes: set[str] = set()
    for i in range(issa_count):
        while True:
            code = f"{random.randint(100000, 999999)}"
            if code not in used_codes:
                used_codes.add(code)
                break
        issa_rows.append(
            {
                "id": uuid4(),
                "code": code,
                "name": "ISSA Catalog Reference",
                "description": "ISSA cross-reference",
            }
        )
    for i in range(0, len(issa_rows), CHUNK):
        await db.execute(IssaCode.__table__.insert(), issa_rows[i:i+CHUNK])
    await db.commit()
    result = await db.execute(select(IssaCode.id, IssaCode.code))
    issa_codes = result.all()
    updates = [
        {"id": pid, "issa_code_id": issa_codes[i][0]}
        for i, pid in enumerate(product_ids[:len(issa_codes)])
    ]
    from sqlalchemy import case, cast
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID
    whens = {u["id"]: cast(u["issa_code_id"], PG_UUID) for u in updates}
    stmt = (
        Product.__table__.update()
        .where(Product.id.in_([u["id"] for u in updates]))
        .values(issa_code_id=case(whens, value=Product.id))
    )
    await db.execute(stmt)
    await db.commit()

    return counter


def _tags_for_category(cat_code: str) -> list[str]:
    base = []
    if cat_code == "provisions":
        base += ["food", "perishable"]
        if random.random() > 0.3:
            base += ["halal"]
        if random.random() > 0.7:
            base += ["vegan"]
    elif cat_code == "bond_store":
        base += ["alcohol", "duty_free"]
    elif cat_code == "safety":
        base += ["solas", "ppe"]
    elif cat_code == "engine_stores":
        base += ["spare_part"]
    elif cat_code == "lubricants" or cat_code == "paint_chemicals":
        base += ["hazardous", "chemical"]
    return base


async def populate_tsvectors(db: AsyncSession) -> None:
    """Update the tsvector columns for FTS. The trigger would do this in prod;
    we run it once after seeding."""
    print("→ Building tsvector columns (FTS index data)")
    # Build the vector from name + short_name + description + manufacturer
    await db.execute(text("""
        UPDATE products
        SET
            name_tsv = to_tsvector('simple', coalesce(name, '') || ' ' || coalesce(short_name, '')),
            description_tsv = to_tsvector('simple', coalesce(description, '')),
            full_tsv = to_tsvector('simple',
                coalesce(name, '') || ' ' ||
                coalesce(short_name, '') || ' ' ||
                coalesce(description, '') || ' ' ||
                coalesce(manufacturer, '') || ' ' ||
                coalesce(sku, '')
            )
        WHERE name_tsv IS NULL
    """))
    await db.commit()


async def seed_regulations(db: AsyncSession, country_map: dict[str, Country], port_map: dict[str, Port]) -> None:
    print("→ Seeding regulations and customs rules")
    # Country-level customs rules
    sg = country_map["SG"]
    ae = country_map["AE"]
    sa = country_map["SA"]
    eg = country_map["EG"]
    rules = [
        CustomsRule(
            country_id=sg.id, category=RegulationCategory.CUSTOMS,
            severity=RegulationSeverity.WARNING, name="Pork import advisory",
            description="Singapore requires additional documentation for pork products.",
            hs_code_pattern="02", product_categories=["provisions"],
            action="require_permit", effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
            action_params={"permit_type": "AVA Import Permit"},
        ),
        CustomsRule(
            country_id=ae.id, category=RegulationCategory.CUSTOMS,
            severity=RegulationSeverity.PROHIBITED, name="Pork and alcohol prohibited",
            description="UAE prohibits import of pork and alcohol products.",
            hs_code_pattern="02", product_categories=["provisions", "bond_store"],
            action="block", effective_from=datetime(2010, 1, 1, tzinfo=timezone.utc),
        ),
        CustomsRule(
            country_id=sa.id, category=RegulationCategory.CUSTOMS,
            severity=RegulationSeverity.PROHIBITED, name="Pork and alcohol prohibited",
            description="Saudi Arabia prohibits import of pork and alcohol.",
            hs_code_pattern="02", product_categories=["provisions", "bond_store"],
            action="block", effective_from=datetime(2010, 1, 1, tzinfo=timezone.utc),
        ),
        CustomsRule(
            country_id=eg.id, category=RegulationCategory.CUSTOMS,
            severity=RegulationSeverity.WARNING, name="Alcohol permit required",
            description="Egypt requires special permit for alcohol imports above 2L.",
            product_categories=["bond_store"], action="require_permit",
            effective_from=datetime(2015, 1, 1, tzinfo=timezone.utc),
            action_params={"permit_type": "Egyptian Customs Permit"},
        ),
    ]
    db.add_all(rules)
    # Port-level
    dubai = port_map["AEDXB"]
    dammam = port_map["SADMM"]
    singapore = port_map["SGSIN"]
    suez = port_map["EGSUZ"]
    port_rules = [
        PortRegulation(
            port_id=dubai.id, country_id=ae.id, category=RegulationCategory.CUSTOMS,
            severity=RegulationSeverity.PROHIBITED,
            title="Strict halal certification required for fresh produce",
            description="Dubai Port requires all fresh meat to carry an accredited halal certificate.",
            applies_to_categories=["provisions"], requires_permit=True,
            permit_authority="UAE Ministry of Climate Change & Environment",
            permit_lead_time_days=7, effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
            is_permanent=True,
        ),
        PortRegulation(
            port_id=singapore.id, country_id=sg.id, category=RegulationCategory.SANITARY_PHYTOSANITARY,
            severity=RegulationSeverity.WARNING,
            title="AVA Phytosanitary Certificate",
            description="Singapore requires AVA phytosanitary certificate for fresh produce.",
            applies_to_categories=["provisions"], requires_permit=True,
            permit_authority="Agri-Food & Veterinary Authority of Singapore",
            permit_lead_time_days=3, effective_from=datetime(2018, 1, 1, tzinfo=timezone.utc),
            is_permanent=True,
        ),
        PortRegulation(
            port_id=suez.id, country_id=eg.id, category=RegulationCategory.SECURITY,
            severity=RegulationSeverity.WARNING,
            title="ISPS Level 2 — Advance notice required",
            description="Suez Canal transits require 48h advance notice and ISPS compliance.",
            applies_to_vessel_types=["tanker", "lng_carrier", "lpg_carrier"],
            requires_permit=True, permit_authority="Suez Canal Authority",
            permit_lead_time_days=2, effective_from=datetime(2010, 1, 1, tzinfo=timezone.utc),
            is_permanent=True,
        ),
    ]
    db.add_all(port_rules)
    await db.commit()


async def seed_suppliers(
    db: AsyncSession, port_map: dict[str, Port], cat_map: dict[str, ProductCategory]
) -> list[Supplier]:
    print("→ Seeding suppliers")
    suppliers = []
    for name, legal, email, country_iso, city, categories, currency in SUPPLIERS:
        stmt = insert(Supplier).values(
            company_name=name, legal_name=legal, contact_email=email,
            country_code=country_iso, city=city, categories=categories,
            currency=currency, status=SupplierStatus.ACTIVE,
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
        result = await db.execute(select(Supplier).where(Supplier.contact_email == email))
        suppliers.append(result.scalar_one())
    await db.commit()

    # Each supplier serves a few ports
    port_ids = list(port_map.values())
    for s in suppliers:
        # Pick 2-3 random ports
        for p in random.sample(port_ids, k=min(3, len(port_ids))):
            db.add(SupplierPort(supplier_id=s.id, port_id=p.id, is_primary=True))
        # Each supplier offers a few products matching their categories
        product_rows = (await db.execute(
            select(Product.id).limit(200)
        )).all()
        # Filter by matching tags (in-process; small dataset for demo)
        all_product_ids = [r[0] for r in product_rows]
        random.shuffle(all_product_ids)
        for pid in all_product_ids[:20]:
            db.add(ProductSupplier(
                supplier_id=s.id, product_id=pid,
                unit_price=round(random.uniform(1.0, 500.0), 4),
                currency=s.currency, lead_time_days=random.choice([3, 5, 7, 14]),
                in_stock=True,
            ))
    await db.commit()
    return suppliers


async def seed_nationalities(db: AsyncSession) -> dict[CrewNationalityEnum, CrewNationality]:
    print("→ Seeding crew nationalities")
    out: dict[CrewNationalityEnum, CrewNationality] = {}
    profiles = [
        (CrewNationalityEnum.FILIPINO, "Filipino", 3000, 0.20, 0.55, 0.25, ["halal"], ["provisions"]),
        (CrewNationalityEnum.INDIAN, "Indian", 3200, 0.18, 0.55, 0.27, ["halal", "vegetarian"], ["provisions"]),
        (CrewNationalityEnum.EUROPEAN, "European", 3400, 0.20, 0.45, 0.35, [], ["provisions", "bond_store"]),
        (CrewNationalityEnum.CHINESE, "Chinese", 3100, 0.20, 0.55, 0.25, [], ["provisions"]),
        (CrewNationalityEnum.TURKISH, "Turkish", 3300, 0.20, 0.50, 0.30, ["halal"], ["provisions"]),
    ]
    for code, name, kcal, p, c, f, diet_flags, categories in profiles:
        n = CrewNationality(
            code=code, name=name, calorie_target=kcal,
            protein_pct=p, carb_pct=c, fat_pct=f,
            preferred_diet_flags=diet_flags, preferred_categories=categories,
            default_meal_slots=[
                {"type": "breakfast", "time": "07:00"},
                {"type": "lunch", "time": "12:00"},
                {"type": "dinner", "time": "18:30"},
                {"type": "snack", "time": "15:00"},
            ],
        )
        db.add(n)
        out[code] = n
    await db.commit()
    return out


async def seed_menu_templates(db: AsyncSession, nationalities: dict[CrewNationalityEnum, CrewNationality]) -> None:
    print("→ Seeding menu templates")
    # For each nationality and meal type, pick a few products in provisions
    provisions = (await db.execute(
        text("SELECT id FROM products WHERE tags @> '[\"provisions\"]'::jsonb OR tags @> '[\"food\"]'::jsonb LIMIT 200")
    )).all()
    if not provisions:
        return
    product_ids = [p[0] for p in provisions]
    for nat_code, nat in nationalities.items():
        for meal in [MealType.BREAKFAST, MealType.LUNCH, MealType.DINNER, MealType.SNACK]:
            target_kcal = int(nat.calorie_target * {
                MealType.BREAKFAST: 0.25,
                MealType.LUNCH: 0.30,
                MealType.DINNER: 0.30,
                MealType.SNACK: 0.10,
            }.get(meal, 0.25))
            tpl = MenuTemplate(
                name=f"{nat.name} {meal.value.title()}",
                nationality=nat.code, meal_type=meal,
                target_kcal=target_kcal, is_default=True,
                diet_flags=nat.preferred_diet_flags or [],
            )
            db.add(tpl)
            await db.flush()
            # Pick 4-7 items
            n = random.randint(4, 7)
            selected = random.sample(product_ids, k=min(n, len(product_ids)))
            for j, pid in enumerate(selected):
                db.add(MenuItem(
                    template_id=tpl.id, product_id=pid,
                    serving_grams=random.randint(50, 250),
                    sort_order=j,
                ))
    await db.commit()


async def main(skip_if_populated: bool = False) -> None:
    print("=" * 60)
    print("AVS Global — seed script")
    print("=" * 60)
    print(f"Database: {engine.url}")
    print()
    await init_db()

    if skip_if_populated:
        async with async_session_factory() as db:
            from sqlalchemy import select, func as sa_func
            from app.models import Product
            count = (await db.execute(select(sa_func.count(Product.id)))).scalar_one()
            if count > 0:
                print(f"⚠ Database already populated ({count} products) — skipping seed.")
                return

    async with async_session_factory() as db:
        role_map = await seed_roles_and_permissions(db)
        country_map = await seed_countries(db)
        port_map = await seed_ports(db, country_map)
        vessels = await seed_vessels(db)
        cat_map = await seed_categories(db)
        n = await seed_products(db, cat_map)
        print(f"  · inserted {n} products")
        await populate_tsvectors(db)
        await seed_regulations(db, country_map, port_map)
        await seed_suppliers(db, port_map, cat_map)
        nationalities = await seed_nationalities(db)
        await seed_menu_templates(db, nationalities)
        user_map = await seed_users(db, role_map)
    print()
    print("✅ Seed complete")
    print()
    print("Demo logins:")
    for u in USERS:
        print(f"  · {u[0]:30s}  /  {u[3]}")


if __name__ == "__main__":
    import sys
    skip = "--skip-if-populated" in sys.argv
    asyncio.run(main(skip_if_populated=skip))
