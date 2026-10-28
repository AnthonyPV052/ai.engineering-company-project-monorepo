#!/usr/bin/env python3
"""Seeder mejorado que genera un volumen realista de datos en Supabase.

Genera:
  - 25 ingredientes con categorías, países y SKUs variados
  - 200 entradas (ingredient_entries) distribuidas en 14 locaciones
  - 150 salidas (ingredient_exits) de consumo/merma

Esto permite que las consultas de inventario (especialmente _compute_current_stock
y list_products) tengan un coste real medible por el middleware de timing.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from random import choice, gauss, randint, seed as set_seed
from typing import Any

from sqlmodel import Session, select

# Asegurar que podemos importar desde services/api
ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "services" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from database import _get_engine, init_db  # noqa: E402
from models import Ingredient, IngredientEntry, IngredientExit  # noqa: E402

set_seed(42)

CATEGORIES = ["meat", "sauce", "produce", "packaging", "cleaning", "beverage"]
COUNTRIES = ["CO", "US"]
UNITS = {"meat": "kg", "sauce": "litro", "produce": "kg", "packaging": "unidad", "cleaning": "litro", "beverage": "litro"}

SUPPLIERS_CO = [
    "Carnes del Valle S.A.S.", "Frigorífico Antioqueño", "Verduras La Cosecha",
    "Condimentos El Sabor", "Distribuidora RefriCol", "Empaques y Más",
    "Limpiahogar Profesional", "CarboCo", "Bebidas Andinas",
    "Lácteos El Porvenir", "Avícola del Monte", "Mariscos del Pacífico",
    "Aceites y Grasas Unidas", "Panadería Industrial Medellín",
    "Frutas Selectas SAS",
]
SUPPLIERS_US = [
    "Miami Meat Distributors LLC", "Sunshine Produce FL", "Latin Flavors Inc.",
    "PackRight USA", "CleanPro Florida", "GrillFuel Supply Co.",
    "American Spices Co.", "Fresh Catch Miami",
    "Premium Dairy FL", "EcoPack Solutions",
]

INGREDIENT_NAMES_CO = [
    ("Falda de ternera", "BRS-BEEF-001", "meat", "CO"),
    ("Chimichurri clásico", "BRS-SAUCE-001", "sauce", "CO"),
    ("Yuca", "BRS-PROD-001", "produce", "CO"),
    ("Caja para llevar (M)", "BRS-PKG-001", "packaging", "CO"),
    ("Desinfectante multiusos", "BRS-CLN-001", "cleaning", "CO"),
    ("Costilla de cerdo", "BRS-PORK-001", "meat", "CO"),
    ("Lomo de res", "BRS-BEEF-002", "meat", "CO"),
    ("Pechuga de pollo", "BRS-POUL-001", "meat", "CO"),
    ("Salsa de tomate brava", "BRS-SAUCE-002", "sauce", "CO"),
    ("Guacamole preparado", "BRS-SAUCE-003", "sauce", "CO"),
    ("Papas criollas", "BRS-PROD-002", "produce", "CO"),
    ("Cebolla cabezona", "BRS-PROD-003", "produce", "CO"),
    ("Tomate chonto", "BRS-PROD-004", "produce", "CO"),
    ("Leche entera", "BRS-DAIRY-001", "beverage", "CO"),
    ("Gaseosa colombiana", "BRS-BEV-001", "beverage", "CO"),
]
INGREDIENT_NAMES_US = [
    ("BBQ Sauce House Special", "BRS-BBQ-001", "sauce", "US"),
    ("Wagyu Brisket", "BRS-BEEF-010", "meat", "US"),
    ("Pulled Pork Shoulder", "BRS-PORK-010", "meat", "US"),
    ("Coleslaw Mix", "BRS-PROD-010", "produce", "US"),
    ("Takeout Box (L)", "BRS-PKG-010", "packaging", "US"),
    ("Industrial Degreaser", "BRS-CLN-010", "cleaning", "US"),
    ("Corn on the Cob", "BRS-PROD-011", "produce", "US"),
    ("Sweet Potato Fries", "BRS-PROD-012", "produce", "US"),
    ("American Cheese Slices", "BRS-DAIRY-010", "beverage", "US"),
    ("Craft Soda Assorted", "BRS-BEV-010", "beverage", "US"),
]

LOCATIONS = list(range(1, 15))  # 14 locaciones


def _generate_entries(sku_id_map: dict[str, int], count: int = 200) -> list[dict[str, Any]]:
    """Genera entradas de stock con fechas y cantidades realistas."""
    entries: list[dict[str, Any]] = []
    base_date = datetime(2025, 1, 1, tzinfo=timezone.utc)

    for i in range(count):
        sku = choice(list(sku_id_map.keys()))
        ingredient_id = sku_id_map[sku]
        quantity = round(gauss(50, 15), 1)
        if quantity < 1:
            quantity = 10.0
        supplier = choice(SUPPLIERS_CO if "BRS-" in sku and sku_id_map[sku] % 2 == 0 else SUPPLIERS_US)
        location = choice(LOCATIONS)
        days_offset = randint(0, 600) + i // 3  # distribuir en ~20 meses
        created_at = base_date + timedelta(days=days_offset, hours=randint(6, 18))

        entries.append({
            "ingredient_id": ingredient_id,
            "quantity": quantity,
            "supplier_name": supplier,
            "location_id": location,
            "created_at": created_at,
            "user_uuid": "seed-system",
        })
    return entries


def _generate_exits(sku_id_map: dict[str, int], count: int = 150) -> list[dict[str, Any]]:
    """Genera consumos y mermas, procurando no dejar stock en cero (aleatorio)."""
    exits: list[dict[str, Any]] = []
    base_date = datetime(2025, 1, 15, tzinfo=timezone.utc)

    # Rastreamos stock aproximado para evitar dejar en cero
    approx_stock: dict[int, float] = {}

    for i in range(count):
        sku = choice(list(sku_id_map.keys()))
        ingredient_id = sku_id_map[sku]

        current_approx = approx_stock.get(ingredient_id, 100.0)
        # Entre 10% y 60% del stock aproximado
        ratio = gauss(0.3, 0.1)
        ratio = max(0.1, min(0.6, ratio))
        quantity = round(current_approx * ratio, 1)
        if quantity < 0.5:
            quantity = 1.0

        reason = "consumption" if randint(0, 9) > 0 else "waste"  # ~10% waste

        location = choice(LOCATIONS)
        days_offset = randint(0, 600) + i // 3
        created_at = base_date + timedelta(days=days_offset, hours=randint(7, 23))

        # Actualizar stock aproximado (se compensa con entradas posteriores)
        approx_stock[ingredient_id] = current_approx - quantity * 0.7 + 5

        exits.append({
            "ingredient_id": ingredient_id,
            "quantity": quantity,
            "reason": reason,
            "location_id": location,
            "created_at": created_at,
            "user_uuid": "seed-system",
        })
    return exits


def seed_heavy_inventory() -> tuple[int, int, int]:
    """Inserta volumen realista de datos en Supabase.

    Returns:
        (ingredients, entries, exits) — conteos de filas insertadas.
    """
    init_db()

    ingredients_count = 0
    entries_count = 0
    exits_count = 0

    all_ingredient_defs = INGREDIENT_NAMES_CO + INGREDIENT_NAMES_US

    with Session(_get_engine()) as session:
        # ---- Ingredients ----
        existing_skus = set(session.exec(select(Ingredient.sku)).all())

        for name, sku, category, country in all_ingredient_defs:
            if sku in existing_skus:
                continue
            ingredient = Ingredient(
                name=name, sku=sku, unit=UNITS[category],
                category=category, country=country,
            )
            session.add(ingredient)
            ingredients_count += 1

        session.commit()

        # Mapa sku → id
        sku_id_map: dict[str, int] = {}
        for ing in session.exec(select(Ingredient)).all():
            if ing.sku:  # type: ignore[truthy-iterable]
                sku_id_map[ing.sku] = ing.id  # type: ignore[assignment]

        # ---- Verificar si ya hay seed pesado ----
        existing_seed_count = session.exec(
            select(IngredientEntry).where(IngredientEntry.user_uuid == "seed-system").limit(1)
        ).first()

        if existing_seed_count is not None:
            print("  [SKIP] Seed pesado ya aplicado (user_uuid='seed-system' detectado).")
            return 0, 0, 0

        # ---- Entries ----
        entries_data = _generate_entries(sku_id_map, count=200)
        for data in entries_data:
            entry = IngredientEntry(**data)
            session.add(entry)
            entries_count += 1

        session.commit()

        # ---- Exits ----
        exits_data = _generate_exits(sku_id_map, count=150)
        for data in exits_data:
            exit_rec = IngredientExit(**data)
            session.add(exit_rec)
            exits_count += 1

        session.commit()

    return ingredients_count, entries_count, exits_count


def print_report(ingredients: int, entries: int, exits: int) -> None:
    print("\n=== Seed Pesado de Inventario (Supabase) ===")
    print(f"  Ingredientes insertados:     {ingredients}")
    print(f"  Entries (entradas) insertadas: {entries}")
    print(f"  Exits (salidas) insertadas:   {exits}")
    print("============================================\n")


def main() -> None:
    result = seed_heavy_inventory()
    print_report(*result)


if __name__ == "__main__":
    main()