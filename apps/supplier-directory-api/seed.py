from __future__ import annotations

from app.services.suppliers_service import seed_suppliers


def main() -> None:
    inserted, skipped = seed_suppliers()
    print(f"Seeder completado. Insertados: {inserted}. Omitidos por duplicado: {skipped}.")


if __name__ == "__main__":
    main()
