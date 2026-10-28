from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session, select

from database import _get_engine, init_db
from models import Ingredient, IngredientEntry, IngredientExit

# ============================================================================
# Datos semilla para el inventario de Brasaland
# ============================================================================

# --- Ingredients (mínimo 6) ---
INGREDIENTS_SEED = [
    {"name": "Falda de ternera", "sku": "BRS-BEEF-001", "unit": "kg", "category": "meat", "country": "CO"},
    {"name": "Costilla de cerdo", "sku": "BRS-PORK-001", "unit": "kg", "category": "meat", "country": "US"},
    {"name": "Chimichurri", "sku": "BRS-SAUCE-001", "unit": "litro", "category": "sauce", "country": "CO"},
    {"name": "Salsa BBQ de la casa", "sku": "BRS-SAUCE-002", "unit": "litro", "category": "sauce", "country": "US"},
    {"name": "Yuca", "sku": "BRS-PROD-001", "unit": "kg", "category": "produce", "country": "CO"},
    {"name": "Caja para llevar (M)", "sku": "BRS-PKG-001", "unit": "unidad", "category": "packaging", "country": "CO"},
]

# --- IngredientEntries (mínimo 4) ---
# 2 entregas para BRS-BEEF-001, 1 para BRS-SAUCE-001, 1 para BRS-PROD-001
ENTRIES_SEED = [
    {"sku": "BRS-BEEF-001", "quantity": 50.0, "supplier_name": "Carnes del Valle S.A.", "location_id": 1, "user_uuid": "seed-system"},
    {"sku": "BRS-BEEF-001", "quantity": 30.0, "supplier_name": "Carnes del Valle S.A.", "location_id": 3, "user_uuid": "seed-system"},
    {"sku": "BRS-SAUCE-001", "quantity": 20.0, "supplier_name": "Salsas Artesanales Ltda.", "location_id": 1, "user_uuid": "seed-system"},
    {"sku": "BRS-PROD-001", "quantity": 100.0, "supplier_name": "Mercado Mayorista Medellín", "location_id": 2, "user_uuid": "seed-system"},
]

# --- IngredientExits (mínimo 3) ---
# 2 consumos + 1 merma, que no dejen stock en cero
EXITS_SEED = [
    {"sku": "BRS-BEEF-001", "quantity": 10.0, "reason": "consumption", "location_id": 1, "user_uuid": "seed-system"},
    {"sku": "BRS-SAUCE-001", "quantity": 3.0, "reason": "consumption", "location_id": 1, "user_uuid": "seed-system"},
    {"sku": "BRS-PROD-001", "quantity": 5.0, "reason": "waste", "location_id": 2, "user_uuid": "seed-system"},
]


def _get_sku_to_id(session: Session) -> dict[str, int]:
    """Construye un mapa {sku: id} desde la tabla Ingredient."""
    ingredients = session.exec(select(Ingredient)).all()
    return {ing.sku: ing.id for ing in ingredients}  # type: ignore[return-value]


def seed_inventory() -> tuple[int, int, int]:
    """Inserta los datos semilla de inventario en Supabase.

    Returns:
        (ingredients_insertados, entries_insertados, exits_insertados)
    """
    # Inicializar tablas por si no existen
    init_db()

    ingredients_count = 0
    entries_count = 0
    exits_count = 0

    with Session(_get_engine()) as session:
        # ---- Ingredients ----
        existing_skus = set(session.exec(select(Ingredient.sku)).all())

        for data in INGREDIENTS_SEED:
            if data["sku"] in existing_skus:
                continue
            ingredient = Ingredient(**data)
            session.add(ingredient)
            ingredients_count += 1

        session.commit()

        # ---- Entries / Exits (solo si el seed del sistema no se ha aplicado aún) ----
        # Marcamos las filas con user_uuid = "seed-system". Si ya existe al
        # menos una entrada con ese marcador, saltamos todas las entradas y
        # salidas del seed para evitar duplicados en ejecuciones sucesivas.
        existing_seed_entries = session.exec(
            select(IngredientEntry).where(IngredientEntry.user_uuid == "seed-system").limit(1)
        ).first()

        if existing_seed_entries is None:
            sku_to_id = _get_sku_to_id(session)

            for data in ENTRIES_SEED:
                ingredient_id = sku_to_id.get(data["sku"])
                if ingredient_id is None:
                    print(f"  [WARN] SKU '{data['sku']}' no encontrado, saltando entry.")
                    continue

                entry = IngredientEntry(
                    ingredient_id=ingredient_id,
                    quantity=data["quantity"],
                    supplier_name=data["supplier_name"],
                    location_id=data["location_id"],
                    created_at=datetime.now(timezone.utc),
                    user_uuid=data["user_uuid"],
                )
                session.add(entry)
                entries_count += 1

            session.commit()

            # ---- Exits ----
            for data in EXITS_SEED:
                ingredient_id = sku_to_id.get(data["sku"])
                if ingredient_id is None:
                    print(f"  [WARN] SKU '{data['sku']}' no encontrado, saltando exit.")
                    continue

                exit_record = IngredientExit(
                    ingredient_id=ingredient_id,
                    quantity=data["quantity"],
                    reason=data["reason"],
                    location_id=data["location_id"],
                    created_at=datetime.now(timezone.utc),
                    user_uuid=data["user_uuid"],
                )
                session.add(exit_record)
                exits_count += 1

            session.commit()
        else:
            print("  [SKIP] Seed entries/exits ya aplicados (user_uuid='seed-system' detectado).")

    return ingredients_count, entries_count, exits_count


def print_report(ingredients: int, entries: int, exits: int) -> None:
    """Imprime un resumen formateado del seed de inventario."""
    print("\n=== Seed de Inventario (Supabase) ===")
    print(f"  Ingredients insertados:  {ingredients}")
    print(f"  Entries insertados:      {entries}")
    print(f"  Exits insertados:        {exits}")
    print("=====================================\n")


def main() -> None:
    """Ejecuta el seed de inventario de forma independiente."""
    result = seed_inventory()
    print_report(*result)


if __name__ == "__main__":
    main()