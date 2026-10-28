from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.models import (
    CountryEnum,
    SupplierCreate,
    SupplierRateUpdate,
    SupplierResponse,
    SupplierStatusUpdate,
)
from app.services.suppliers_service import (
    create_supplier,
    delete_supplier,
    get_supplier_by_id,
    list_suppliers,
    update_supplier_rate,
    update_supplier_status,
)

app = FastAPI(title="Brasaland Supplier Directory API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:4011",
        "http://127.0.0.1:4011",
    ],
    allow_origin_regex=r"https://.*\.(github\.dev|app\.github\.dev)$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/supplier", response_model=SupplierResponse, status_code=201)
def create_supplier_endpoint(payload: SupplierCreate) -> SupplierResponse:
    return create_supplier(payload)


@app.get("/suppliers", response_model=list[SupplierResponse])
def list_suppliers_endpoint(
    country: CountryEnum | None = Query(default=None),
    category: str | None = Query(default=None),
) -> list[SupplierResponse]:
    return list_suppliers(
        country=country.value if country else None,
        category=category,
    )


@app.get("/suppliers/{supplier_id}", response_model=SupplierResponse)
def get_supplier_endpoint(supplier_id: int) -> SupplierResponse:
    supplier = get_supplier_by_id(supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return supplier


@app.patch("/suppliers/{supplier_id}/rate", response_model=SupplierResponse)
@app.patch("/sppliers/{supplier_id}/rate", response_model=SupplierResponse)
def update_rate_endpoint(supplier_id: int, payload: SupplierRateUpdate) -> SupplierResponse:
    supplier = update_supplier_rate(supplier_id, payload)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return supplier


@app.patch("/suppliers/{supplier_id}/status", response_model=SupplierResponse)
def update_status_endpoint(supplier_id: int, payload: SupplierStatusUpdate) -> SupplierResponse:
    supplier = update_supplier_status(supplier_id, payload)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return supplier


@app.delete("/suppliers/{supplier_id}")
def delete_supplier_endpoint(supplier_id: int) -> dict[str, str]:
    deleted = delete_supplier(supplier_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return {"message": "Supplier deleted"}
