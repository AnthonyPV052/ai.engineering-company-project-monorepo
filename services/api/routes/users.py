from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from auth_models import ProfilePublic, UserCreate, UserPublic, UserRegistrationResponse, UserRoleEnum, UserUpdate
from schemas import MessageResponse
from security import get_current_user, hash_password
from users_service import (
    create_user,
    delete_user,
    get_profile_by_user_id,
    get_user_by_email,
    get_user_by_id,
    list_users,
    update_user,
)

router = APIRouter(prefix="/users", tags=["users"])


def _to_user_public(user: dict) -> UserPublic:
    return UserPublic(
        id=user["id"],
        email=user["email"],
        is_active=user.get("is_active", True),
        role=UserRoleEnum(user["role"]),
        created_at=user["created_at"],
    )


def _ensure_same_user_or_admin(current_user: dict, target_user_id: str) -> None:
    if current_user["id"] == target_user_id:
        return
    if current_user.get("role") == UserRoleEnum.admin.value:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


@router.post("", response_model=UserRegistrationResponse, status_code=status.HTTP_201_CREATED)
def register_user(payload: UserCreate) -> UserRegistrationResponse:
    existing = get_user_by_email(payload.email)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user, profile = create_user(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=UserRoleEnum.user,
        profile_name=payload.name,
        profile_phone=payload.phone,
        profile_address=payload.address,
    )
    return UserRegistrationResponse(
        user=_to_user_public(user),
        profile=ProfilePublic(**profile),
    )


@router.get("", response_model=list[UserPublic])
def get_users(current_user: dict = Depends(get_current_user)) -> list[UserPublic]:
    if current_user.get("role") != UserRoleEnum.admin.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")

    return [_to_user_public(user) for user in list_users()]


@router.get("/{user_id}", response_model=UserPublic)
def get_user(user_id: str, current_user: dict = Depends(get_current_user)) -> UserPublic:
    _ensure_same_user_or_admin(current_user, user_id)
    user = get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return _to_user_public(user)


@router.put("/{user_id}", response_model=UserPublic)
def put_user(user_id: str, payload: UserUpdate, current_user: dict = Depends(get_current_user)) -> UserPublic:
    _ensure_same_user_or_admin(current_user, user_id)
    is_admin = current_user.get("role") == UserRoleEnum.admin.value

    if payload.role is not None and not is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admin can change role")

    if payload.is_active is not None and not is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admin can change activation")

    if payload.email is not None:
        existing = get_user_by_email(payload.email)
        if existing is not None and existing["id"] != user_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    updated = update_user(
        user_id,
        payload,
        hashed_password=hash_password(payload.password) if payload.password else None,
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return _to_user_public(updated)


@router.delete("/{user_id}", response_model=MessageResponse)
def remove_user(user_id: str, current_user: dict = Depends(get_current_user)) -> MessageResponse:
    _ensure_same_user_or_admin(current_user, user_id)
    deleted = delete_user(user_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return MessageResponse(message="User deleted")


@router.get("/{user_id}/profile", response_model=ProfilePublic)
def get_user_profile(user_id: str, current_user: dict = Depends(get_current_user)) -> ProfilePublic:
    _ensure_same_user_or_admin(current_user, user_id)
    user = get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    profile = get_profile_by_user_id(user_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return ProfilePublic(**profile)