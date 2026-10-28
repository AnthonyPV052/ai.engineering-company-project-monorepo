from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, EmailStr, Field


class UserRoleEnum(str, Enum):
    admin = "admin"
    manager = "manager"
    user = "user"


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str | None = None
    phone: str | None = None
    address: str | None = None


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8)
    role: UserRoleEnum | None = None
    is_active: bool | None = None


class UserStored(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    email: EmailStr
    hashed_password: str
    is_active: bool = True
    role: UserRoleEnum = UserRoleEnum.user
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UserPublic(BaseModel):
    id: str
    email: EmailStr
    is_active: bool
    role: UserRoleEnum
    created_at: datetime


class ProfileUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    address: str | None = None


class ProfileStored(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    name: str | None = None
    phone: str | None = None
    address: str | None = None


class ProfilePublic(BaseModel):
    id: str
    user_id: str
    name: str | None = None
    phone: str | None = None
    address: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1)
    new_password: str = Field(min_length=8)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class AuthMeResponse(BaseModel):
    id: str
    email: EmailStr
    role: UserRoleEnum
    profile: ProfilePublic | None = None


class UserRegistrationResponse(BaseModel):
    """Respuesta tipada para POST /users (registro)."""

    user: UserPublic
    profile: ProfilePublic
