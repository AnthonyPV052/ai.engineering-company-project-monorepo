from __future__ import annotations

from fastapi import APIRouter, Depends

from auth_models import ProfilePublic, ProfileUpdate
from security import get_current_user
from users_service import get_profile_by_user_id, update_profile_by_user_id

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get("/me", response_model=ProfilePublic)
def get_my_profile(current_user: dict = Depends(get_current_user)) -> ProfilePublic:
    profile = get_profile_by_user_id(current_user["id"])
    if profile is None:
        profile = update_profile_by_user_id(current_user["id"], ProfileUpdate())
    return ProfilePublic(**profile)


@router.put("/me", response_model=ProfilePublic)
def put_my_profile(payload: ProfileUpdate, current_user: dict = Depends(get_current_user)) -> ProfilePublic:
    profile = update_profile_by_user_id(current_user["id"], payload)
    return ProfilePublic(**profile)