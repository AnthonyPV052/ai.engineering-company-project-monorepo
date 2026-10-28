from __future__ import annotations

from datetime import datetime, timezone

from tinydb import Query

from app.db import get_db
from app.models import (
    SupplierCreate,
    SupplierRateUpdate,
    SupplierRecord,
    SupplierResponse,
    SupplierStatusUpdate,
)
from app.seeds import SUPPLIERS_SEED


def _to_response(doc_id: int, doc: dict) -> SupplierResponse:
    return SupplierResponse(id=doc_id, **doc)


def create_supplier(payload: SupplierCreate) -> SupplierResponse:
    db = get_db()
    record = SupplierRecord(**payload.model_dump())
    doc_id = db.insert(record.model_dump(mode="json"))
    created = db.get(doc_id=doc_id)
    return _to_response(doc_id, created)


def list_suppliers(country: str | None = None, category: str | None = None) -> list[SupplierResponse]:
    db = get_db()
    records = db.all()

    filtered: list[tuple[int, dict]] = []
    for doc in records:
        doc_id = doc.doc_id
        value = dict(doc)

        if country and value.get("country") != country:
            continue
        if category and category not in value.get("categories", []):
            continue
        filtered.append((doc_id, value))

    return [_to_response(doc_id, doc) for doc_id, doc in filtered]


def get_supplier_by_id(supplier_id: int) -> SupplierResponse | None:
    db = get_db()
    doc = db.get(doc_id=supplier_id)
    if doc is None:
        return None
    return _to_response(supplier_id, dict(doc))


def update_supplier_rate(supplier_id: int, payload: SupplierRateUpdate) -> SupplierResponse | None:
    db = get_db()
    doc = db.get(doc_id=supplier_id)
    if doc is None:
        return None

    updates = {
        "rate_per_unit": payload.rate_per_unit,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    db.update(updates, doc_ids=[supplier_id])
    updated = db.get(doc_id=supplier_id)
    return _to_response(supplier_id, dict(updated))


def update_supplier_status(supplier_id: int, payload: SupplierStatusUpdate) -> SupplierResponse | None:
    db = get_db()
    doc = db.get(doc_id=supplier_id)
    if doc is None:
        return None

    db.update({"status": payload.status.value}, doc_ids=[supplier_id])
    updated = db.get(doc_id=supplier_id)
    return _to_response(supplier_id, dict(updated))


def delete_supplier(supplier_id: int) -> bool:
    db = get_db()
    doc = db.get(doc_id=supplier_id)
    if doc is None:
        return False
    db.remove(doc_ids=[supplier_id])
    return True


def seed_suppliers() -> tuple[int, int]:
    db = get_db()
    query = Query()

    inserted = 0
    skipped = 0

    for supplier in SUPPLIERS_SEED:
        exists = db.contains((query.name == supplier["name"]) & (query.country == supplier["country"]))
        if exists:
            skipped += 1
            continue

        record = SupplierRecord(**supplier)
        db.insert(record.model_dump(mode="json"))
        inserted += 1

    return inserted, skipped
