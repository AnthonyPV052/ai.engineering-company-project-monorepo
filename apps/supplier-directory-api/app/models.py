from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Self

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.config import COUNTRY_TO_CURRENCY, VALID_CATEGORIES


class CountryEnum(str, Enum):
    colombia = "Colombia"
    usa = "USA"


class CurrencyEnum(str, Enum):
    cop = "COP"
    usd = "USD"


class SupplierStatusEnum(str, Enum):
    active = "active"
    suspended = "suspended"


class SupplierBase(BaseModel):
    name: str = Field(min_length=1)
    country: CountryEnum
    categories: list[str] = Field(min_length=1)
    rate_per_unit: float = Field(gt=0)
    currency: CurrencyEnum
    status: SupplierStatusEnum
    contact_email: EmailStr | None = None
    notes: str | None = None

    @field_validator("categories")
    @classmethod
    def validate_categories(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if not normalized:
            raise ValueError("categories must contain at least one value")

        invalid = [item for item in normalized if item not in VALID_CATEGORIES]
        if invalid:
            raise ValueError(
                f"Invalid categories: {', '.join(invalid)}. Allowed: {', '.join(VALID_CATEGORIES)}"
            )

        return normalized

    @model_validator(mode="after")
    def validate_country_currency(self) -> Self:
        expected_currency = COUNTRY_TO_CURRENCY[self.country.value]
        if self.currency.value != expected_currency:
            raise ValueError(
                f"Currency '{self.currency.value}' is invalid for country '{self.country.value}'. "
                f"Expected '{expected_currency}'."
            )
        return self


class SupplierCreate(SupplierBase):
    pass


class SupplierResponse(SupplierBase):
    id: int
    updated_at: datetime


class SupplierRateUpdate(BaseModel):
    rate_per_unit: float = Field(gt=0)


class SupplierStatusUpdate(BaseModel):
    status: SupplierStatusEnum


class SupplierRecord(SupplierBase):
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
