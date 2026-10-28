from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

# ============================================================================
# Schema genérico de mensaje
# ============================================================================


class MessageResponse(BaseModel):
    """Respuesta genérica para endpoints que solo devuelven un mensaje."""

    message: str


# ============================================================================
# Schemas de Ingredient
# ============================================================================


class IngredientCreate(BaseModel):
    """Schema de request para crear un nuevo ingrediente."""

    name: str = Field(min_length=1, description="Nombre del ingrediente")
    sku: str = Field(min_length=1, description="Código interno único, ej. BRS-BEEF-001")
    unit: str = Field(min_length=1, description="Unidad de medida: kg, litro, unidad")
    category: str = Field(min_length=1, description="meat, produce, sauce, beverage, packaging, cleaning")
    country: str = Field(min_length=2, max_length=2, description="CO (Colombia) o US (EE.UU.)")


class IngredientResponse(BaseModel):
    """Schema de respuesta para un ingrediente, incluye current_stock calculado."""

    id: int
    name: str
    sku: str
    unit: str
    category: str
    country: str
    current_stock: float = Field(
        description="Stock actual calculado: suma entradas − suma salidas (no almacenado)"
    )


# ============================================================================
# Schemas de IngredientEntry (entrada / entrega de proveedor)
# ============================================================================


class IngredientEntryCreate(BaseModel):
    """Schema de request para registrar una entrega de ingrediente.

    El campo user_uuid se inyecta automáticamente desde el token JWT.
    """

    ingredient_id: int = Field(gt=0, description="ID del ingrediente (FK)")
    quantity: float = Field(gt=0, description="Cantidad recibida en la unidad del ingrediente")
    supplier_name: str = Field(min_length=1, description="Nombre del proveedor")
    location_id: int = Field(ge=1, le=14, description="Local receptor (1–14)")


class IngredientEntryResponse(BaseModel):
    """Schema de respuesta para una entrega registrada."""

    id: int
    ingredient_id: int
    quantity: float
    supplier_name: str
    location_id: int
    created_at: datetime
    user_uuid: str


# ============================================================================
# Schemas de IngredientExit (salida / consumo o merma)
# ============================================================================


class IngredientExitCreate(BaseModel):
    """Schema de request para registrar un consumo o merma.

    El campo user_uuid se inyecta automáticamente desde el token JWT.
    """

    ingredient_id: int = Field(gt=0, description="ID del ingrediente (FK)")
    quantity: float = Field(gt=0, description="Cantidad consumida o mermada")
    reason: str = Field(
        min_length=1,
        description='Motivo: "consumption" (consumo) o "waste" (merma)',
    )
    location_id: int = Field(ge=1, le=14, description="Local donde ocurrió la salida (1–14)")


class IngredientExitResponse(BaseModel):
    """Schema de respuesta para una salida registrada."""

    id: int
    ingredient_id: int
    quantity: float
    reason: str
    location_id: int
    created_at: datetime
    user_uuid: str


# ============================================================================
# Schema combinado para el listado de órdenes (GET /inventory/orders)
# ============================================================================


class IngredientOrderEntry(BaseModel):
    """Orden de entrada con datos del ingrediente asociado."""

    id: int
    type: str = Field(description='"entry" para entrada, "exit" para salida')
    ingredient_id: int
    ingredient_name: str
    ingredient_sku: str
    quantity: float
    supplier_name: str | None = Field(default=None, description="Solo para entradas")
    reason: str | None = Field(default=None, description="Solo para salidas: consumption o waste")
    location_id: int
    created_at: datetime
    user_uuid: str