from __future__ import annotations

from datetime import datetime, timezone

from tinydb import Query

from auth_models import ProfileStored, ProfileUpdate, UserRoleEnum, UserStored, UserUpdate
from database import get_password_reset_tokens_db, get_profiles_db, get_users_db


def _to_dict(document: dict | None) -> dict | None:
    if document is None:
        return None
    return dict(document)


def create_user(
    *,
    email: str,
    hashed_password: str,
    role: UserRoleEnum = UserRoleEnum.user,
    is_active: bool = True,
    profile_name: str | None = None,
    profile_phone: str | None = None,
    profile_address: str | None = None,
) -> tuple[dict, dict]:
    user = UserStored(
        email=email.lower(),
        hashed_password=hashed_password,
        role=role,
        is_active=is_active,
    )
    users_db = get_users_db()
    users_db.insert(user.model_dump(mode="json"))

    profile = ProfileStored(
        user_id=user.id,
        name=profile_name,
        phone=profile_phone,
        address=profile_address,
    )
    profiles_db = get_profiles_db()
    profiles_db.insert(profile.model_dump(mode="json"))

    return user.model_dump(mode="json"), profile.model_dump(mode="json")


def get_user_by_id(user_id: str) -> dict | None:
    users_db = get_users_db()
    query = Query()
    return _to_dict(users_db.get(query.id == user_id))


def get_user_by_email(email: str) -> dict | None:
    users_db = get_users_db()
    query = Query()
    return _to_dict(users_db.get(query.email == email.lower()))


def list_users() -> list[dict]:
    users_db = get_users_db()
    return [dict(item) for item in users_db.all()]


def update_user(user_id: str, payload: UserUpdate, *, hashed_password: str | None = None) -> dict | None:
    users_db = get_users_db()
    query = Query()
    existing = users_db.get(query.id == user_id)
    if existing is None:
        return None

    updates: dict[str, str | bool] = {}
    if payload.email is not None:
        updates["email"] = payload.email.lower()
    if payload.role is not None:
        updates["role"] = payload.role.value
    if payload.is_active is not None:
        updates["is_active"] = payload.is_active
    if hashed_password is not None:
        updates["hashed_password"] = hashed_password

    if updates:
        users_db.update(updates, query.id == user_id)

    return _to_dict(users_db.get(query.id == user_id))


def delete_user(user_id: str) -> bool:
    users_db = get_users_db()
    profiles_db = get_profiles_db()
    query = Query()
    user_exists = users_db.contains(query.id == user_id)
    if not user_exists:
        return False

    users_db.remove(query.id == user_id)
    profiles_db.remove(query.user_id == user_id)
    return True


def get_profile_by_user_id(user_id: str) -> dict | None:
    profiles_db = get_profiles_db()
    query = Query()
    return _to_dict(profiles_db.get(query.user_id == user_id))


def update_profile_by_user_id(user_id: str, payload: ProfileUpdate) -> dict:
    profiles_db = get_profiles_db()
    query = Query()
    existing = profiles_db.get(query.user_id == user_id)

    if existing is None:
        new_profile = ProfileStored(
            user_id=user_id,
            name=payload.name,
            phone=payload.phone,
            address=payload.address,
        )
        profiles_db.insert(new_profile.model_dump(mode="json"))
        return new_profile.model_dump(mode="json")

    updates: dict[str, str | None] = {}
    if payload.name is not None:
        updates["name"] = payload.name
    if payload.phone is not None:
        updates["phone"] = payload.phone
    if payload.address is not None:
        updates["address"] = payload.address

    if updates:
        profiles_db.update(updates, query.user_id == user_id)

    return _to_dict(profiles_db.get(query.user_id == user_id)) or dict(existing)


def create_password_reset_token_record(*, token_id: str, user_id: str, expires_at: datetime) -> None:
    tokens_db = get_password_reset_tokens_db()
    tokens_db.insert(
        {
            "token_id": token_id,
            "user_id": user_id,
            "expires_at": expires_at.isoformat(),
            "used_at": None,
        }
    )


def consume_password_reset_token(*, token_id: str, user_id: str) -> bool:
    tokens_db = get_password_reset_tokens_db()
    query = Query()
    record = tokens_db.get((query.token_id == token_id) & (query.user_id == user_id))
    if record is None or record.get("used_at") is not None:
        return False

    tokens_db.update(
        {"used_at": datetime.now(timezone.utc).isoformat()},
        (query.token_id == token_id) & (query.user_id == user_id),
    )
    return True
