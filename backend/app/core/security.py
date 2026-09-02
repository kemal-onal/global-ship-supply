"""
Security utilities: password hashing, JWT handling, token verification.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jose import jwt
from passlib.context import CryptContext
from pydantic import SecretStr

from app.core.config import settings

# Password hashing
pwd_context = CryptContext(schemes=["argon2", "bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


# JWT Key Management
def load_private_key() -> str:
    key_path = Path(settings.JWT_PRIVATE_KEY_PATH)
    if key_path.exists():
        return key_path.read_text()
    # Generate ephemeral key for development
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(pem)
    return pem.decode()


def load_public_key() -> str:
    key_path = Path(settings.JWT_PUBLIC_KEY_PATH)
    if key_path.exists():
        return key_path.read_text()
    # Derive from private key
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_pem = load_private_key().encode()
    private_key = serialization.load_pem_private_key(private_pem, password=None)
    public_key = private_key.public_key()
    pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(pem)
    return pem.decode()


PRIVATE_KEY = load_private_key()
PUBLIC_KEY = load_public_key()


def create_access_token(
    subject: str,
    roles: list[str],
    permissions: list[str],
    vessel_id: int | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode = {
        "sub": subject,
        "roles": roles,
        "permissions": permissions,
        "vessel_id": vessel_id,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    return jwt.encode(to_encode, PRIVATE_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(subject: str, expires_delta: timedelta | None = None) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    to_encode = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "refresh",
    }
    return jwt.encode(to_encode, PRIVATE_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, PUBLIC_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise ValueError("Token has expired")
    except jwt.JWTError as e:
        raise ValueError(f"Invalid token: {e}")


def verify_token(token: str) -> dict[str, Any] | None:
    try:
        return decode_token(token)
    except ValueError:
        return None


class TokenData:
    def __init__(
        self,
        sub: str,
        roles: list[str],
        permissions: list[str],
        vessel_id: int | None = None,
        exp: datetime | None = None,
    ):
        self.sub = sub
        self.roles = roles
        self.permissions = permissions
        self.vessel_id = vessel_id
        self.exp = exp

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "TokenData":
        return cls(
            sub=payload.get("sub", ""),
            roles=payload.get("roles", []),
            permissions=payload.get("permissions", []),
            vessel_id=payload.get("vessel_id"),
            exp=datetime.fromtimestamp(payload["exp"], tz=timezone.utc) if payload.get("exp") else None,
        )

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions

    def has_any_role(self, roles: list[str]) -> bool:
        return any(r in self.roles for r in roles)

    def has_any_permission(self, permissions: list[str]) -> bool:
        return any(p in self.permissions for p in permissions)