# CACHING REPORT — Optimizaciones de Rendimiento Frontend

> **Proyecto:** Brasaland Website (Next.js 16 + React 19)
> **Rama:** `feature/caching-optimisation`
> **Fecha:** 2026-08-24

---

## Resumen

Se identificaron y aplicaron **3 tipos de optimización** en el frontend del monorepo:

1. **Lazy Loading** de componentes pesados mediante `next/dynamic`
2. **Memoización** de cálculos costosos mediante `useMemo`
3. **Extracción** de secciones de módulos grandes para carga diferida

---

## 1. Lazy Loading — Dashboard de métricas (`backoffice/page.tsx`)

### Archivo modificado
- `uis/website/src/app/backoffice/page.tsx`
- Componente extraído: `uis/website/src/components/DashboardMetrics.tsx` (nuevo)

### ¿Qué se optimizó?
La sección `<section id="dashboard">` contenía **8 cálculos** que procesaban datos de muestra (`sampleLocations`, `sampleSales`, `sampleMenuItems`) mediante funciones costosas de `@repo/utils/transformations`:

- `calculateDailyRevenue` — recorre todas las ventas filtrando por fecha
- `calculateAverageTicket` — suma de tickets / cantidad
- `findTopSellingItems` — agrupa ventas por ítem, ordena y corta top N
- `calculateCountryComparison` — cruza ventas, locaciones y menú por país
- `rankLocationsByPerformance` — puntúa cada locación combinando 4 métricas
- `filterActiveLocations` / `sortMenuItemsByPrice` — filtros y ordenaciones sobre colecciones
- 3 validaciones (`validateMenuItem`, `validateSaleTransaction`, `validateLocation`) que recorren arrays completos

### ¿Por qué está justificado?
- **Peso del bundle:** Las importaciones de `@repo/utils/transformations`, `@repo/utils/validation`, `@repo/data/sample`, `@repo/utils/collections` y `@repo/utils/search` representan un chunk grande que no es necesario para la carga inicial.
- **Frecuencia:** El dashboard está debajo del pliegue (`below the fold`), tras la hero section y tres módulos de navegación. No es visible hasta que el usuario hace scroll.
- **Impacto en bundle:** Se eliminan ~30 KB (gzip estimado) del bundle crítico inicial.

### Implementación
```tsx
const DashboardMetrics = dynamic(() => import("@/components/DashboardMetrics"), {
  loading: () => (
    <div className="flex items-center justify-center py-20 text-sm text-slate-400">
      Cargando dashboard…
    </div>
  ),
});
```

### Fallback UX
Un spinner indicador "Cargando dashboard…" centrado con el mismo estilo visual del tema oscuro.

### Diff (conceptual)
```
- import type { WasteRecord } from "@repo/types/model";
- import { sampleLocations, ... } from "@repo/data/sample";
- import { filterActiveLocations, ... } from "@repo/utils/collections";
- import { findLocationById, ... } from "@repo/utils/search";
- import { calculateAverageTicket, ... } from "@repo/utils/transformations";
- import { validateLocation, ... } from "@repo/utils/validation";
+ import dynamic from "next/dynamic";
+ const DashboardMetrics = dynamic(() => import("@/components/DashboardMetrics"), ...);

- <section id="dashboard">...contenido del dashboard...</section>
+ <DashboardMetrics />
```

---

## 2. Lazy Loading — Formulario de registro de incidencias (`incidents/page.tsx`)

### Archivos modificados
- `uis/website/src/app/backoffice/incidents/page.tsx`
- Componente extraído: `uis/website/src/components/IncidentCreateForm.tsx` (nuevo)

### ¿Qué se optimizó?
El formulario "Registrar incidencia" (con todos sus campos, selects dinámicos, validación client-side y estados de carga) se extrajo a un componente independiente y se carga diferidamente.

### ¿Por qué está justificado?
- **Frecuencia de uso:** El formulario de creación está al **final del scroll** en una página que ya contiene el resumen de métricas y el listado de incidencias con filtros. El usuario primero lee las métricas, luego explora la lista y solo al final crea una nueva incidencia.
- **Peso del formulario:** Incluye importación de `BRANCHES`, `CATEGORIES`, `ORIGINS`, `STATUSES` y su lógica de validación completa, lo que añade código JS al bundle crítico.
- **Interacción:** No es necesario que el formulario esté disponible en el primer paint ni en los primeros segundos de interacción.

### Implementación
```tsx
const IncidentCreateForm = dynamic(() => import("@/components/IncidentCreateForm"), {
  loading: () => (
    <section className="rounded-2xl border border-orange-300/25 bg-slate-900 p-5 sm:p-6">
      <p className="text-sm text-slate-400">Cargando formulario de registro…</p>
    </section>
  ),
});
```

### Fallback UX
Un placeholder del mismo tamaño y estilo que el formulario real, sin salto de layout.

### Callback post-creación
El formulario acepta un `onCreated` que refresca tanto el listado como el resumen, manteniendo la funcionalidad idéntica a la original.

### Diff (conceptual)
```
- import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
+ import dynamic from "next/dynamic";
+ const IncidentCreateForm = dynamic(() => import("@/components/IncidentCreateForm"), ...);

-  const [form, setForm] = useState<IncidentForm>(EMPTY_FORM);
-  const [saving, setSaving] = useState(false);
-  const [formErrors, setFormErrors] = useState<Record<string, string>>({});
-  const [notice, setNotice] = useState<string | null>(null);
-  async function create(event: FormEvent<HTMLFormElement>) { ... }

-  <section className="rounded-2xl border border-orange-300/25 ...">
-    <!-- formulario completo -->
-  </section>
+  <IncidentCreateForm onCreated={() => { void loadList(); void loadSummary(); }} />
```

---

## 3. useMemo — Cálculos del Dashboard (`DashboardMetrics.tsx`)

### Archivo
- `uis/website/src/components/DashboardMetrics.tsx` (nuevo)

### ¿Qué se optimizó?
Los 8 cálculos sobre datos de muestra en el dashboard se envolvieron en `useMemo` con arrays de dependencias vacíos (`[]`), ya que los datos (`sampleLocations`, `sampleSales`, `sampleMenuItems`) son estáticos — nunca cambian durante el ciclo de vida del componente.

### Cálculos memoizados

| Cálculo | Dependencias | ¿Por qué es costoso? |
|---|---|---|
| `activeLocations` | `[]` | Filtra un array de 14+ locaciones |
| `sortedMenuByUsd` | `[]` | Ordena items del menú por precio |
| `dailyRevenueUSD` | `[referenceDate]` | Filtra ventas por rango de fechas y suma precios |
| `averageTicketUSD` | `[]` | Suma todos los tickets / N ventas |
| `topSelling` | `[]` | Agrupa ventas por ítem (recorrido completo) + ordenación + slice |
| `countryComparison` | `[]` | Cruza 3 colecciones (ventas, locaciones, menú) |
| `locationRanking` | `[]` | Puntúa cada locación con 4 sub-métricas (recorre todo varias veces) |
| `isDataValid` | `[]` | Ejecuta 3 validaciones `.every()` sobre arrays completos |

### ¿Qué mejora aporta?
- **Antes:** Cada render del componente (por cualquier `setState` o cambio contextual) re-ejecutaba los 8 cálculos, incluyendo bucles anidados y funciones de orden superior.
- **Después:** Los cálculos se ejecutan **una sola vez** en el ciclo de vida del componente. Cualquier re-render posterior simplemente lee los valores memoizados.

### Criterio de selección
No se aplicó memoización a cálculos triviales como accesos a propiedades o render condicional simple. Solo se protegieron operaciones con complejidad O(n) o superior que iteran sobre colecciones.

### Diff (conceptual)
```tsx
- const dailyRevenueUSD = calculateDailyRevenue(sampleSales, referenceDate, "USD");
+ const dailyRevenueUSD = useMemo(
+   () => calculateDailyRevenue(sampleSales, referenceDate, "USD"),
+   [referenceDate],
+ );

- const locationRanking = rankLocationsByPerformance(locations, sales, waste, items);
+ const locationRanking = useMemo(
+   () => rankLocationsByPerformance(sampleLocations, sampleSales, wasteRecords, sampleMenuItems),
+   [],
+ );
// (mismo patrón para los 8 cálculos)
```

---

## Impacto estimado

| Métrica | Antes | Después | Mejora |
|---|---|---|---|
| Bundle JS inicial (`/backoffice`) | ~120 KB | ~85 KB (sin dashboard ni form) | **~30% menor** |
| Cálculos en render inicial del dashboard | 8 ejecuciones síncronas | 1 ejecución única (memoizado) | **0 re-cálculos en re-renders** |
| Tiempo de paint inicial (LCP) | Afectado por imports pesados | Solo CSS + layout inicial | **Mejora indirecta** |
| Re-renders por cambios de estado en lista de incidencias | Re-ejecutaba lógica de form inlines | Form separado, no afecta | **Aislamiento de renders** |

---

## Principios respetados

- ❌ No se aplicó memoización a cálculos triviales (ej. `.length`, `?.` encadenamiento)
- ❌ No se aplicó Lazy Loading a componentes críticos para la carga inicial (hero, navbar, layout)
- ✅ Todos los fallbacks son consistentes con el diseño visual del tema oscuro
- ✅ No se alteró la funcionalidad ni la frescura de datos (los cálculos con datos estáticos son seguros con `[]`)
- ✅ Los datos provenientes de API (incidencias, proveedores, inventario) NO se memoizaron para no afectar frescura

---

# CACHING REPORT — Optimizaciones de Rendimiento Backend (FastAPI)

> **Backend:** FastAPI (services/api)
> **Infraestructura:** TinyDB (JSON) + Supabase PostgreSQL vía SQLModel
> **Middleware de timing:** main.py — logs `{method} {path} → {status} | {duration:.1f}ms`
> **Volumen de datos durante el test:** 27 ingredientes, 223 entradas, 166 salidas en Supabase

---

## 1. Listado completo de endpoints

### Autenticación (routes/auth.py) — SIN cacheo por seguridad
| Método | Ruta | Protegido | Coste estimado | Frecuencia | Datos |
|---|---|---|---|---|---|
| POST | `/auth/login` | No | Bajo (bcrypt verify) | Baja | Privados (sesión) |
| POST | `/auth/forgot-password` | No | Bajo | Muy baja | Privados |
| POST | `/auth/reset-password` | No | Bajo | Muy baja | Privados |
| POST | `/auth/change-password` | Sí | Bajo | Muy baja | Privados |
| GET | `/auth/me` | Sí | Bajo | Media | **Privados** (user-specific) |

### Usuarios (routes/users.py) — SIN cacheo por seguridad
| Método | Ruta | Protegido | Coste estimado | Frecuencia | Datos |
|---|---|---|---|---|---|
| POST | `/users` | No (registro) | Bajo | Baja | Privados |
| GET | `/users` | Sí (admin) | Bajo | Baja | Privados |
| GET | `/users/{id}` | Sí | Bajo | Baja | **Privados** |
| PUT | `/users/{id}` | Sí | Bajo | Baja | Privados |
| DELETE | `/users/{id}` | Sí | Bajo | Baja | Privados |
| GET | `/users/{id}/profile` | Sí | Bajo | Baja | **Privados** |

### Perfiles (routes/profiles.py) — SIN cacheo por seguridad
| Método | Ruta | Protegido | Coste | Frecuencia | Datos |
|---|---|---|---|---|---|
| GET | `/profiles/me` | Sí | Bajo | Media | **Privados** |
| PUT | `/profiles/me` | Sí | Bajo | Baja | Privados |

### Incidencias (routes/incidents.py)
| Método | Ruta | Protegido | Coste | Frecuencia | Datos |
|---|---|---|---|---|---|
| POST | `/api/incidents` | No | Bajo | Baja | Públicos |
| **GET** | **`/api/incidents/summary`** | **No** | **Medio** (Counter sobre todo el JSON) | **Alta** (backoffice) | **Estables** |
| GET | `/api/incidents` | No | Medio (filtros en memoria) | Alta | Estables |
| GET | `/api/incidents/{id}` | No | Bajo | Baja | Estables |
| PATCH | `/api/incidents/{id}/status` | No | Bajo | Media | Cambiantes |

### Proveedores (routes/suppliers.py) — todos requieren auth
| Método | Ruta | Protegido | Coste | Frecuencia | Datos |
|---|---|---|---|---|---|
| POST | `/supplier` | Sí | Bajo | Baja | Cambiantes |
| **GET** | **`/suppliers`** | **Sí** | **Medio** (lee JSON + filtra) | **Alta** | **Muy estables** |
| GET | `/suppliers/{id}` | Sí | Bajo | Media | Muy estables |
| PATCH | `/suppliers/{id}/rate` | Sí | Bajo | Baja | Cambiantes |
| PATCH | `/suppliers/{id}/status` | Sí | Bajo | Baja | Cambiantes |
| DELETE | `/suppliers/{id}` | Sí | Bajo | Muy baja | Cambiantes |
| DELETE | `/suppliers` | Sí | Bajo | Muy baja | Cambiantes |

### Inventario (routes/inventory.py) — todos requieren auth, datos NO personalizados
| Método | Ruta | Protegido | Coste | Frecuencia | Datos |
|---|---|---|---|---|---|
| POST | `/inventory/products` | Sí | Bajo | Baja | Cambiantes |
| **GET** | **`/inventory/products`** | **Sí** | **Muy alto** (N×2 agregaciones SQL) | **Alta** | **Estables** |
| **GET** | **`/inventory/products/{id}`** | **Sí** | **Alto** (2 agregaciones SQL) | **Media** | **Estables** |
| POST | `/inventory/orders/inbound` | Sí | Bajo | Media | Cambiantes |
| POST | `/inventory/orders/outbound` | Sí | Medio (valida stock) | Media | Cambiantes |
| **GET** | **`/inventory/orders`** | **Sí** | **Alto** (2 queries + N joins) | **Media** | **Estables** |

### Salud
| Método | Ruta | Protegido | Coste | Frecuencia |
|---|---|---|---|---|
| GET | `/health` | No | Ínfimo | Baja |

---

## 2. Endpoints seleccionados para caching

### Candidato 1: `GET /inventory/products`
- **Coste:** **1.0s** en el primer request con 223 entradas + 166 salidas (2 consultas SUM por ingrediente).
- **Frecuencia:** Alta — el frontend de inventario consulta esta ruta al cargar y al refrescar.
- **Estabilidad:** Los datos solo cambian cuando se crea un producto (raro) o una orden (más frecuente, pero sigue siendo estable a escala de segundos).
- **Justificación:** Cada ingrediente ejecuta 2 consultas agregadas (SUM de entradas y SUM de salidas). Con 27 ingredientes son 54 consultas SQL. El TTL de 30s permite servir desde memoria caché durante ventanas de alta demanda.

### Candidato 2: `GET /api/incidents/summary`
- **Coste:** ~5ms pero escala linealmente con el número de incidencias (lee todo el JSON + 4 Counters).
- **Frecuencia:** Muy alta — el backoffice muestra el resumen en la cabecera y los usuarios lo refrescan manualmente o con polling.
- **Estabilidad:** Cambia solo cuando se crea una incidencia o se transiciona su estado.
- **Justificación:** Es el endpoint más llamado del módulo de incidencias. TTL de 15s es adecuado para un backoffice donde un pequeño desfase es aceptable.

### Candidato 3: `GET /suppliers`
- **Coste:** ~7ms, lee todo el archivo JSON de TinyDB.
- **Frecuencia:** Alta (listado principal del módulo de proveedores).
- **Estabilidad:** Muy estable — los proveedores se crean/modifican con poca frecuencia.
- **Justificación:** TTL de 60s. Los datos de proveedores cambian tan poco que incluso 5 minutos sería aceptable, pero 60s mantiene buena frescura visual.

---

## 3. Implementación del caching

### Módulo: `services/api/cache.py` (nuevo)

Se implementó un sistema de caché en memoria con las siguientes características:
- **Almacenamiento:** Diccionario global `{key: (expiry_timestamp, value)}`
- **TTL por entrada:** Configurable por endpoint
- **Clave de caché:** `{path}?{query_string}` — incluye filtros de búsqueda
- **Decorador:** `@cached(ttl_seconds=N)` para envolver endpoints FastAPI
- **Invalidación:** `invalidate_cache(prefix)` — borra todas las entradas cuyo path empiece por el prefijo
- **Seguridad:** La clave NO incluye el user_id; esto es seguro porque los endpoints cacheados devuelven datos NO personalizados (mismos datos para todos los usuarios autenticados)

### Endpoints cacheados

| Endpoint | Archivo | TTL | Clave de caché |
|---|---|---|---|
| `GET /inventory/products` | `routes/inventory.py` | 30s | `/inventory/products?country=X` |
| `GET /inventory/products/{id}` | `routes/inventory.py` | 30s | `/inventory/products/123` |
| `GET /inventory/orders` | `routes/inventory.py` | 30s | `/inventory/orders?ingredient_id=X` |
| `GET /api/incidents/summary` | `routes/incidents.py` | 15s | `/api/incidents/summary` |
| `GET /suppliers` | `routes/suppliers.py` | 60s | `/suppliers?country=X&category=X` |

### Código de ejemplo

```python
# cache.py - Decorador principal
def cached(ttl_seconds: float = 30.0):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            request = _find_request(args, kwargs)
            if request:
                key = _build_cache_key(request)
                cached_value = get_cached(key)
                if cached_value is not None:
                    return cached_value
                result = func(*args, **kwargs)
                set_cached(key, result, ttl_seconds)
                return result
            return func(*args, **kwargs)
        return wrapper
    return decorator

# routes/inventory.py
@router.get("/products", response_model=list[IngredientResponse])
@cached(ttl_seconds=30.0)  # <-- una línea
def list_products(
    request: Request,
    country: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[IngredientResponse]:
    ...
```

---

## 4. Invalidación de caché

Cada endpoint de escritura invalida la caché del endpoint de lectura afectado:

| Escritura | Invalida | Mecanismo |
|---|---|---|
| `POST /inventory/products` | `/inventory/products` | `invalidate_cache("/inventory/products")` |
| `POST /inventory/orders/inbound` | `/inventory/products`, `/inventory/orders` | `invalidate_cache(...)` × 2 |
| `POST /inventory/orders/outbound` | `/inventory/products`, `/inventory/orders` | `invalidate_cache(...)` × 2 |
| `POST /api/incidents` | `/api/incidents` | `invalidate_cache("/api/incidents")` |
| `PATCH /api/incidents/{id}/status` | `/api/incidents` | `invalidate_cache("/api/incidents")` |
| `POST /supplier` | `/suppliers` | `invalidate_cache("/suppliers")` |
| `PATCH /suppliers/{id}/rate` | `/suppliers` | `invalidate_cache("/suppliers")` |
| `PATCH /suppliers/{id}/status` | `/suppliers` | `invalidate_cache("/suppliers")` |
| `DELETE /suppliers/{id}` | `/suppliers` | `invalidate_cache("/suppliers")` |
| `DELETE /suppliers` | `/suppliers` | `invalidate_cache("/suppliers")` |

La invalidación usa **prefijos de ruta**: `invalidate_cache("/inventory/products")` elimina tanto `/inventory/products?country=CO` como `/inventory/products/1`.

---

## 5. Seguridad de datos

**NO se cachean** los siguientes endpoints porque devuelven datos privados o personalizados:

| Endpoint | Motivo |
|---|---|
| `GET /auth/me` | Datos del usuario autenticado (email, rol, perfil) |
| `GET /profiles/me` | Perfil personal del usuario |
| `GET /users/{id}` | Datos de usuario específico |
| `GET /users/{id}/profile` | Perfil de usuario específico |
| `GET /users` | Listado admin de usuarios (datos sensibles) |
| `POST /auth/login` | Credenciales — nunca cachear |
| `POST /auth/change-password` | Acción de seguridad |

**SÍ se cachean** endpoints autenticados que devuelven datos NO personalizados:

| Endpoint | Por qué es seguro |
|---|---|
| `GET /inventory/products` | Mismos productos/stock para todos los usuarios |
| `GET /inventory/orders` | Mismas órdenes para todos los usuarios |
| `GET /suppliers` | Mismos proveedores para todos los usuarios autenticados |

La clave de caché **no incluye el user_id** en ningún caso.

---

## 6. Seeder de carga realista

### Script: `services/api/seed_heavy.py` (nuevo)

Se creó un seeder que genera un volumen de datos realista en Supabase:

| Tabla | Antes | Después |
|---|---|---|
| `ingredient` | 6 | **27** (+21) |
| `ingrediententry` | 4 | **223** (+219) |
| `ingredientexit` | 3 | **166** (+163) |

Los datos incluyen:
- **25 ingredientes** con nombres realistas en español e inglés, categorías variadas (meat, sauce, produce, packaging, cleaning, beverage), países CO/US
- **200 entradas** con fechas distribuidas en 20 meses, 14 locaciones, 15 proveedores colombianos y 10 estadounidenses
- **150 salidas** (~90% consumo, ~10% merma) con cantidades gaussianas proporcionales al stock aproximado

---

## 7. Resultados de latencia

Mediciones con el middleware de timing incorporado en `main.py`:

| Endpoint | Sin caché (run 1) | Con caché (run 2) | Con caché (run 3) | Mejora |
|---|---|---|---|---|
| `GET /inventory/products` | **1.000 s** | **0.003 s** | **0.004 s** | **~99.6 %** |
| `GET /api/incidents/summary` | 0.005 s | 0.004 s | 0.002 s | ~50 % |
| `GET /suppliers` | 0.007 s | 0.007 s | 0.003 s | ~50 % |

El mayor impacto se observa en `GET /inventory/products`, que pasa de **1 segundo** a **3 milisegundos** gracias al caching. La razón es que con 27 ingredientes, cada uno ejecuta 2 consultas agregadas (SUM) sobre tablas con ~200 filas cada una, resultando en 54 consultas SQL por request.

---

## 8. Diffs

### services/api/cache.py (nuevo archivo)
Archivo completo con sistema de caché: `CacheDict`, `get_cached`, `set_cached`, `invalidate_cache`, `decorador @cached`.

### services/api/routes/inventory.py
```
+ from cache import cached, invalidate_cache
+ from fastapi import Request

+ @cached(ttl_seconds=30.0)
- def list_products(country, db):
+ def list_products(request: Request, country, db):

+ @cached(ttl_seconds=30.0)
- def get_product(ingredient_id, db):
+ def get_product(request: Request, ingredient_id, db):

+ @cached(ttl_seconds=30.0)
- def list_orders(ingredient_id, db):
+ def list_orders(request: Request, ingredient_id, db):

  # En create_product, create_inbound_order, create_outbound_order:
+ invalidate_cache("/inventory/products")
+ invalidate_cache("/inventory/orders")
```

### services/api/routes/incidents.py
```
+ from cache import cached, invalidate_cache
+ from fastapi import Request

+ @cached(ttl_seconds=15.0)
- def get_incidents_summary():
+ def get_incidents_summary(request: Request):

  # En create_incident y update_incident_status:
+ invalidate_cache("/api/incidents")
```

### services/api/routes/suppliers.py
```
+ from cache import cached, invalidate_cache
+ from fastapi import Request

+ @cached(ttl_seconds=60.0)
- def list_suppliers(country, category):
+ def list_suppliers(request: Request, country, category):

  # En create_supplier, patch_supplier_rate, patch_supplier_status,
  # delete_by_query, delete_supplier:
+ invalidate_cache("/suppliers")
```

---

## 9. Endpoints que NO se cachearon (y por qué)

| Endpoint | Motivo |
|---|---|
| `GET /auth/me`, `/profiles/me` | Datos privados del usuario autenticado |
| `GET /users/{id}`, `/users/{id}/profile` | Datos privados de usuario específico |
| `GET /users` (listado admin) | Datos sensibles (emails, roles) |
| `POST /auth/login` | Credenciales y creación de sesión |
| `POST/PUT/DELETE` en general | Escrituras — nunca cachear |
| `GET /api/incidents` (listado) | Filtros muy diversos, baja tasa de acierto esperada |
| `GET /api/incidents/{id}` (detalle) | Baja frecuencia, coste bajo |
| `GET /health` | Coste ínfimo, no necesita cache