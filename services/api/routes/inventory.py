from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlmodel import Session, func, select

from cache import cached, invalidate_cache
from database import get_db
from models import Ingredient, IngredientEntry, IngredientExit
from schemas import (
    IngredientCreate,
    IngredientEntryCreate,
    IngredientEntryResponse,
    IngredientExitCreate,
    IngredientExitResponse,
    IngredientOrderEntry,
    IngredientResponse,
)
from security import get_current_user
from telemetry_util import emit_telemetry_event

router = APIRouter(
    prefix="/inventory",
    tags=["inventory"],
    dependencies=[Depends(get_current_user)],
)


# ---------------------------------------------------------------------------
# Función auxiliar: calcula el current_stock de un ingrediente
# ---------------------------------------------------------------------------
def _compute_current_stock(*, ingredient_id: int, db: Session) -> float:
    """Calcula el stock actual como suma de entradas menos suma de salidas."""
    total_entries = db.exec(
        select(func.coalesce(func.sum(IngredientEntry.quantity), 0.0)).where(
            IngredientEntry.ingredient_id == ingredient_id
        )
    ).one()

    total_exits = db.exec(
        select(func.coalesce(func.sum(IngredientExit.quantity), 0.0)).where(
            IngredientExit.ingredient_id == ingredient_id
        )
    ).one()

    return float(total_entries - total_exits)


def _build_ingredient_response(ingredient: Ingredient, db: Session) -> IngredientResponse:
    """Convierte un modelo Ingredient en IngredientResponse con current_stock calculado."""
    stock = _compute_current_stock(ingredient_id=ingredient.id, db=db)  # type: ignore[arg-type]
    return IngredientResponse(
        id=ingredient.id,  # type: ignore[arg-type]
        name=ingredient.name,
        sku=ingredient.sku,
        unit=ingredient.unit,
        category=ingredient.category,
        country=ingredient.country,
        current_stock=stock,
    )


# ============================================================================
# GET /inventory/products — Lista todos los ingredientes con stock
# ============================================================================


@router.get("/products", response_model=list[IngredientResponse])
@cached(ttl_seconds=30.0)  # TTL 30s: el stock solo cambia con entradas/salidas, no en cada consulta
def list_products(
    request: Request,
    country: str | None = Query(default=None, description="Filtrar por país: CO o US"),
    db: Session = Depends(get_db),
) -> list[IngredientResponse]:
    """Lista todos los ingredientes con su current_stock calculado."""
    query = select(Ingredient)
    if country:
        query = query.where(Ingredient.country == country)
    ingredients = db.exec(query).all()
    return [_build_ingredient_response(ing, db) for ing in ingredients]


# ============================================================================
# POST /inventory/products — Crea un nuevo ingrediente
# ============================================================================


@router.post("/products", response_model=IngredientResponse, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: IngredientCreate,
    db: Session = Depends(get_db),
) -> IngredientResponse:
    """Crea un nuevo ingrediente. El stock inicial es 0 automáticamente."""
    ingredient = Ingredient(**payload.model_dump())
    db.add(ingredient)
    db.commit()
    db.refresh(ingredient)
    invalidate_cache("/inventory/products")
    return _build_ingredient_response(ingredient, db)


# ============================================================================
# GET /inventory/products/{id} — Obtiene un ingrediente con su stock
# ============================================================================


@router.get("/products/{ingredient_id}", response_model=IngredientResponse)
@cached(ttl_seconds=30.0)  # TTL 30s: mismo criterio que list_products
def get_product(
    request: Request,
    ingredient_id: int,
    db: Session = Depends(get_db),
) -> IngredientResponse:
    """Obtiene un ingrediente por ID con su current_stock calculado."""
    ingredient = db.get(Ingredient, ingredient_id)
    if ingredient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ingredient with id {ingredient_id} not found",
        )
    return _build_ingredient_response(ingredient, db)


# ============================================================================
# POST /inventory/orders/inbound — Registra una entrada (entrega de proveedor)
# ============================================================================


@router.post("/orders/inbound", response_model=IngredientEntryResponse, status_code=status.HTTP_201_CREATED)
def create_inbound_order(
    payload: IngredientEntryCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IngredientEntryResponse:
    """Registra una entrega de ingrediente recibida de un proveedor.

    El user_uuid se inyecta automáticamente desde el usuario autenticado (TinyDB).
    """
    # Verificar que el ingrediente existe
    ingredient = db.get(Ingredient, payload.ingredient_id)
    if ingredient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ingredient with id {payload.ingredient_id} not found",
        )

    entry = IngredientEntry(
        **payload.model_dump(),
        user_uuid=current_user["id"],
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    invalidate_cache("/inventory/products")
    invalidate_cache("/inventory/orders")

    # Emitir telemetría
    country = ingredient.country
    emit_telemetry_event(
        "inbound_order_created",
        user_id=current_user["id"],
        properties={
            "location_id": payload.location_id,
            "country": country,
            "product_id": payload.ingredient_id,
            "product_category": ingredient.category,
            "quantity": payload.quantity,
            "unit": ingredient.unit,
            "currency": "USD" if country == "US" else "COP",
            "supplier_name": payload.supplier_name,
        },
    )

    return IngredientEntryResponse(
        id=entry.id,  # type: ignore[arg-type]
        ingredient_id=entry.ingredient_id,
        quantity=entry.quantity,
        supplier_name=entry.supplier_name,
        location_id=entry.location_id,
        created_at=entry.created_at,
        user_uuid=entry.user_uuid,
    )


# ============================================================================
# POST /inventory/orders/outbound — Registra una salida (consumo o merma)
# ============================================================================


@router.post("/orders/outbound", response_model=IngredientExitResponse, status_code=status.HTTP_201_CREATED)
def create_outbound_order(
    payload: IngredientExitCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IngredientExitResponse:
    """Registra un consumo o merma de ingrediente.

    Valida que el motivo sea "consumption" o "waste" y que el stock
    resultante no sea negativo. El user_uuid se inyecta automáticamente
    desde el usuario autenticado (TinyDB).
    """
    # Validar reason
    if payload.reason not in ("consumption", "waste"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid reason '{payload.reason}'. Must be 'consumption' or 'waste'.",
        )

    # Verificar que el ingrediente existe
    ingredient = db.get(Ingredient, payload.ingredient_id)
    if ingredient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ingredient with id {payload.ingredient_id} not found",
        )

    # Validar stock suficiente
    current_stock = _compute_current_stock(ingredient_id=payload.ingredient_id, db=db)
    if current_stock < payload.quantity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Insufficient stock for ingredient '{ingredient.name}'. "
                f"Available: {current_stock}, requested: {payload.quantity}."
            ),
        )

    exit_record = IngredientExit(
        **payload.model_dump(),
        user_uuid=current_user["id"],
    )
    db.add(exit_record)
    db.commit()
    db.refresh(exit_record)
    invalidate_cache("/inventory/products")
    invalidate_cache("/inventory/orders")

    # Emitir telemetría
    country = ingredient.country
    event_type = "stock_waste_registered" if payload.reason == "waste" else "outbound_order_created"
    telemetry_props: dict[str, object] = {
        "location_id": payload.location_id,
        "country": country,
        "product_id": payload.ingredient_id,
        "product_category": ingredient.category,
        "quantity": payload.quantity,
        "unit": ingredient.unit,
        "currency": "USD" if country == "US" else "COP",
    }
    if payload.reason == "waste":
        telemetry_props["reason"] = "kitchen_error"  # default; backend podría recibir razón real

    emit_telemetry_event(
        event_type,
        user_id=current_user["id"],
        properties=telemetry_props,
    )

    # Verificar umbral mínimo de stock
    threshold_min = 10  # umbral por defecto; podría ser configurable por producto
    new_stock = _compute_current_stock(ingredient_id=payload.ingredient_id, db=db)
    if new_stock < threshold_min:
        emit_telemetry_event(
            "stock_threshold_triggered",
            user_id=current_user["id"],
            properties={
                "location_id": payload.location_id,
                "country": country,
                "product_id": payload.ingredient_id,
                "product_category": ingredient.category,
                "current_stock": new_stock,
                "threshold_min": threshold_min,
                "unit": ingredient.unit,
                "currency": "USD" if country == "US" else "COP",
            },
        )

    return IngredientExitResponse(
        id=exit_record.id,  # type: ignore[arg-type]
        ingredient_id=exit_record.ingredient_id,
        quantity=exit_record.quantity,
        reason=exit_record.reason,
        location_id=exit_record.location_id,
        created_at=exit_record.created_at,
        user_uuid=exit_record.user_uuid,
    )


# ============================================================================
# GET /inventory/orders — Lista todas las entradas y salidas
# ============================================================================


@router.get("/orders", response_model=list[IngredientOrderEntry])
@cached(ttl_seconds=30.0)  # TTL 30s: las órdenes cambian con entradas/salidas
def list_orders(
    request: Request,
    ingredient_id: int | None = Query(default=None, description="Filtrar por ingrediente"),
    db: Session = Depends(get_db),
) -> list[IngredientOrderEntry]:
    """Lista todas las entradas y salidas con datos del ingrediente asociado."""
    results: list[IngredientOrderEntry] = []

    # Consultar entradas
    entries_query = select(IngredientEntry)
    if ingredient_id is not None:
        entries_query = entries_query.where(IngredientEntry.ingredient_id == ingredient_id)
    entries = db.exec(entries_query).all()

    for entry in entries:
        ing = db.get(Ingredient, entry.ingredient_id)
        results.append(
            IngredientOrderEntry(
                id=entry.id,  # type: ignore[arg-type]
                type="entry",
                ingredient_id=entry.ingredient_id,
                ingredient_name=ing.name if ing else "Unknown",
                ingredient_sku=ing.sku if ing else "Unknown",
                quantity=entry.quantity,
                supplier_name=entry.supplier_name,
                reason=None,
                location_id=entry.location_id,
                created_at=entry.created_at,
                user_uuid=entry.user_uuid,
            )
        )

    # Consultar salidas
    exits_query = select(IngredientExit)
    if ingredient_id is not None:
        exits_query = exits_query.where(IngredientExit.ingredient_id == ingredient_id)
    exits = db.exec(exits_query).all()

    for exit_record in exits:
        ing = db.get(Ingredient, exit_record.ingredient_id)
        results.append(
            IngredientOrderEntry(
                id=exit_record.id,  # type: ignore[arg-type]
                type="exit",
                ingredient_id=exit_record.ingredient_id,
                ingredient_name=ing.name if ing else "Unknown",
                ingredient_sku=ing.sku if ing else "Unknown",
                quantity=exit_record.quantity,
                supplier_name=None,
                reason=exit_record.reason,
                location_id=exit_record.location_id,
                created_at=exit_record.created_at,
                user_uuid=exit_record.user_uuid,
            )
        )

    # Ordenar por created_at descendente (más reciente primero)
    results.sort(key=lambda r: r.created_at, reverse=True)

    return results