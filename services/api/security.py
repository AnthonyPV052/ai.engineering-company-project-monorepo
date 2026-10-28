from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from users_service import get_user_by_id

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
ALGORITHM = "HS256"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _load_dotenv() -> None:
    if not ENV_FILE.exists():
        return

    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


def get_secret_key() -> str:
    secret = os.getenv("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY is required. Set it in services/api/.env")
    return secret


def get_access_token_expire_minutes() -> int:
    raw_value = os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError("ACCESS_TOKEN_EXPIRE_MINUTES must be a valid integer") from exc
    if value <= 0:
        raise RuntimeError("ACCESS_TOKEN_EXPIRE_MINUTES must be greater than 0")
    return value


def get_password_reset_token_expire_minutes() -> int:
    raw_value = os.getenv("PASSWORD_RESET_TOKEN_EXPIRE_MINUTES", "15")
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError("PASSWORD_RESET_TOKEN_EXPIRE_MINUTES must be a valid integer") from exc
    if value <= 0:
        raise RuntimeError("PASSWORD_RESET_TOKEN_EXPIRE_MINUTES must be greater than 0")
    return value


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(*, user_id: str, expires_delta: timedelta | None = None) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=get_access_token_expire_minutes())
    )
    payload = {
        "sub": user_id,
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(payload, get_secret_key(), algorithm=ALGORITHM)


def create_password_reset_token(*, user_id: str) -> tuple[str, str, datetime]:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=get_password_reset_token_expire_minutes())
    token_id = str(uuid4())
    token = jwt.encode(
        {"sub": user_id, "jti": token_id, "purpose": "password_reset", "exp": int(expires_at.timestamp())},
        get_secret_key(),
        algorithm=ALGORITHM,
    )
    return token, token_id, expires_at


def validate_password_reset_token(token: str) -> tuple[str, str]:
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid or expired password reset token") from exc

    user_id = payload.get("sub")
    token_id = payload.get("jti")
    if payload.get("purpose") != "password_reset" or not user_id or not token_id:
        raise ValueError("Invalid or expired password reset token")
    return user_id, token_id


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise credentials_exception
    except JWTError as exc:
        raise credentials_exception from exc

    user = get_user_by_id(user_id)
    if user is None or not user.get("is_active", True):
        raise credentials_exception

    return user
