# Auditoría de Serialización — Backend API

> **Fecha:** 2026-08-24  
> **Objetivo:** Identificar cómo serializa cada endpoint y llevarlo a estándares de producción.  
> **Criterio:** Ningún endpoint debe devolver objetos ORM crudos ni `dict` sin esquema Pydantic.

---

## Resumen ejecutivo

| Clasificación | Cantidad |
|---|---|
| ✅ Correcto | 24 endpoints |
| ⚠️ Parcial | 1 endpoint |
| ❌ Incorrecto | 2 endpoints |
| **Total** | **27 endpoints** |

---

## Listado completo de endpoints

### 1. `GET /health`
| Campo | Valor |
|---|---|
| Archivo | `main.py` |
| Estado | ✅ Correcto |
| Modelo | `dict[str, str]` inline (aceptable para health) |
| response_model | No tiene (no necesita) |
| Riesgos | Ninguno |

---

### 2. `GET /auth/me`
|Campo | Valor |
|---|---|
| Archivo | `routes/auth.py` |
| Estado | ✅ Correcto |
| Modelo | `AuthMeResponse` |
| Endpoint fields | `id`, `email`, `role`, `profile` (anidado `ProfilePublic`) |
| Riesgos | Ninguno |

---

### 3. `POST /auth/login`
| Campo | Valor |
|---|---|
| Archivo | `routes/auth.py` |
| Estado | ✅ Correcto |
| Modelo | `TokenResponse` |
| Campos | `access_token`, `token_type`, `expires_in` |
| Riesgos | Ninguno |

---

### 4. `POST /auth/forgot-password`
| Campo | Valor |
|---|---|
| Archivo | `routes/auth.py` |
| Estado | ❌ Incorrecto (bajo riesgo) |
| Serialización actual | Devuelve `dict[str, str]` sin `response_model` |
| Riesgos | Bajo: solo devuelve un mensaje, pero carece de esquema formal|
| **Recomendación** | Crear `MessageResponse` genérico|

---

###5.`POST /auth/reset-pasword`
|Campo|Valor|
|---|---|
|Archivo|`routes/auth.py`|
|Estado|❌ Incorrecto (bajo riesgo)|
|Serialización actual|Devuelve`dict[str, str]` sin `response_model`|
|Riesgos|Bajo: solo devuelve un mensaje, pero carece de esquema formal|
|**Recomendación**|Usar `MessageResponse` genérico|

---

### 6. `POST /auth/change-password`
| Campo | Valor |
|---|---|
| Archivo | `routes/auth.py` |
| Estado | ❌ Incorrecto (bajo riesgo) |
| Serialización actual | Devuelve `dict[str, str]` sin `response_model` |
| Riesgos | Bajo: solo devuelve un mensaje, pero carece de esquema formal |
| **Recomendación** | Usar `MessageResponse` genérico |

---

### 7. `POST /users` (Registro)
| Campo | Valor |
|---|---|
| Archivo | `routes/users.py` |
| Estado | ❌ **Incorrecto** |
| Serialización actual | No tiene `response_model`. Devuelve `dict` crudo: `{"user": {...}, "profile": {...}}` |
| Campos expuestos hoy | `user` (id, email, is_active, role, created_at) + `profile` (id, user_id, name, phone, address) |
| Riesgos | Fata de esquema: el cliente no tiene contratos fiables sobre la respuesta|
|**Recomendación**| Crear `UserRegistrationResponse` con dos campos: `user: UserPublic` y `profile: ProfilePublic` |

---

### 8. `GET /users`
|Campo|Valor|
|---|---|
|Archivo|`routes/users.py`|
|Estao|✅ Correcto|
|Modelo|`list[UserPublic]`|
|Campos|`id`, `email`, `is_active`, `role`, `created_at`|
|Riesgos|Ninguno|

---

###9.`GET /users/{user_id}`
|Campo|Valor|
|---|---|
|Archivo|`routes/users.py`|
|Estao|✅Correcto|
|Modelo|`UserPblic`|
|Campos|`id`, `email`, `is_active`, `role`, `created_at`|
|Riesgos|Ninguno|

---

###10. `PUT /users/{user_id}`
| Campo | Valor |
|---|---|
| Archivo | `routes/users.py` |
| Estado | ✅ Correcto |
| Modelo | `UserPublic` |
| Campos | `id`, `email`, `is_active`, `role`, `created_at` |
| Riesgos | Ninguno |

---

### 11. `DELETE /users/{user_id}`
| Campo | Valor |
|---|---|
| Archivo | `routes/users.py` |
| Estado | ❌ Incorrecto (bajo riesgo) |
| Serialización actual | Devuelve `dict[str, str]` sin `response_model` |
| Riesgos | Bajo: solo mensaje de confirmación |
| **Recomendación** | Usar `MessageResponse` |

---

### 12. `GET /users/{user_id}/profile`
| Campo | Valor |
|---|---|
| Archivo | `routes/users.py` |
| Estado | ✅ Correcto |
| Modelo | `ProfilePublic` |
| Campos | `id`, `user_id`, `name`, `phone`, `address` |
| Riesgos | Ninguno |

---

### 13. `GET /profiles/me`
| Camp | Valor |
|---|---|
| Archivo | `routes/profiles.py` |
| Estado | ✅ Correcto |
| Modelo | `ProfilePublic` |
| Campos | `id`, `user_id`, `name`, `phone`, `address` |
| Riesgos | Ninguno |

---

###14. `PUT /profiles/me`
| Camp | Valor |
|---|---|---|
| Archivo | `routes/profiles.py` |
| Estado | ✅ Correcto |
| Modelo | `ProfilePublic` |
| Campos | `id`, `user_id`, `name`, `phone`, `address` |
| Riesgos | Ninguno |

---

### 15. `POST /supplier`
| Campo | Valor |
|---|---|
| Archivo | `routes/suppliers.py` |
| Estado | ✅ Correcto |
| Modelo | `SupplierResponse` |
| Campos | `id`, `name`, `country`, `categories`, `rate_per_unit`, `currency`, `status`, `contact_email`, `notes`, `updated_at` |
| Riesgos | Expone `contact_email` y `notes` en el listado (se puede optimizar) |

---

### 16. `GET /suppliers`
| Campo | Valor |
|---|---|
| Archivo | `routes/suppliers.py` |
| Estado | ⚠️ Parcial |
| Modelo | `list[SupplierResponse]` |
| Campos expuestos | `id`, `name`, `country`, `categories`, `rate_per_unit`, `currency`, `status`, `contact_email`, `notes`, `updated_at` |
| Riesgos | Payload grande: `contact_email` y `notes` no son necesarios en un listado. `currency` y `status` son campos internos |
| **Recomendación** | Crear `SupplierListItem` con campos esenciales: `id`, `name`, `country`, `categories`, `rate_per_unit`, `currency`, `status`. Dejar `contact_email`, `notes` para el detalle |

---

### 17. `GET /suppliers/{supplier_id}`
| Campo | Valor |
|---|---|
| Archivo | `routes/suppliers.py` |
| Estado | ✅ Correcto |
| Modelo | `SupplierResponse` |
| Campos | `id`, `name`, `country`, `categories`, `rate_per_unit`, `currency`, `status`, `contact_email`, `notes`, `updated_at` |
| Riesgos | Podría escindirse en `SupplierDetail` y `SupplierListItem` |

---

### 18. `PATCH /suppliers/{supplier_id}/rate`
| Campo | Valor |
|---|---|
| Archivo | `routes/suppliers.py` |
| Estado | ✅ Correcto |
| Modelo | `SupplierResponse` |
| Riesgos | Expone todo el objeto cuando solo se actualizó el rate, pero es práctica común en APIs |

---

###19. `PATCH /sppliers/{supplier_id}/rate`(typo)
|Campo|Valor|
|---|---|
|Archivo|`routes/suppliers.py`|
|Estado|✅ Correcto (el typo está en la ruta, no en la serialización)|
|Modelo|`SupplierResponse`|
|Riesgos|Endpoint duplicado por typo. Se debe deprecar|

---

###20. `PACTH /suppliers/{supplier_id}/status`
| Campo | Valor |
|---|---|
| Archivo | `routes/suppliers.py` |
| Estado | ✅ Correcto |
| Modelo | `SupplierResponse` |
| Riesgos | Ninguo |

---

###21. `DELETE /suppliers`
| Campo| Valor |
|---|---|
| Archivo | `routes/suppliers.py` |
| Estado| ❌ Incorrecto (bajo riesgo)|
| Serialización actual | Devuelve `dict[str, str]` sin `response_model`|
| Riesgos | Bajo: solo mensaje de confirmación |
| **Recomendación** | Usar `MessageResponse` |

---

### 22. `DELETE /suppliers/{supplier_id}`
| Campo | Valor |
|---|---|
| Archivo | `routes/suppliers.py` |
| Estado | ❌ Incorrecto (bajo riesgo) |
| Serialización actual | Devuelve `dict[str, str]` sin `response_model` |
| Riesgos | Bajo: solo mensaje de confirmación |
| **Recomendación** | Usar `MessageResponse` |

---

###23. `POST/ap/incidents`
| Campo | Valor |
|---|---|
| Archivo | `routes/incidents.py` |
| Estado | ✅ Correcto |
| Modelo | `IncidentResponse` |
| Campos | `id`, `title`, `description`, `category`, `status`, `origin`, `branch`, `created_at`, `updated_at` |
| Riesgos | El modelo `IncidentCreate` permite al cliente fijar el `status` inicial — debería forzarse a `open` en creación. Esto es lógica de negocio, no serialización |

---

### 24. `GET /api/incidents`
| Campo | Valor |
|---|---|
| Archivo | `routes/incidents.py` |
| Estado | ✅ Correcto |
| Modelo| `list[IncidentResponse]` |
| Campos | `id`, `title`, `description`, `category`, `status`, `origin`, `branch`, `created_at`, `updated_at` |
| Riesgos | Descripción (`description`, 5000 chars) en listado puede ser payload grande. Considerar `IncidentListItem` |

---

### 25. `GET /api/incidents/{incident_id}`
| Campo | Valor |
|---|---|
| Archivo | `routes/incidents.py` |
| Estado | ✅ Correcto |
| Modelo | `IncidentResponse` |
| Campos | `id`, `title`, `description`, `category`, `status`, `origin`, `branch`, `created_at`, `updated_at` |
| Riesgos | Ninguno |

---

### 26. `PATCH /api/incidents/{incident_id}/status`
| Campo | Valor |
|---|---|
| Archivo | `routes/incidents.py` |
| Estado | ✅ Correcto |
| Modelo | `IncidentResponse` |
| Campos | `id`, `title`, `description`, `category`, `status`, `origin`, `branch`, `created_at`, `updated_at` |
| Riesgos | Devuelve todo el objeto cuando solo cambió `status`. Aceptable |

---

### 27. `GET /api/incidents/summary`
| Campo | Valor |
|---|---|
| Archivo | `routes/incidens.py`|
|Estao|⚠️**Parcia**|
|Serilización actual|`-> dict[str, dict[str, int]]` sin `response_model`|
|Campos expuestos|`by_status`, `by_category`, `by_origin`, `by_branch` cada uno con `dict[str, int]`|
|Riesgos|Payload con estructura predecible pero sin esquema formal|
|**Recomendación**|Crear `IncidentSummaryResponse` con campos tipados|

---

###28. `GET /nventory/products`
|Campo|Valor|
|---|---|
|Archivo|`routes/inventory.py`|
|Estado|✅ Correcto|
|Modelo|`list[IngredientResponse]`|
|Campos|`id`, `name`, `sku`, `unit`, `category`, `country`, `current_stock`||Riesgos|Ninguno|

---

###29. `POST /inventory/products`
|Campo|Valor|
|---|---|
|Archivo|`routes/inventory.py`|
|Estado|✅ Correcto|
|Modelo|`IngredientResponse`|
|Campos|`id`, `name`, `sku`, `unit`, `category`, `country`, `current_stock`|
|Riesgos|Ninguno|

---

###30. `GET/inventory/products/{ingredient_id}`
| Campo | Valor |
|---|---|
| Archivo | `routes/inventory.py` |
| Estado | ✅ Correcto |
| Modelo | `IngredientResponse` |
| Campos | `id`, `name`, `sku`, `unit`, `category`, `country`, `current_stock` |
| Riesgos | Ninguno |

---

### 31. `POST /inventory/orders/inbound`
| Campo | Valor |
|---|---|
| Archivo | `routes/inventory.py` |
| Estado | ✅ Correcto |
| Modelo | `IngredientEntryResponse` |
| Campos | `id`, `ingredient_id`, `quantity`, `supplier_name`, `location_id`, `created_at`, `user_uuid` |
| Riesgos | Expone `user_uuid` — campo interno de auditoría. Considerar omitirlo del response|

---

###32.`POST /inventory/orders/outbound`
|Campo|Valor|
|---|---|
|Archivo|`routes/inventory.py`|
|Estado|✅ Correcto|
|Modelo|`IngredientExitResponse`|
|Campos|`id`, `ingredient_id`, `quantity`, `reason`, `location_id`, `created_at`, `user_uuid`|
|Riesgos|Expone `user_uuid` — campo interno de auditoría|

---

###33.`GET /inventory/orders`
|Campo|Valor|
|---|---|
|Archivo|`routes/inventory.py`|
|Estado|✅ Correcto|
|Modelo|`list[IngredientOrderEntry]`|
|Campos|`id`, `type`, `ingredient_id`, `ingredient_name`, `ingredient_sku`, `quantity`, `supplier_name`, `reason`, `location_id`, `created_at`, `user_uuid`|
|Riesgos|Expone `user_uuid` — campo interno|

---

## Problemas detectados

### 🔴 Críticos

| # | Endpoint | Problema | Solución |
|---|---|---|---|
| 1 | `POST /users` | Sin `response_model`. Devuelve `dict` crudo | Crear `UserRegistrationResponse` |
| 2 | `GET /api/incidents/summary` | Sin `response_model`. `dict[str, dict[str, int]]` | Crear `IncidentSummaryResponse` |

### 🟡 Medios

| # | Endpoint(s) | Problema | Solución |
|---|---|---|---|
| 3 | `GET /suppliers` | `SupplierResponse` completo en listado expone `contact_email`, `notes` | Crear `SupplierListItem` |
| 4 | Varios DELETE, change-password, etc. | Devuelven `dict[str, str]` sin esquema | Usar `MessageResponse` genérico |

### 🟢 Bajos / Informativos

| # | Endpoint(s) | Problema | Solución |
|---|---|---|---|
| 5 | `PATCH /sppliers/{id}/rate` | Ruta con typo ("sppliers") | Deprecar o eliminar |
| 6 | `POST /api/incidents` | Cliente puede fijar `status` inicial | Forzar `status="open"` en creación |
| 7 | Inventory entries/exits/orders | Expone `user_uuid` interno | Considerar omitir en response |
| 8 | `GET /api/incidents` | `description` (5000 chars) en cada item del listado | Crear `IncidentListItem` sin description |

---

## Plan de acción: Serializers propuestos

### Nuevos modelos Pydantic a crear

```python
# 1. Mensaje genérico para respuestas simples
class MessageResponse(BaseModel):
    message: str

# 2. Respuesta de registro
class UserRegistrationResponse(BaseModel):
    user: UserPublic
    profile: ProfilePublic

# 3. Resumen de incidencias
class IncidentSummaryResponse(BaseModel):
    by_status: dict[str, int]
    by_category: dict[str, int]
    by_origin: dict[str, int]
    by_branch: dict[str, int]

# 4. Versión ligera de Supplier para listados
class SupplierListItem(BaseModel):
    id: int
    name: str
    country: CountryEnum
    categories: list[str]
    rate_per_unit: float
    currency: CurrencyEnum
    status: SupplierStatusEnum
```

### Endpoints a modificar

| Endpoint | Acción |
|---|---|
| `POST /users` | Agregar `response_model=UserRegistrationResponse` |
| `GET /api/incidents/summary` | Agregar `response_model=IncidentSummaryResponse` |
| `POST /auth/forgot-password` | Agregar `response_model=MessageResponse` |
| `POST /auth/reset-password` | Agregar `response_model=MessageResponse` |
| `POST /auth/change-password` | Agregar `response_model=MessageResponse` |
| `DELETE /users/{user_id}` | Agregar `response_model=MessageResponse` |
| `DELETE /suppliers` | Agregar `response_model=MessageResponse` |
| `DELETE /suppliers/{supplier_id}` | Agregar `response_model=MessageResponse` |
| `GET /suppliers` | Cambiar a `response_model=list[SupplierListItem]` |

---

## Archivos a modificar

1. **`models.py`** — Agregar `SupplierListItem`
2. **`schemas.py`** — Agregar `MessageResponse`
3. **`incident_models.py`** — Agregar `IncidentSummaryResponse`
4. **`auth_models.py`** — Agregar `UserRegistrationResponse`
5. **`routes/users.py`** — Corregir `POST /users` con `response_model`
6. **`routes/incidents.py`** — Corregir `GET /api/incidents/summary` con `response_model`
7. **`routes/suppliers.py`** — Optimizar `GET /suppliers` con `SupplierListItem`
8. **`routes/auth.py`** — Agregar `MessageResponse` a endpoints sin esquema

---

## Conclusión

La API está **bien serializada en su mayoría** (24/27 endpoints correctos). Los problemas principales son:

1. **`POST /users`** es el único caso grave: devuelve un dict sin esquema.
2. **`GET /api/incidents/summary`** estructura predecible pero sin modelo formal.
3. **Los endpoints de mensajes simples** carecen de `response_model`.
4. **`GET /suppliers`** podría optimizarse separando listado de detalle.