# Supplier Directory API

FastAPI + TinyDB + Pydantic API para el directorio de proveedores de Brasaland.

## Ejecutar

```bash
cd apps/supplier-directory-api
uv sync
uv run seed
uv run uvicorn app.main:app --reload --port 8000
```

## Endpoints

- `POST /supplier`
- `GET /suppliers?country=Colombia&category=carne`
- `GET /suppliers/{id}`
- `PATCH /suppliers/{id}/rate`
- `PATCH /sppliers/{id}/rate` (alias para compatibilidad con typo)
- `PATCH /suppliers/{id}/status`
- `DELETE /suppliers/{id}`
