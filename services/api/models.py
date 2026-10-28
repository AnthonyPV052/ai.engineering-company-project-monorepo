from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Self

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from sqlmodel import Field as SQLModelField, SQLModel

VALID_CATEGORIES = [
    "carne",
    "verduras_y_hortalizas",
    "salsas_y_condimentos",
    "bebidas",
    "packaging",
    "productos_limpieza",
    "lacteos",
    "carbon_y_combustible",
]

VALID_STATUSES = ["active", "suspended"]

COUNTRY_TO_CURRENCY = {
    "Colombia": "COP",
    "USA": "USD",
}


class CountryEnum(str, Enum):
    colombia = "Colombia"
    usa = "USA"


class CurrencyEnum(str, Enum):
    cop = "COP"
    usd = "USD"


class SupplierStatusEnum(str, Enum):
    active = "active"
    suspended = "suspended"


class SupplierCreate(BaseModel):
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
        cleaned = [item.strip() for item in value if item.strip()]
        if not cleaned:
            raise ValueError("categories debe contener al menos una categoría válida")

        invalid = [item for item in cleaned if item not in VALID_CATEGORIES]
        if invalid:
            raise ValueError(
                f"Categorías inválidas: {', '.join(invalid)}. Permitidas: {', '.join(VALID_CATEGORIES)}"
            )
        return cleaned

    @model_validator(mode="after")
    def validate_currency_per_country(self) -> Self:
        expected = COUNTRY_TO_CURRENCY[self.country.value]
        if self.currency.value != expected:
            raise ValueError(
                f"La moneda '{self.currency.value}' no corresponde al país '{self.country.value}'. "
                f"Se esperaba '{expected}'."
            )
        return self


class SupplierRatePatch(BaseModel):
    rate_per_unit: float = Field(gt=0)


class SupplierStatusPatch(BaseModel):
    status: SupplierStatusEnum


class SupplierStored(SupplierCreate):
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SupplierListItem(BaseModel):
    """Versión ligera para listados de proveedores.

    Omite campos internos o pesados (contact_email, notes, updated_at)
    que no son necesarios en una vista de lista.
    """

    id: int
    name: str
    country: CountryEnum
    categories: list[str]
    rate_per_unit: float
    currency: CurrencyEnum
    status: SupplierStatusEnum


class SupplierResponse(SupplierCreate):
    id: int
    updated_at: datetime


# ============================================================================
# Modelos SQLModel (tablas en Supabase / PostgreSQL)
# ============================================================================


class Ingredient(SQLModel, table=True):
    """Ingrediente / producto del inventario."""

    __tablename__ = "ingredient"

    id: int | None = SQLModelField(default=None, primary_key=True)
    name: str = SQLModelField(nullable=False)
    sku: str = SQLModelField(nullable=False, unique=True, index=True)
    unit: str = SQLModelField(nullable=False)
    category: str = SQLModelField(nullable=False)
    country: str = SQLModelField(nullable=False)


class IngredientEntry(SQLModel, table=True):
    """Entrega de ingredientes recibida de un proveedor."""

    __tablename__ = "ingrediententry"

    id: int | None = SQLModelField(default=None, primary_key=True)
    ingredient_id: int = SQLModelField(foreign_key="ingredient.id", nullable=False)
    quantity: float = SQLModelField(nullable=False)
    supplier_name: str = SQLModelField(nullable=False)
    location_id: int = SQLModelField(nullable=False)
    created_at: datetime = SQLModelField(
        default_factory=lambda: datetime.now(timezone.utc), nullable=False
    )
    # user_uuid referencia al usuario en TinyDB (sin FK ni tabla de usuarios en SQL)
    user_uuid: str = SQLModelField(nullable=False)


class IngredientExit(SQLModel, table=True):
    """Registro de consumo o merma de ingredientes."""

    __tablename__ = "ingredientexit"

    id: int | None = SQLModelField(default=None, primary_key=True)
    ingredient_id: int = SQLModelField(foreign_key="ingredient.id", nullable=False)
    quantity: float = SQLModelField(nullable=False)
    reason: str = SQLModelField(nullable=False)
    location_id: int = SQLModelField(nullable=False)
    created_at: datetime = SQLModelField(
        default_factory=lambda: datetime.now(timezone.utc), nullable=False
    )
    # user_uuid referencia al usuario en TinyDB (sin FK ni tabla de usuarios en SQL)
    user_uuid: str = SQLModelField(nullable=False)
