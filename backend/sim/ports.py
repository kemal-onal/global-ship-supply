"""
Hand-picked set of major maritime hubs used by the simulator.

Why a hand-picked set?
~~~~~~~~~~~~~~~~~~~~~~

The simulator's job is to drive plausible traffic into the AVS Global
backend. ~50 ports covers the vast majority of real merchant traffic
(all major container hubs, oil terminals, and key canal/port-of-call
locations) and keeps the dataset hand-auditable.

Coordinates are public-domain (UN/LOCODE, World Port Index, port
authority websites). They are *approximate* — within ~0.5 nm of the
actual berth — which is the resolution AIS data is reported at anyway.

To extend: append a ``Port(...)`` to ``PORTS``. All other modules read
this list at import time.
"""
from __future__ import annotations

from .types import Port

# Mediterranean & Europe
PORTS: list[Port] = [
    # --- Asia ---
    Port("SGSIN", "Singapore", "SG", "Singapore", "asia", 1.2644, 103.8200),
    Port("CNSHA", "Shanghai", "CN", "China", "asia", 31.3416, 121.6493),
    Port("CNNGB", "Ningbo-Zhoushan", "CN", "China", "asia", 29.8683, 121.5440),
    Port("CNSHE", "Shenzhen", "CN", "China", "asia", 22.5431, 114.0579),
    Port("HKHKG", "Hong Kong", "HK", "Hong Kong", "asia", 22.3193, 114.1694),
    Port("CNNSA", "Qingdao", "CN", "China", "asia", 36.0671, 120.3826),
    Port("KRPUS", "Busan", "KR", "South Korea", "asia", 35.1020, 129.0403),
    Port("JPYOK", "Yokohama", "JP", "Japan", "asia", 35.4437, 139.6380),
    Port("JPTYO", "Tokyo", "JP", "Japan", "asia", 35.6528, 139.8395),
    Port("JPKIX", "Kobe", "JP", "Japan", "asia", 34.6898, 135.1956),
    Port("TWKHH", "Kaohsiung", "TW", "Taiwan", "asia", 22.6273, 120.3014),
    Port("INMUN", "Mundra", "IN", "India", "asia", 22.7393, 69.7220),
    Port("INNSA", "Mumbai (JNPT)", "IN", "India", "asia", 18.9633, 72.9525),
    Port("INMAA", "Chennai", "IN", "India", "asia", 13.0827, 80.2707),
    Port("AEJEA", "Jebel Ali (Dubai)", "AE", "United Arab Emirates", "asia", 24.9858, 55.0613),
    Port("SAJED", "Jeddah", "SA", "Saudi Arabia", "asia", 21.4858, 39.1925),
    Port("LBBEY", "Beirut", "LB", "Lebanon", "asia", 33.8938, 35.5018),
    Port("MYPKG", "Port Klang", "MY", "Malaysia", "asia", 3.0042, 101.3997),
    Port("THLCH", "Laem Chabang", "TH", "Thailand", "asia", 13.0762, 100.8848),
    Port("IDJKT", "Jakarta (Tanjung Priok)", "ID", "Indonesia", "asia", -6.1045, 106.8800),
    Port("PHMNL", "Manila", "PH", "Philippines", "asia", 14.5995, 120.9842),
    # --- Middle East / Indian Ocean ---
    Port("OMSLL", "Salalah", "OM", "Oman", "asia", 16.9320, 54.0036),
    Port("EGSUZ", "Suez (Port Suez)", "EG", "Egypt", "africa", 29.9668, 32.5498),
    # --- Europe ---
    Port("NLRTM", "Rotterdam", "NL", "Netherlands", "europe", 51.9525, 4.1392),
    Port("BEANR", "Antwerp", "BE", "Belgium", "europe", 51.2602, 4.4023),
    Port("DEHAM", "Hamburg", "DE", "Germany", "europe", 53.5409, 9.9686),
    Port("DEBRV", "Bremerhaven", "DE", "Germany", "europe", 53.5396, 8.5810),
    Port("DEWVN", "Wilhelmshaven", "DE", "Germany", "europe", 53.5235, 8.1126),
    Port("GBFXT", "Felixstowe", "GB", "United Kingdom", "europe", 51.9542, 1.3104),
    Port("GBPME", "Portsmouth", "GB", "United Kingdom", "europe", 50.7989, -1.0912),
    Port("ESVLC", "Valencia", "ES", "Spain", "europe", 39.4484, -0.3161),
    Port("ESALG", "Algeciras", "ES", "Spain", "europe", 36.1395, -5.4545),
    Port("ITGOA", "Genoa", "IT", "Italy", "europe", 44.4056, 8.9463),
    Port("ITCVV", "Civitavecchia", "IT", "Italy", "europe", 42.0942, 11.7964),
    Port("FRLEH", "Le Havre", "FR", "France", "europe", 49.4944, 0.1079),
    Port("FRMRS", "Marseille", "FR", "France", "europe", 43.3043, 5.3690),
    Port("GITAR", "Gibraltar", "GI", "Gibraltar", "europe", 36.1408, -5.3536),
    Port("GRPIR", "Piraeus", "GR", "Greece", "europe", 37.9420, 23.6469),
    Port("MTMLA", "Valletta (Malta)", "MT", "Malta", "europe", 35.8989, 14.5146),
    # --- North America ---
    Port("USLAX", "Los Angeles", "US", "United States", "north_america", 33.7395, -118.2610),
    Port("USLGB", "Long Beach", "US", "United States", "north_america", 33.7542, -118.2165),
    Port("USNYC", "New York / New Jersey", "US", "United States", "north_america", 40.6692, -74.0445),
    Port("USSAV", "Savannah", "US", "United States", "north_america", 32.0833, -81.0995),
    Port("USCHS", "Charleston", "US", "United States", "north_america", 32.7833, -79.9333),
    Port("CAVAN", "Vancouver", "CA", "Canada", "north_america", 49.2880, -123.1120),
    Port("MXZLO", "Lázaro Cárdenas", "MX", "Mexico", "north_america", 17.9614, -102.1814),
    # --- South America ---
    Port("BRSSZ", "Santos", "BR", "Brazil", "south_america", -23.9608, -46.3331),
    Port("CLVAP", "Valparaíso", "CL", "Chile", "south_america", -33.0472, -71.6127),
    # --- Africa ---
    Port("ZADUR", "Durban", "ZA", "South Africa", "africa", -29.8587, 31.0218),
    Port("MAPTM", "Port Tangier-Med", "MA", "Morocco", "africa", 35.8838, -5.5119),
    Port("NGLOS", "Lagos (Apapa)", "NG", "Nigeria", "africa", 6.4474, 3.3903),
    # --- Oceania ---
    Port("AUSYD", "Sydney", "AU", "Australia", "oceania", -33.8688, 151.2093),
    Port("AUMEL", "Melbourne", "AU", "Australia", "oceania", -37.8400, 144.9000),
    # --- Central America / Canal ---
    Port("PAPCN", "Panama (Balboa)", "PA", "Panama", "north_america", 8.9583, -79.5667),
]


def get_port(un_locode: str) -> Port:
    """Look up a port by UN/LOCODE. Raises ``KeyError`` if unknown."""
    for p in PORTS:
        if p.un_locode == un_locode.upper():
            return p
    raise KeyError(f"Unknown port UN/LOCODE: {un_locode!r}")


def ports_by_region(region: str) -> list[Port]:
    """Filter the port list by region string (e.g. 'asia', 'europe')."""
    region = region.lower()
    return [p for p in PORTS if p.region == region]


__all__ = ["PORTS", "get_port", "ports_by_region"]
