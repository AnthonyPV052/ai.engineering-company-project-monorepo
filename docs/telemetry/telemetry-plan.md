# Plan de Telemetría — Brasaland Inventory System

> **Propósito:** Transformar el sistema de gestión de inventario de Brasaland de una caja negra operativa a una fuente continua de información de negocio y salud técnica, sentando las bases para el dashboard ejecutivo y los reportes semanales de Mariana y Felipe.

---

## Índice

1. [Resumen ejecutivo](#1-resumen-ejecutivo)
2. [Flujo de gestión de inventario y puntos de instrumentación](#2-flujo-de-gestión-de-inventario-y-puntos-de-instrumentación)
3. [Catálogo de eventos de telemetría](#3-catálogo-de-eventos-de-telemetría)
   - [3.1 Métricas obligatorias (Telemetry-context.md)](#31-métricas-obligatorias)
   - [3.2 Oportunidades identificadas — Autenticación y sesión](#32-oportunidades-identificadas--autenticación-y-sesión)
   - [3.3 Oportunidades identificadas — Inventario y operaciones](#33-oportunidades-identificadas--inventario-y-operaciones)
   - [3.4 Oportunidades identificadas — Proveedores](#34-oportunidades-identificadas--proveedores)
   - [3.5 Oportunidades identificadas — Incidencias](#35-oportunidades-identificadas--incidencias)
   - [3.6 Oportunidades identificadas — Rendimiento y errores](#36-oportunidades-identificadas--rendimiento-y-errores)
   - [3.7 Oportunidades identificadas — Navegación y UX](#37-oportunidades-identificadas--navegación-y-ux)
4. [Event Envelope estándar](#4-event-envelope-estándar)
5. [Esquemas detallados de eventos](#5-esquemas-detallados-de-eventos)
   - [5.1 Métricas obligatorias](#51-métricas-obligatorias)
   - [5.2 Oportunidades — Autenticación y sesión](#52-oportunidades--autenticación-y-sesión)
   - [5.3 Oportunidades — Rendimiento y errores](#53-oportunidades--rendimiento-y-errores)
   - [5.4 Oportunidades — Navegación y UX](#54-oportunidades--navegación-y-ux)
   - [5.5 Oportunidades — Inventario extendido](#55-oportunidades--inventario-extendido)
6. [Resumen y priorización](#6-resumen-y-priorización)
7. [Estrategia de entrega](#7-estrategia-de-entrega)
   - [7.1 Procesamiento: stream vs batch](#71-procesamiento-stream-vs-batch)
   - [7.2 Throttle / debounce](#72-throttle--debounce)
   - [7.3 Riesgos y exclusiones](#73-riesgos-y-exclusiones)

---

## 1. Resumen ejecutivo

El sistema de inventario de Brasaland está en producción, pero el equipo de operaciones —encabezado por Felipe, Director de Operaciones— opera a ciegas: no sabe qué ingredientes se compran más, en qué local se pierde más producto, ni con qué frecuencia un local se queda sin un insumo crítico.

La telemetría que se define en este plan convierte cada interacción significativa con el sistema en un evento estructurado que fluye desde la captura (frontend y backend) hasta el almacenamiento, habilitando tres niveles de consumo:

- **Operativo (Felipe):** alertas y paneles diarios sobre compras, consumo, merma y stock crítico.
- **Táctico (Lucía, Jake):** detección de anomalías de precio y de intentos de manipulación directa de stock para auditoría y compras.
- **Ejecutivo (Mariana):** reportes semanales agregados por local, por país y por semana sin necesidad de reinstrumentar.

**Principios de diseño del plan:**

- Las métricas obligatorias de `Telemetry-context.md` son el piso mínimo y deben coincidir exactamente en nombre, hipótesis y decisión.
- Los campos `properties` siguen el envelope estándar definido en el contexto: `location_id`, `country`, `product_id`, `product_category`, `quantity`, `unit`, `currency`.
- No se incluyen datos personales (nombres de empleados, datos de clientes).
- Las monedas se registran en la moneda del local (COP/USD) — sin conversión en la capa de telemetría.
- Los `event_type` se nombran con `snake_case` prefijado por dominio (`auth_`, `inventory_`, `supplier_`, `incident_`, `perf_`, `nav_`, `error_`).

---

## 2. Flujo de gestión de inventario y puntos de instrumentación

A continuación se mapea el flujo completo que un usuario autenticado recorre para gestionar el inventario, desde que accede al sistema hasta que completa una orden de entrada o salida. Se identifican **9 puntos de instrumentación potenciales** a lo largo del flujo.

```
[1] Login                     →  POST /auth/login
       │                              │
       │ [2] Validación de           │ Autenticación 2FA no aplica;
       │     credenciales             │ solo usuario/contraseña
       ▼                              ▼
[3] Dashboard Backoffice      →  GET /auth/me (validar sesión)
       │
       │ [4] Navegación al
       │     módulo de inventario
       ▼
[5] Lista de productos        →  GET /inventory/products
       │
       ├── [6] Vista detalle producto → GET /inventory/products/{id}
       │
       └── Sección "Órdenes"
                │
                ├── [7] Historial de órdenes → GET /inventory/orders
                │
                ├── [8] Formulario entrada (inbound)
                │       │
                │       ├── Validación cliente: cantidad > 0, proveedor no vacío,
                │       │   ubicación 1–14, producto existe.
                │       │
                │       └── [9] POST /inventory/orders/inbound
                │               ├── Validación backend: ingrediente existe
                │               ├── ✔ Éxito: IngredientEntry creado, caché invalidada
                │               └── ✘ FALLO: 404 ingrediente no encontrado
                │
                └── [10] Formulario salida (outbound)
                        │
                        ├── [11] Validación cliente: stock suficiente vs. cantidad
                        │   (aviso visual "La cantidad supera el stock disponible")
                        │
                        ├── Validación backend: reason = "consumption"|"waste",
                        │   ingrediente existe
                        │
                        ├── [12] Validación stock suficiente:
                        │   compute_current_stock < quantity → 400
                        │
                        ├── [13] POST /inventory/orders/outbound
                        │       ├── ✔ Éxito: IngredientExit creado
                        │       └── ✘ FALLO: stock insuficiente
                        │
                        └── [14] Post-creación: verificar umbral mínimo
                            (si stock_resultante < min_config → stock_threshold_triggered)
```

### Puntos de instrumentación numerados

| # | Punto | Dónde ocurre | Evento asociado | Clasificación |
|---|-------|-------------|-----------------|---------------|
| 1 | Intento de login (éxito/fallo) | Backend `POST /auth/login` | `auth_login_attempted` | Oportunidad |
| 2 | Fallo de credenciales | Backend `verify_password` retorna False | `auth_login_failed` | Oportunidad |
| 3 | Sesión válida / expirada | Backend `get_current_user` / Frontend `ProtectedRoute` | `auth_session_checked` | Oportunidad |
| 4 | Navegación a sección inventario | Frontend router | `nav_page_visited` | Oportunidad |
| 5 | Consulta de lista de productos | Backend `GET /inventory/products` | — (rendimiento, ver #25) | Oportunidad |
| 6 | Consulta de detalle de producto | Backend `GET /inventory/products/{id}` | `inventory_product_viewed` | Oportunidad |
| 7 | Consulta de historial de órdenes | Backend `GET /inventory/orders` | `inventory_orders_history_viewed` | Oportunidad |
| 8 | Apertura de formulario de entrada | Frontend carga formulario inbound | `inventory_inbound_form_opened` | Oportunidad |
| 9 | Creación de orden de entrada | Backend `POST /inventory/orders/inbound` | `inbound_order_created` | **Obligatorio** |
| 10 | Apertura de formulario de salida | Frontend carga formulario outbound | `inventory_outbound_form_opened` | Oportunidad |
| 11 | Validación client-side: stock insuficiente | Frontend, advertencia visual | `inventory_outbound_stock_warning` | Oportunidad |
| 12 | Validación backend: stock insuficiente | Backend `_compute_current_stock < quantity` | — (deriva en error 400) | — |
| 13 | Creación de orden de salida | Backend `POST /inventory/orders/outbound` | `outbound_order_created` o `stock_waste_registered` | **Obligatorio** |
| 14 | Post-creación: umbral mínimo | Backend (lógica futura) | `stock_threshold_triggered` | **Obligatorio** |
| ★ | Intento de edición directa de stock | Middleware/Validación (rechazado por diseño) | `direct_stock_edit_rejected` | **Obligatorio** |
| ★ | Variación de precio de ingrediente | Backend al crear inbound order | `ingredient_price_variance_detected` | **Obligatorio** |

> ★ Estos dos puntos no aparecen explícitamente en el flujo visible del frontend, pero son críticos: el primero porque el backend por diseño no expone un endpoint de edición directa de stock (cualquier intento debe ser rechazado y registrado); el segundo porque debe comparar el costo unitario de cada entrada contra el histórico del mismo producto y proveedor.

---

## 3. Catálogo de eventos de telemetría

Cada evento del catálogo incluye:
- **event_type**: identificador único en snake_case.
- **Clasificación**: `obligatorio` (viene de Telemetry-context.md) u `oportunidad` (identificada por el autor del plan).
- **Disparo**: cuándo se emite el evento.
- **Hipótesis → Decisión**: la estructura "Capturamos X porque necesitamos saber Y, lo que nos permite tomar la decisión Z".
- **Properties**: campos que acompañan al evento.
- **Origen**: frontend (cliente) o backend (servidor).

---

### 3.1 Métricas obligatorias

> Estas métricas vienen definidas en `Telemetry-context.md` y son el piso mínimo del plan. Los nombres, hipótesis y decisiones coinciden exactamente con ese documento.

#### `inbound_order_created`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `obligatorio` |
| **Disparo** | Backend, al completar `POST /inventory/orders/inbound` (después de `db.commit()`). |
| **Hipótesis → Decisión** | Capturamos `inbound_order_created` porque necesitamos saber cuánto y qué se está comprando, por local y por proveedor, lo que nos permite consolidar compras entre locales para negociar mejores precios (Lucía). |
| **Properties** | `location_id`, `country`, `product_id`, `product_category`, `quantity`, `unit`, `currency`, `supplier_name` |
| **Origen** | Backend |

#### `outbound_order_created`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `obligatorio` |
| **Disparo** | Backend, al completar `POST /inventory/orders/outbound` con `reason = "consumption"`. |
| **Hipótesis → Decisión** | Capturamos `outbound_order_created` porque necesitamos saber qué ingredientes se consumen más, y a qué ritmo, por local, lo que nos permite ajustar la sugerencia automática de pedidos a proveedores (Felipe). |
| **Properties** | `location_id`, `country`, `product_id`, `product_category`, `quantity`, `unit`, `currency`, `reason` |
| **Origen** | Backend |

#### `stock_waste_registered`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `obligatorio` |
| **Disparo** | Backend, al completar `POST /inventory/orders/outbound` con `reason = "waste"`. |
| **Hipótesis → Decisión** | Capturamos `stock_waste_registered` porque necesitamos saber cuánto producto se pierde, por qué razón, y en qué local, lo que nos permite priorizar auditorías de merma en los locales con peor indicador (Felipe). |
| **Properties** | `location_id`, `country`, `product_id`, `product_category`, `quantity`, `unit`, `currency`, `reason` (valores: `expired`, `kitchen_error`, `theft_suspected`) |
| **Origen** | Backend |

#### `stock_threshold_triggered`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `obligatorio` |
| **Disparo** | Backend, después de cualquier operación de salida (`outbound_order_created` o `stock_waste_registered`), al verificar que el stock resultante del producto en ese local está por debajo del umbral mínimo configurado. |
| **Hipótesis → Decisión** | Capturamos `stock_threshold_triggered` porque necesitamos saber con qué frecuencia un local se queda corto de un ingrediente clave, lo que nos permite ajustar el umbral mínimo o la frecuencia de reabastecimiento de ese producto. |
| **Properties** | `location_id`, `country`, `product_id`, `product_category`, `current_stock`, `threshold_min`, `unit`, `currency` |
| **Origen** | Backend |

#### `direct_stock_edit_rejected`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `obligatorio` |
| **Disparo** | Backend o middleware, ante cualquier intento de modificar el stock fuera de una orden de entrada/salida (por defecto, el backend no expone endpoint de edición directa; si se intercepta una petición con esa intención, se rechaza y registra). |
| **Hipótesis → Decisión** | Capturamos `direct_stock_edit_rejected` porque necesitamos saber si el personal está intentando saltarse el control de trazabilidad, lo que nos permite reforzar capacitación o permisos en los locales donde esto ocurre con más frecuencia (Jake). |
| **Properties** | `location_id`, `country`, `product_id`, `user_id` (anonimizado), `attempt_type` (ej. `api_direct_patch`, `db_manual`), `reason_rejected` |
| **Origen** | Backend / Middleware |

#### `ingredient_price_variance_detected`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `obligatorio` |
| **Disparo** | Backend, durante la creación de una orden de entrada (`POST /inventory/orders/inbound`), al detectar que el precio unitario del producto en esa orden varía más de un 10% (o el umbral configurado) respecto al histórico del mismo producto y proveedor. |
| **Hipótesis → Decisión** | Capturamos `ingredient_price_variance_detected` porque necesitamos saber cuándo un ingrediente clave (ej. carne) sube de precio de forma anómala, lo que nos permite alertar a Lucía y a Mariana para renegociar o buscar proveedor alterno. |
| **Properties** | `location_id`, `country`, `product_id`, `product_category`, `supplier_name`, `previous_unit_price`, `new_unit_price`, `variance_percentage`, `currency` |
| **Origen** | Backend |

---

### 3.2 Oportunidades identificadas — Autenticación y sesión

#### `auth_login_attempted`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `oportunidad` |
| **Disparo** | Backend, cada vez que se recibe una petición `POST /auth/login`. |
| **Hipótesis → Decisión** | Capturamos `auth_login_attempted` porque necesitamos saber cuántos intentos de login recibe el sistema, desde qué IPs y en qué locales, lo que nos permite detectar picos anómalos, posibles ataques de fuerza bruta y evaluar si el sistema de autenticación necesita refuerzo (Jake). |
| **Properties** | `success` (booleano), `ip_geo_country` (inferido), `user_role` (si éxito), `failure_reason` (si fallo) |
| **Origen** | Backend |

#### `auth_login_failed`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `oportunidad` |
| **Disparo** | Backend, cuando `verify_password` retorna False en `POST /auth/login`. |
| **Hipótesis → Decisión** | Capturamos `auth_login_failed` porque necesitamos saber qué emails están fallando y con qué frecuencia, lo que nos permite identificar cuentas bajo ataque o usuarios que olvidaron su contraseña y necesitan recordatorio o restablecimiento. |
| **Properties** | `email_domain`, `failure_count_window` (acumulado en los últimos 5 min) |
| **Origen** | Backend |

#### `auth_session_expired`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `oportunidad` |
| **Disparo** | Frontend, cuando `ProtectedRoute` detecta que el token JWT ha expirado (error 401 en `GET /auth/me` o validación local de `exp`). |
| **Hipótesis → Decisión** | Capturamos `auth_session_expired` porque necesitamos saber con qué frecuencia los usuarios pierden la sesión, lo que nos permite ajustar el `ACCESS_TOKEN_EXPIRE_MINUTES` para equilibrar seguridad y experiencia de usuario. |
| **Properties** | `time_since_last_activity` (minutos), `page_before_expiry` |
| **Origen** | Frontend |

#### `auth_password_reset_requested`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `oportunidad` |
| **Disparo** | Backend, al recibir `POST /auth/forgot-password`. |
| **Hipótesis → Decisión** | Capturamos `auth_password_reset_requested` porque necesitamos saber cuántos usuarios solicitan restablecimiento de contraseña y desde qué locales, lo que nos permite identificar problemas de usabilidad en el login o campañas de phishing dirigidas al personal. |
| **Properties** | `request_ip` (anonimizada parcial) |
| **Origen** | Backend |

#### `auth_password_changed`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `oportunidad` |
| **Disparo** | Backend, al completar `POST /auth/change-password` exitosamente. |
| **Hipótesis → Decisión** | Capturamos `auth_password_changed` porque necesitamos saber con qué frecuencia los usuarios cambian su contraseña, lo que nos permite evaluar si la política de rotación es eficaz o si hay un problema de seguridad que obliga a cambios frecuentes. |
| **Properties** | `user_role`, `time_since_last_change` (días) |
| **Origen** | Backend |

---

### 3.3 Oportunidades identificadas — Inventario y operaciones

#### `inventory_product_viewed`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `oportunidad` |
| **Disparo** | Backend, al servir `GET /inventory/products/{id}`. |
| **Hipótesis → Decisión** | Capturamos `inventory_product_viewed` porque necesitamos saber qué productos consultan más los operadores y desde qué local, lo que nos permite identificar ingredientes que generan dudas o requieren atención especial (productos nuevos, con stock crítico, o con alta rotación). |
| **Properties** | `product_id`, `product_category`, `location_id`, `country` |
| **Origen** | Backend |

#### `inventory_orders_history_viewed`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `oportunidad` |
| **Disparo** | Backend, al servir `GET /inventory/orders` (posiblemente con filtros). |
| **Hipótesis → Decisión** | Capturamos `inventory_orders_history_viewed` porque necesitamos saber con qué frecuencia los operadores revisan el historial de órdenes, lo que nos permite validar si el flujo de trazabilidad es lo suficientemente transparente o si los usuarios necesitan buscar información que debería estar más accesible. |
| **Properties** | `has_filters` (booleano), `result_count`, `location_id` (si aplica filtro) |
| **Origen** | Backend |

#### `inventory_inbound_form_opened`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `oportunidad` |
| **Disparo** | Frontend, cuando el usuario carga la página `/backoffice/inventory/orders/inbound`. |
| **Hipótesis → Decisión** | Capturamos `inventory_inbound_form_opened` porque necesitamos saber cuántas veces se inicia el proceso de registro de entrada, lo que nos permite calcular la tasa de conversión de "formulario abierto" vs. "orden creada" y detectar abandonos por fricción en el formulario. |
| **Properties** | `location_id_preselected` (si aplica), `product_id_preselected` (si viene por query param) |
| **Origen** | Frontend |

#### `inventory_outbound_form_opened`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `oportunidad` |
| **Disparo** | Frontend, cuando el usuario carga la página `/backoffice/inventory/orders/outbound`. |
| **Hipótesis → Decisión** | Capturamos `inventory_outbound_form_opened` porque necesitamos saber cuántas veces se inicia el proceso de registro de salida, lo que nos permite calcular la tasa de conversión y detectar si el formulario tiene una tasa de abandono superior a la de entrada (lo que indicaría fricción en la selección de motivo o validación de stock). |
| **Properties** | `location_id_preselected`, `product_id_preselected` |
| **Origen** | Frontend |

#### `inventory_outbound_stock_warning`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `oportunidad` |
| **Disparo** | Frontend, cuando el usuario ve la advertencia visual "La cantidad supera el stock disponible" en el formulario de salida. |
| **Hipótesis → Decisión** | Capturamos `inventory_outbound_stock_warning` porque necesitamos saber con qué frecuencia los operadores intentan registrar salidas que superan el stock disponible, lo que nos permite identificar si hay errores de conteo, productos mal etiquetados o necesidad de ajustar umbrales de reorden. |
| **Properties** | `product_id`, `requested_quantity`, `available_stock`, `location_id` |
| **Origen** | Frontend |

#### `inventory_inbound_form_abandoned`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `oportunidad` |
| **Disparo** | Frontend, cuando el usuario abandona la página `/backoffice/inventory/orders/inbound` sin haber enviado el formulario (se rastrea con `beforeunload` o heartbeat). |
| **Hipótesis → Decisión** | Capturamos `inventory_inbound_form_abandoned` porque necesitamos saber qué campos rellenó el usuario antes de abandonar, lo que nos permite identificar puntos de fricción (por ej., un proveedor que no aparece en la lista o una cantidad que el usuario no está seguro de haber medido bien). |
| **Properties** | `fields_filled` (lista de campos completados), `time_spent_seconds` |
| **Origen** | Frontend |

#### `inventory_outbound_form_abandoned`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `oportunidad` |
| **Disparo** | Frontend, análogo al anterior pero para el formulario de salida. |
| **Hipótesis → Decisión** | Capturamos `inventory_outbound_form_abandoned` porque necesitamos saber si el formulario de salida tiene más abandono que el de entrada, lo que nos permite priorizar mejoras de UX en el flujo de salida (por ej., la selección de motivo parece confusa o la advertencia de stock disuade sin dar alternativas). |
| **Properties** | `fields_filled`, `time_spent_seconds`, `stock_warning_shown` (booleano) |
| **Origen** | Frontend |

---

### 3.4 Oportunidades identificadas — Proveedores

#### `supplier_created`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `oportunidad` |
| **Disparo** | Backend, al completar `POST /supplier`. |
| **Hipótesis → Decisión** | Capturamos `supplier_created` porque necesitamos saber qué nuevos proveedores se están incorporando, en qué país y para qué categorías, lo que nos permite validar que la expansión de la red de proveedores sigue la estrategia de abastecimiento definida por Lucía. |
| **Properties** | `supplier_name`, `country`, `categories`, `rate_per_unit`, `currency` |
| **Origen** | Backend |

#### `supplier_rate_updated`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `oportunidad` |
| **Disparo** | Backend, al completar `PATCH /suppliers/{id}/rate`. |
| **Hipótesis → Decisión** | Capturamos `supplier_rate_updated` porque necesitamos saber con qué frecuencia y en qué magnitud cambian las tarifas de los proveedores, lo que nos permite alertar a Lucía sobre renegociaciones frecuentes que podrían indicar inestabilidad en el precio de materias primas clave. |
| **Properties** | `supplier_id`, `previous_rate`, `new_rate`, `variance_percentage`, `currency`, `country` |
| **Origen** | Backend |

#### `supplier_status_changed`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `oportunidad` |
| **Disparo** | Backend, al completar `PATCH /suppliers/{id}/status`. |
| **Hipótesis → Decisión** | Capturamos `supplier_status_changed` porque necesitamos saber qué proveedores están siendo suspendidos o reactivados, lo que nos permite detectar patrones (ej., varios proveedores de una misma categoría suspendidos en un período corto, lo que indicaría un problema de calidad generalizado). |
| **Properties** | `supplier_id`, `previous_status`, `new_status`, `country`, `categories` |
| **Origen** | Backend |

---

### 3.5 Oportunidades identificadas — Incidencias

#### `incident_created`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `oportunidad` |
| **Disparo** | Backend, al registrarse una nueva incidencia en el gestor de incidencias. |
| **Hipótesis → Decisión** | Capturamos `incident_created` porque necesitamos saber qué tipo de incidencias se reportan más, en qué local y con qué origen (cliente, local, interno), lo que nos permite priorizar la asignación de recursos de operaciones y detectar patrones tempranos de problemas recurrentes (Felipe). |
| **Properties** | `category`, `origin`, `branch`, `country` |
| **Origen** | Backend |

#### `incident_status_changed`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `oportunidad` |
| **Disparo** | Backend, al cambiar el estado de una incidencia (`open → in_progress`, `in_progress → resolved`, etc.). |
| **Hipótesis → Decisión** | Capturamos `incident_status_changed` porque necesitamos saber cuánto tiempo pasa desde que se abre una incidencia hasta que se resuelve y qué caminos de transición son más comunes, lo que nos permite medir la eficiencia del equipo de operaciones e identificar cuellos de botella (Felipe). |
| **Properties** | `incident_id`, `previous_status`, `new_status`, `category`, `branch`, `time_since_creation` (horas) |
| **Origen** | Backend |

---

### 3.6 Oportunidades identificadas — Rendimiento y errores

#### `perf_api_latency`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `oportunidad` |
| **Disparo** | Backend, después de cada petición HTTP (medido desde el middleware de timing existente en `main.py`). |
| **Hipótesis → Decisión** | Capturamos `perf_api_latency` porque necesitamos saber qué endpoints son lentos y cómo evoluciona la latencia en el tiempo, lo que nos permite identificar degradaciones tempranas, endpoints que necesitan optimización o caching más agresivo, y planificar escalabilidad. |
| **Properties** | `method`, `path` (normalizado, ej. `/inventory/products`), `status_code`, `duration_ms`, `country` (si aplica) |
| **Origen** | Backend |

#### `perf_api_error_rate`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `oportunidad` |
| **Disparo** | Backend, cada vez que un endpoint devuelve un código de error 4xx o 5xx. |
| **Hipótesis → Decisión** | Capturamos `perf_api_error_rate` porque necesitamos saber qué errores están ocurriendo y con qué frecuencia, lo que nos permite detectar bugs, picos de tráfico mal manejados o problemas de integración con Supabase/TinyDB antes de que afecten a múltiples locales. |
| **Properties** | `method`, `path`, `status_code`, `error_type` (validation_error, not_found, server_error), `country` |
| **Origen** | Backend |

#### `perf_frontend_page_load`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `oportunidad` |
| **Disparo** | Frontend, después de que una página del backoffice se cargue completamente (usando `Navigation Timing API` o `web-vitals`). |
| **Hipótesis → Decisión** | Capturamos `perf_frontend_page_load` porque necesitamos saber qué páginas cargan lento y cómo afecta la experiencia del operador, lo que nos permite optimizar bundles, lazy loading y estrategias de caché para que el personal de local no pierda tiempo esperando (Jake). |
| **Properties** | `page_path`, `load_time_ms`, `ttfb_ms`, `dom_interactive_ms`, `country` (inferido) |
| **Origen** | Frontend |

#### `error_frontend_unhandled`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `oportunidad` |
| **Disparo** | Frontend, cuando se produce una excepción no capturada (`window.onerror` o `React Error Boundary`). |
| **Hipótesis → Decisión** | Capturamos `error_frontend_unhandled` porque necesitamos saber qué errores están experimentando los usuarios en el frontend y en qué página, lo que nos permite corregir bugs antes de que se conviertan en reportes de incidencia y afecten la productividad del personal. |
| **Properties** | `page_path`, `error_message` (sanitizado, sin stack trace completo), `error_type`, `user_action` (última interacción) |
| **Origen** | Frontend |

#### `error_api_request_failure`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `oportunidad` |
| **Disparo** | Frontend, cuando una llamada `authenticatedApiFetch` falla (red timeout, error de red, respuesta 5xx). |
| **Hipótesis → Decisión** | Capturamos `error_api_request_failure` porque necesitamos saber si los operadores están experimentando fallos de conectividad o errores del servidor, lo que nos permite distinguir entre problemas de red del local y problemas del backend central, y actuar en consecuencia (Jake). |
| **Properties** | `endpoint`, `method`, `error_type` (network_timeout, server_error, http_4xx), `status_code` (si aplica), `retry_attempted` (booleano) |
| **Origen** | Frontend |

---

### 3.7 Oportunidades identificadas — Navegación y UX

#### `nav_page_visited`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `oportunidad` |
| **Disparo** | Frontend, cada vez que el usuario navega a una página del backoffice (rastreado a nivel de layout o router). |
| **Hipótesis → Decisión** | Capturamos `nav_page_visited` porque necesitamos saber qué secciones del backoffice visitan más los operadores, lo que nos permite priorizar mejoras de UX y rendimiento en las rutas más usadas, y detectar si alguna sección (ej. proveedores, incidencias) está siendo infrautilizada. |
| **Properties** | `page_path` (normalizado, ej. `/backoffice/inventory/products`), `referrer_path` (desde dónde viene), `country` (inferido del local del usuario) |
| **Origen** | Frontend |

#### `nav_section_abandoned`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `oportunidad` |
| **Disparo** | Frontend, cuando el usuario abandona una sección del backoffice sin interactuar con sus elementos principales (visto desde el backend: petición de listado que no deriva en ninguna acción de escritura). |
| **Hipótesis → Decisión** | Capturamos `nav_section_abandoned` porque necesitamos saber qué secciones consultan los operadores sin llegar a actuar, lo que nos permite identificar si la información presentada es insuficiente o confusa, o si el flujo de acción está mal ubicado. |
| **Properties** | `page_path`, `time_on_page_seconds`, `has_scrolled` (booleano) |
| **Origen** | Frontend |

#### `nav_search_performed`

| Campo | Valor |
|-------|-------|
| **Clasificación** | `oportunidad` |
| **Disparo** | Frontend, cuando el usuario utiliza algún filtro de búsqueda en productos, órdenes o incidencias. |
| **Hipótesis → Decisión** | Capturamos `nav_search_performed` porque necesitamos saber qué términos y filtros usan los operadores para buscar información, lo que nos permite mejorar la funcionalidad de búsqueda y detectar necesidades de información no cubiertas por las vistas predeterminadas. |
| **Properties** | `section` (products/orders/incidents/suppliers), `filter_type` (country, category, status), `result_count` |
| **Origen** | Frontend |

---

## 4. Event Envelope estándar

Todo evento de telemetría en Brasaland debe cumplir con el siguiente envelope estándar. Los campos del envelope son obligatorios en todos los eventos y proporcionan trazabilidad, correlación y auditoría.

### 4.1 Envelope — campos obligatorios

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `eventId` | `string (UUID v4)` | Identificador único del evento. Generado en el punto de captura. Permite deduplicación. |
| `timestamp` | `string (ISO 8601)` | Momento exacto en que ocurrió el evento. Formato: `YYYY-MM-DDTHH:mm:ss.sssZ` (siempre UTC). |
| `sessionId` | `string (UUID v4)` | Identificador de sesión del usuario. Se asigna al iniciar sesión y persiste hasta el logout o expiración. |
| `userId` | `string` | Identificador del usuario que generó el evento. Para eventos de backend, es el `user_uuid` del token JWT. Para eventos de frontend anónimos (login fallido), se omite. |
| `eventType` | `string` | Nombre del evento según la taxonomía `entidad_accion`. Ej. `inbound_order_created`, `session_expired`. |
| `schemaVersion` | `string` | Versión del esquema de este event_type. Semver estricto: `"1.0"`. Se incrementa al añadir/quitar campos del allowlist. |
| `requestId` | `string (UUID v4)` | Identificador de correlación que vincula el evento con la petición HTTP que lo originó. Generado por el backend en cada request (middleware) o por el frontend en cada llamada fetch. |
| `properties` | `object` | Payload específico del evento. Solo contiene las claves definidas en el allowlist de cada `eventType`. |

### 4.2 Ejemplo de envelope completo

```json
{
  "eventId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "timestamp": "2026-08-26T14:30:00.000Z",
  "sessionId": "c0d1e2f3-4a5b-6789-0cde-fa1234567890",
  "userId": "user_abc123",
  "eventType": "inbound_order_created",
  "schemaVersion": "1.0",
  "requestId": "req-8f7e6d5c-4b3a-2910-fedc-ba9876543210",
  "properties": {}
}
```

### 4.3 Principios del envelope

- **Inmutabilidad:** Una vez emitido, el evento no se modifica. El `eventId` garantiza idempotencia en el almacenamiento.
- **Correlación:** El `requestId` permite reconstruir la traza completa de una petición (frontend → API → base de datos).
- **Privacidad por diseño:** `userId` puede ser un seudónimo no reversible; nunca se incluyen nombres, emails ni datos personales en `properties`.
- **Evolución:** `schemaVersion` permite que consumidores downstream detecten cambios en el allowlist sin romper pipelines existentes.

---

## 5. Esquemas detallados de eventos

Esta sección define el allowlist de propiedades para cada evento del catálogo. Nada fuera del allowlist debe incluirse en `properties` — esto previene fugas accidentales de datos.

Convenciones de tipos:
- `UUID`: string con formato UUID v4.
- `DateTimeISO`: string ISO 8601 en UTC.
- `CountryCode`: `"CO"` | `"US"`.
- `CurrencyCode`: `"COP"` | `"USD"`.
- `LocationID`: entero 1–14.
- `ProductCategory`: `"meat"` | `"produce"` | `"sauce"` | `"beverage"` | `"packaging"` | `"cleaning"`.

---

### 5.1 Métricas obligatorias

#### `inbound_order_created`

| Campo | Tipo | Obligatorio | Descripción | ¿PII/Sensible? |
|-------|------|-------------|-------------|----------------|
| `location_id` | `LocationID` | ✅ | Identificador del local que recibe la mercancía (1–14) | No |
| `country` | `CountryCode` | ✅ | País del local (`CO` o `US`) | No |
| `product_id` | `integer` | ✅ | ID del ingrediente recibido | No |
| `product_category` | `ProductCategory` | ✅ | Categoría del producto | No |
| `quantity` | `number` | ✅ | Cantidad recibida (en la unidad del producto) | No |
| `unit` | `string` | ✅ | Unidad de medida (`kg`, `litro`, `unidad`) | No |
| `currency` | `CurrencyCode` | ✅ | Moneda de la transacción | No |
| `supplier_name` | `string` | ✅ | Nombre del proveedor | No |

**Allowlist:** `[location_id, country, product_id, product_category, quantity, unit, currency, supplier_name]`

---

#### `outbound_order_created`

| Campo | Tipo | Obligatorio | Descripción | ¿PII/Sensible? |
|-------|------|-------------|-------------|----------------|
| `location_id` | `LocationID` | ✅ | Identificador del local donde se consumió | No |
| `country` | `CountryCode` | ✅ | País del local | No |
| `product_id` | `integer` | ✅ | ID del ingrediente consumido | No |
| `product_category` | `ProductCategory` | ✅ | Categoría del producto | No |
| `quantity` | `number` | ✅ | Cantidad consumida | No |
| `unit` | `string` | ✅ | Unidad de medida | No |
| `currency` | `CurrencyCode` | ✅ | Moneda (COP/USD) | No |

**Allowlist:** `[location_id, country, product_id, product_category, quantity, unit, currency]`

---

#### `stock_waste_registered`

| Campo | Tipo | Obligatorio | Descripción | ¿PII/Sensible? |
|-------|------|-------------|-------------|----------------|
| `location_id` | `LocationID` | ✅ | Identificador del local donde ocurrió la merma | No |
| `country` | `CountryCode` | ✅ | País del local | No |
| `product_id` | `integer` | ✅ | ID del producto perdido | No |
| `product_category` | `ProductCategory` | ✅ | Categoría del producto | No |
| `quantity` | `number` | ✅ | Cantidad perdida | No |
| `unit` | `string` | ✅ | Unidad de medida | No |
| `currency` | `CurrencyCode` | ✅ | Moneda | No |
| `reason` | `string` | ✅ | Causa de la merma: `expired`, `kitchen_error`, o `theft_suspected` | No |

**Allowlist:** `[location_id, country, product_id, product_category, quantity, unit, currency, reason]`

---

#### `stock_threshold_triggered`

| Campo | Tipo | Obligatorio | Descripción | ¿PII/Sensible? |
|-------|------|-------------|-------------|----------------|
| `location_id` | `LocationID` | ✅ | Local donde se activó el umbral | No |
| `country` | `CountryCode` | ✅ | País del local | No |
| `product_id` | `integer` | ✅ | Producto por debajo del umbral | No |
| `product_category` | `ProductCategory` | ✅ | Categoría del producto | No |
| `current_stock` | `number` | ✅ | Stock actual después de la operación | No |
| `threshold_min` | `number` | ✅ | Umbral mínimo configurado para ese producto en ese local | No |
| `unit` | `string` | ✅ | Unidad de medida | No |
| `currency` | `CurrencyCode` | ✅ | Moneda | No |

**Allowlist:** `[location_id, country, product_id, product_category, current_stock, threshold_min, unit, currency]`

---

#### `direct_stock_edit_rejected`

| Campo | Tipo | Obligatorio | Descripción | ¿PII/Sensible? |
|-------|------|-------------|-------------|----------------|
| `location_id` | `LocationID` | ✅ | Local desde el que se intentó la edición | No |
| `country` | `CountryCode` | ✅ | País del local | No |
| `product_id` | `integer` | ✅ | Producto que se intentó modificar | No |
| `attempt_type` | `string` | ✅ | Tipo de intento: `api_direct_patch`, `db_manual`, `ui_bypass` | No |
| `reason_rejected` | `string` | ✅ | Motivo del rechazo: `no_endpoint`, `invalid_operation`, `unauthorized` | No |

**Sanitización:** El `userId` del envelope se almacena pero sin correlación a identidad real. No se incluye `user_id` duplicado en `properties`.

**Allowlist:** `[location_id, country, product_id, attempt_type, reason_rejected]`

---

#### `ingredient_price_variance_detected`

| Campo | Tipo | Obligatorio | Descripción | ¿PII/Sensible? |
|-------|------|-------------|-------------|----------------|
| `location_id` | `LocationID` | ✅ | Local que registró la entrada | No |
| `country` | `CountryCode` | ✅ | País del local | No |
| `product_id` | `integer` | ✅ | Producto con variación de precio | No |
| `product_category` | `ProductCategory` | ✅ | Categoría del producto | No |
| `supplier_name` | `string` | ✅ | Proveedor asociado a la orden | No |
| `previous_unit_price` | `number` | ✅ | Precio unitario histórico de referencia | No |
| `new_unit_price` | `number` | ✅ | Precio unitario de la nueva orden | No |
| `variance_percentage` | `number` | ✅ | Porcentaje de variación (ej. `15.5` = 15.5%) | No |
| `currency` | `CurrencyCode` | ✅ | Moneda del precio | No |

**Allowlist:** `[location_id, country, product_id, product_category, supplier_name, previous_unit_price, new_unit_price, variance_percentage, currency]`

---

### 5.2 Oportunidades — Autenticación y sesión

#### `auth_login_attempted`

| Campo | Tipo | Obligatorio | Descripción | ¿PII/Sensible? |
|-------|------|-------------|-------------|----------------|
| `success` | `boolean` | ✅ | Indica si el login fue exitoso | No |
| `failure_reason` | `string` | Opcional | Solo si `success=false`: `invalid_credentials`, `account_locked`, `inactive_account` | No |
| `ip_country` | `string` | Opcional | País inferido de la IP de origen (no la IP en sí) | **Sensible** — solo se almacena el país, no la IP |

**Sanitización:** No se almacena la IP completa ni el email. Solo se infiere y guarda el país de origen de la IP.

**Allowlist:** `[success, failure_reason, ip_country]`

---

#### `auth_login_failed`

| Campo | Tipo | Obligatorio | Descripción | ¿PII/Sensible? |
|-------|------|-------------|-------------|----------------|
| `email_domain` | `string` | ✅ | Dominio del email (ej. `gmail.com`, `brasaland.co`) | **Sensible** — solo se almacena el dominio, no el email completo |
| `failure_count_window` | `integer` | ✅ | Número de fallos consecutivos desde el último éxito en los últimos 5 minutos | No |

**Sanitización:** El email completo NUNCA se almacena. Solo se extrae y guarda el dominio.

**Allowlist:** `[email_domain, failure_count_window]`

---

#### `session_expired`

| Campo | Tipo | Obligatorio | Descripción | ¿PII/Sensible? |
|-------|------|-------------|-------------|----------------|
| `time_since_last_activity` | `integer` | ✅ | Minutos desde la última interacción registrada | No |
| `page_before_expiry` | `string` | Opcional | Ruta de la página donde expiró la sesión (normalizada) | No |

**Allowlist:** `[time_since_last_activity, page_before_expiry]`

---

#### `password_reset_requested`

| Campo | Tipo | Obligatorio | Descripción | ¿PII/Sensible? |
|-------|------|-------------|-------------|----------------|
| `email_domain` | `string` | ✅ | Dominio del email que solicitó el reseteo | **Sensible** — solo dominio, no email completo |

**Sanitización:** Mismo criterio que `auth_login_failed`: solo se almacena el dominio.

**Allowlist:** `[email_domain]`

---

### 5.3 Oportunidades — Rendimiento y errores

#### `api_latency_recorded`

| Campo | Tipo | Obligatorio | Descripción | ¿PII/Sensible? |
|-------|------|-------------|-------------|----------------|
| `method` | `string` | ✅ | Método HTTP (`GET`, `POST`, `PATCH`, `DELETE`) | No |
| `path` | `string` | ✅ | Ruta normalizada (ej. `/inventory/products`, `/auth/login`) | No |
| `status_code` | `integer` | ✅ | Código de respuesta HTTP | No |
| `duration_ms` | `number` | ✅ | Duración de la petición en milisegundos | No |
| `country` | `CountryCode` | Opcional | País inferido del local que originó la petición | No |

**Allowlist:** `[method, path, status_code, duration_ms, country]`

---

#### `api_error_occurred`

| Campo | Tipo | Obligatorio | Descripción | ¿PII/Sensible? |
|-------|------|-------------|-------------|----------------|
| `method` | `string` | ✅ | Método HTTP | No |
| `path` | `string` | ✅ | Ruta normalizada | No |
| `status_code` | `integer` | ✅ | Código de error HTTP (4xx o 5xx) | No |
| `error_type` | `string` | ✅ | Categoría: `validation_error`, `not_found`, `server_error`, `unauthorized` | No |
| `country` | `CountryCode` | Opcional | País inferido | No |

**Allowlist:** `[method, path, status_code, error_type, country]`

---

#### `frontend_error_occurred`

| Campo | Tipo | Obligatorio | Descripción | ¿PII/Sensible? |
|-------|------|-------------|-------------|----------------|
| `page_path` | `string` | ✅ | Ruta de la página donde ocurrió el error (normalizada) | No |
| `error_type` | `string` | ✅ | Tipo de error (`TypeError`, `ReferenceError`, `NetworkError`, `ReactError`) | No |
| `error_message` | `string` | ✅ | Mensaje de error (máximo 200 caracteres, sanitizado) | No |

**Sanitización:** `error_message` se trunca a 200 caracteres y se filtran patrones que pudieran contener datos del usuario (URLs, tokens, emails). Nunca se incluye el stack trace completo.

**Allowlist:** `[page_path, error_type, error_message]`

---

### 5.4 Oportunidades — Navegación y UX

#### `page_visited`

| Campo | Tipo | Obligatorio | Descripción | ¿PII/Sensible? |
|-------|------|-------------|-------------|----------------|
| `page_path` | `string` | ✅ | Ruta normalizada de la página visitada | No |
| `referrer_path` | `string` | Opcional | Ruta desde la que llegó el usuario (vacío si es entrada directa) | No |
| `country` | `CountryCode` | Opcional | País inferido del local del usuario | No |

**Allowlist:** `[page_path, referrer_path, country]`

---

#### `section_abandoned`

| Campo | Tipo | Obligatorio | Descripción | ¿PII/Sensible? |
|-------|------|-------------|-------------|----------------|
| `page_path` | `string` | ✅ | Ruta de la sección abandonada | No |
| `time_on_page_seconds` | `integer` | ✅ | Tiempo en segundos antes de abandonar | No |
| `has_scrolled` | `boolean` | ✅ | Indica si el usuario hizo scroll en la página | No |

**Allowlist:** `[page_path, time_on_page_seconds, has_scrolled]`

---

#### `search_performed`

| Campo | Tipo | Obligatorio | Descripción | ¿PII/Sensible? |
|-------|------|-------------|-------------|----------------|
| `section` | `string` | ✅ | Sección donde se realizó la búsqueda: `products`, `orders`, `incidents`, `suppliers` | No |
| `filter_type` | `string` | ✅ | Tipo de filtro usado: `country`, `category`, `status`, `text_query` | No |
| `result_count` | `integer` | ✅ | Número de resultados devueltos | No |

**Allowlist:** `[section, filter_type, result_count]`

---

### 5.5 Oportunidades — Inventario extendido

#### `outbound_stock_warning_triggered`

| Campo | Tipo | Obligatorio | Descripción | ¿PII/Sensible? |
|-------|------|-------------|-------------|----------------|
| `product_id` | `integer` | ✅ | Producto con stock insuficiente | No |
| `requested_quantity` | `number` | ✅ | Cantidad que el usuario intentó registrar | No |
| `available_stock` | `number` | ✅ | Stock disponible al momento de la advertencia | No |
| `location_id` | `LocationID` | ✅ | Local donde se realizó el intento | No |

**Allowlist:** `[product_id, requested_quantity, available_stock, location_id]`

---

#### `incident_created`

| Campo | Tipo | Obligatorio | Descripción | ¿PII/Sensible? |
|-------|------|-------------|-------------|----------------|
| `category` | `string` | ✅ | Categoría de la incidencia (`equipment_failure`, `supply_issue`, `customer_complaint`, `staff_issue`, `facility_issue`, `pos_system`, `delivery_issue`, `other`) | No |
| `origin` | `string` | ✅ | Origen: `customer`, `branch`, `internal` | No |
| `branch` | `string` | ✅ | Código del local o `central` | No |
| `country` | `CountryCode` | ✅ | País inferido del branch | No |

**Allowlist:** `[category, origin, branch, country]`

---

#### `supplier_rate_updated`

| Campo | Tipo | Obligatorio | Descripción | ¿PII/Sensible? |
|-------|------|-------------|-------------|----------------|
| `supplier_id` | `integer` | ✅ | ID del proveedor | No |
| `previous_rate` | `number` | ✅ | Tarifa anterior por unidad | No |
| `new_rate` | `number` | ✅ | Nueva tarifa por unidad | No |
| `variance_percentage` | `number` | ✅ | Porcentaje de cambio | No |
| `currency` | `CurrencyCode` | ✅ | Moneda de la tarifa | No |
| `country` | `CountryCode` | ✅ | País del proveedor | No |

**Allowlist:** `[supplier_id, previous_rate, new_rate, variance_percentage, currency, country]`

---

## 6. Resumen y priorización

### Totales del catálogo

| Clasificación | Cantidad |
|---------------|----------|
| **Obligatorias** (Telemetry-context.md) | 6 eventos |
| **Oportunidades identificadas** | 21 eventos |
| **Total del catálogo** | 27 eventos |

### Desglose por dominio

| Dominio | Eventos | Clasificación |
|---------|---------|---------------|
| Inventario — órdenes y stock | `inbound_order_created`, `outbound_order_created`, `stock_waste_registered`, `stock_threshold_triggered`, `direct_stock_edit_rejected`, `ingredient_price_variance_detected` | 6 obligatorios |
| Inventario — exploración adicional | `inventory_product_viewed`, `inventory_orders_history_viewed`, `inventory_inbound_form_opened`, `inventory_outbound_form_opened`, `inventory_outbound_stock_warning`, `inventory_inbound_form_abandoned`, `inventory_outbound_form_abandoned` | 7 oportunidades |
| Autenticación y sesión | `auth_login_attempted`, `auth_login_failed`, `auth_session_expired`, `auth_password_reset_requested`, `auth_password_changed` | 5 oportunidades |
| Proveedores | `supplier_created`, `supplier_rate_updated`, `supplier_status_changed` | 3 oportunidades |
| Incidencias | `incident_created`, `incident_status_changed` | 2 oportunidades |
| Rendimiento y errores | `perf_api_latency`, `perf_api_error_rate`, `perf_frontend_page_load`, `error_frontend_unhandled`, `error_api_request_failure` | 5 oportunidades |
| Navegación y UX | `nav_page_visited`, `nav_section_abandoned`, `nav_search_performed` | 3 oportunidades |

### Criterios de priorización para implementación

1. **Fase 1 — Obligatorio (piso):** Los 6 eventos obligatorios deben instrumentarse de punta a punta (captura → almacenamiento) al final de la serie de proyectos. Son la base del dashboard operativo de Felipe y del reporte ejecutivo de Mariana.
2. **Fase 2 — Alta (core operacional):** Eventos de autenticación (`auth_login_attempted`, `auth_login_failed`) + navegación (`nav_page_visited`) + rendimiento (`perf_api_latency`). Estos eventos no requieren cambios en las entidades de dominio y se pueden instrumentar con middleware existente.
3. **Fase 3 — Media (UX y exploración):** Eventos de formularios (`inventory_inbound_form_opened`, formularios abandonados), proveedores e incidencias. Requieren instrumentación en el frontend y coordinación con el equipo de UI.
4. **Fase 4 — Baja (monitoreo profundo):** Eventos de error frontend, búsqueda y umbrales detallados. Dependen de fases anteriores y son complementarios para el análisis de calidad.

### Cumplimiento de restricciones de negocio

- ✅ Las monedas se registran en `COP` o `USD` según el país del local — sin conversión en la capa de telemetría.
- ✅ El stock nunca se modifica directamente — el evento `direct_stock_edit_rejected` monitorea precisamente los intentos de violar esta restricción.
- ✅ No se incluyen nombres de empleados ni datos de clientes en `properties`.
- ✅ Los campos de idioma de UI (español/inglés) no se mezclan con `country`.

---

## 7. Estrategia de entrega

Esta sección define cómo se entrega cada evento desde el punto de captura hasta el almacenamiento, y qué controles de volumen se aplican para evitar saturación. También documenta los riesgos conocidos y las decisiones explícitas de no capturar ciertos datos.

---

### 7.1 Procesamiento: stream vs batch

Cada evento del catálogo se clasifica según si debe procesarse en **stream** (tiempo real, milisegundos desde la ocurrencia hasta la disponibilidad) o en **batch** (acumulado en lotes periódicos, minutos/horas).

El criterio de decisión es la **urgencia de la decisión** que el evento alimenta: si la acción derivada requiere respuesta en segundos/minutos, es stream; si la acción es analítica/reporting y se resuelve con agregación, es batch.

#### Eventos stream (tiempo real)

| Evento | Justificación | Consumidor |
|--------|---------------|------------|
| `stock_threshold_triggered` | Un producto por debajo del umbral mínimo puede detener la operación de un local ese mismo día. Felipe necesita saberlo de inmediato para autorizar una transferencia o reorden urgente. | Felipe (alerta) |
| `direct_stock_edit_rejected` | Un intento de manipulación directa del stock es un posible incidente de seguridad o un error crítico de proceso. Jake necesita investigarlo en el momento. | Jake (alerta) |
| `ingredient_price_variance_detected` | Una subida anómala de precio de un ingrediente clave puede requerir renegociación inmediata o cambio de proveedor. Lucía necesita actuar mientras la orden de entrada está fresca. | Lucía (alerta) |
| `auth_login_attempted` | Detección temprana de fuerza bruta. Si hay un pico de intentos fallidos desde una misma región, el sistema debe poder bloquear o escalar antes de que se comprometa una cuenta. | Sistema (escalado automático) |
| `auth_login_failed` | Complementa a `auth_login_attempted`. Los fallos consecutivos rápidos son el indicador más temprano de un ataque activo. | Sistema (escalado automático) |
| `api_error_occurred` | Errores 5xx indican que el backend está fallando. Un pico de errores requiere intervención inmediata del equipo de plataforma. | Jake / DevOps (alerta) |
| `incident_created` | Cada incidencia representa un problema activo en un local. El equipo de operaciones necesita visibilidad en tiempo real para asignar recursos. | Felipe (dashboard en tiempo real) |

Total eventos stream: **7** (5 obligatorios + 2 oportunidad)

#### Eventos batch (lotes periódicos)

| Evento | Justificación | Batch sugerido |
|--------|---------------|----------------|
| `inbound_order_created` | Las compras se consolidan en reportes diarios/semanales. Una orden individual no requiere acción inmediata. | Cada 15 min o al alcanzar 100 eventos |
| `outbound_order_created` | El consumo se analiza en agregación para identificar tendencias y ajustar pedidos futuros. | Cada 15 min o al alcanzar 100 eventos |
| `stock_waste_registered` | La merma se reporta semanalmente a Mariana y Felipe. Los valores diarios se consolidan sin urgencia. | Cada hora o al alcanzar 50 eventos |
| `session_expired` | La frecuencia de expiración de sesiones es una métrica de UX que se analiza semanalmente. | Cada hora |
| `password_reset_requested` | Volumen bajo y no crítico. Se analiza mensualmente para detectar tendencias. | Cada 24 h |
| `api_latency_recorded` | Las latencias se agregan en percentiles (p50, p95, p99). Una sola medición no es significativa. Sin embargo, si el p95 supera un umbral (ej. >2000ms) se promueve a stream para alertar. | Cada 1 min (ventana móvil de 5 min) |
| `frontend_error_occurred` | Los errores de frontend se analizan en agregación por tipo y por página. Una ocurrencia aislada no requiere acción. | Cada 30 min |
| `page_visited` | El volumen es alto (cada navegación). El valor está en la agregación por sección, usuario y local. | Cada 10 min o al alcanzar 500 eventos |
| `section_abandoned` | Análisis de UX a partir de patrones de abandono. No requiere tiempo real. | Cada hora |
| `search_performed` | Los términos de búsqueda se analizan para mejorar filtros y detectar necesidades de información. | Cada hora |
| `outbound_stock_warning_triggered` | Advertencias de stock insuficiente del frontend. Se analizan en agregación para identificar productos problemáticos. | Cada hora |
| `supplier_rate_updated` | Cambios de tarifa de proveedores. Se consolidan en reportes mensuales de costos. | Cada 24 h |

Total eventos batch: **12** (1 obligatorio + 11 oportunidad)

#### Diagrama de decisión stream vs batch

```
¿La decisión que alimenta el evento requiere acción en < 5 min?
├── Sí → ¿El evento se genera en backend o frontend?
│   ├── Backend → STREAM (emitir inmediatamente vía cola/pub-sub)
│   └── Frontend → STREAM con batching local (acumular y emitir cada 2s)
└── No → BATCH (acumular en buffer local o en cola, vaciar periódicamente)
```

---

### 7.2 Throttle / debounce

Algunos eventos tienen el potencial de generar volumen alto en condiciones normales o anómalas. Para proteger el almacenamiento y la red, se aplican las siguientes estrategias:

#### Eventos con throttling obligatorio

| Evento | Riesgo de volumen | Estrategia | Límite |
|--------|-------------------|------------|--------|
| `api_latency_recorded` | **Muy alto** — se genera por cada petición HTTP (docenas por minuto por local × 14 locales) | **Throttle de emisión:** en el middleware, acumular métricas en un buffer circular de 1 minuto y emitir un solo evento con array de duraciones y count. Alternativa: muestreo 1:10 si el volumen excede 1000 rpm. | 1 evento agregado por endpoint + ventana de 1 min |
| `page_visited` | **Alto** — cada navegación en el frontend | **Debounce:** si el usuario navega rápidamente entre páginas (ej. listado → detalle → listado), no emitir eventos intermedios si han pasado <500 ms desde la última navegación. | 1 evento cada 500 ms por sesión |
| `auth_login_attempted` | **Bajo en calma, crítico bajo ataque** — fuerza bruta puede generar cientos por minuto | **Throttle por IP inferida (país):** si se detectan >20 intentos/minuto desde un mismo país, agregar en lotes de 10 y reducir frecuencia. | 1 evento cada 100 ms por origen |
| `auth_login_failed` | **Bajo en calma, crítico bajo ataque** | **Debounce por email_domain:** acumular dominios repetidos en ventana de 1s y emitir un solo evento con `failure_count_window` incrementado. | 1 evento por dominio cada 1s |
| `api_error_occurred` | **Alto durante incidentes** — una caída de Supabase puede generar cientos de errores por minuto | **Throttle por path + error_type:** si se detectan >10 errores del mismo tipo en el mismo endpoint en 10s, agregar y emitir un contador. | 1 evento agregado por tipo/endpoint cada 10s |

#### Estrategia general de buffer

```
Frontend                          Backend
  │                                 │
  ├─ page_visited ──debounce(500ms)─┤
  ├─ search_performed ──────────────┤
  ├─ outbound_stock_warning ────────┤
  └─ frontend_error ──debounce(2s)──┤
                                      │
                                      ├─ api_latency_recorded ──throttle(1min buffer)──▶ Cola / Archivo
                                      ├─ api_error_occurred ────throttle(10s/type)─────▶ Cola / Archivo
                                      ├─ inbound_order_created ─────────────────────────▶ Cola / Archivo
                                      ├─ outbound_order_created ────────────────────────▶ Cola / Archivo
                                      ├─ stock_waste_registered ────────────────────────▶ Cola / Archivo
                                      ├─ stock_threshold_triggered ──STREAM─────────────▶ Alerta / Cola
                                      ├─ direct_stock_edit_rejected ──STREAM────────────▶ Alerta / Cola
                                      ├─ ingredient_price_variance ──STREAM─────────────▶ Alerta / Cola
                                      ├─ auth_login_attempted ──throttle(100ms)─────────▶ Cola / Alerta
                                      ├─ auth_login_failed ─────debounce(1s)────────────▶ Cola / Alerta
                                      ├─ api_error_occurred ────throttle(10s)───────────▶ Cola / Alerta
                                      ├─ incident_created ──────STREAM──────────────────▶ Alerta / Cola
                                      └─ supplier_rate_updated ─────────────────────────▶ Cola / Archivo
```

---

### 7.3 Riesgos y exclusiones

#### Riesgos identificados

1. **Volumen inesperado de `api_latency_recorded`:**
   Si los 14 locales están activos simultáneamente, el middleware de timing puede generar ~200 eventos/minuto en hora pico. Sin throttling, esto saturaría el almacenamiento. **Mitigación:** el buffer circular de 1 min y el muestreo 1:10 descritos en 7.2.

2. **Falsos positivos en `direct_stock_edit_rejected`:**
   El backend no expone un endpoint de edición directa, pero un error de programación (ej. query mal formada) podría registrar un falso positivo. **Mitigación:** revisión manual del primer mes de datos para calibrar el detector; añadir un campo `source` que distinga entre intentos reales (HTTP directo) y automáticos (código interno).

3. **Deriva semántica de `eventType`:**
   A medida que el sistema evolucione, un mismo `eventType` podría cambiar de significado si se añaden o eliminan campos del allowlist. **Mitigación:** el campo `schemaVersion` en el envelope permite versionar. Se recomienda mantener `schemaVersion` como `major.minor` donde `major` se incrementa si hay cambios incompatibles (eliminación de campos obligatorios) y `minor` si se añaden campos opcionales.

4. **Latencia de red entre Colombia y Florida:**
   Los eventos generados en locales de Florida (US) viajan a la nube de Supabase (probablemente US East). Los generados en Colombia (CO) pueden tener latencia adicional. **Mitigación:** el campo `duration_ms` de `api_latency_recorded` ya captura el tiempo total; monitorear la diferencia de latencia entre CO y US para decidir si se necesita un endpoint regional.

5. **Pérdida de eventos en frontend:**
   Si el usuario cierra el navegador antes de que un evento de frontend se haya enviado (ej. `section_abandoned` en `beforeunload`), el evento se pierde. Los navegadores modernos no garantizan que `sendBeacon()` se complete. **Mitigación:** usar `navigator.sendBeacon()` para eventos críticos en `beforeunload`; para el resto, aceptar pérdida marginal (<1%).

#### Exclusiones: eventos considerados y descartados

| Evento descartado | Razón |
|-------------------|-------|
| `user_location_gps` (geolocalización exacta) | No hay necesidad de negocio. La ubicación del local ya está determinada por `location_id`. GPS del usuario sería invasivo y no añade valor: el operador está en el local. |
| `employee_clock_in` / `employee_clock_out` (control de horario) | Pertenece al dominio de RRHH, no al sistema de inventario. Mezclar dominios crea acoplamiento innecesario. |
| `supplier_payment_processed` (pago a proveedor) | Pertenece al dominio financiero/contable. El sistema de inventario registra la orden de entrada, no el pago. |
| `customer_order_placed` (pedido de cliente en mostrador) | Es un evento del POS (punto de venta), no del inventario. El inventario solo ve el consumo de ingredientes. |
| `database_query_timing` (timing de cada consulta SQL) | Volumen altísimo (cada query individual). No hay un consumidor de negocio directo. Si se necesita, se implementa con herramientas especializadas (PgBouncer, RDS Performance Insights). |
| `browser_console_errors` (errores de consola del navegador del operador) | Alto volumen, bajo valor. Los errores relevantes ya se capturan vía `frontend_error_occurred`. |
| `ui_element_clicked` (cada clic del usuario) | Esencialmente un "heatmap" de clicks. No hay decisión de negocio vinculada. Instrumentar esto añadiría ruido sin hipótesis clara. |
| `page_scroll_depth` (profundidad de scroll) | Misma razón que `ui_element_clicked`. Sin hipótesis de negocio que lo justifique. |
| `session_recording` (grabación de pantalla del operador) | Costoso de almacenar, riesgoso para privacidad (el operador podría estar viendo datos del local o del cliente). No hay equipo para revisar grabaciones. |
| `stock_count_verified` (conteo físico de inventario) | Es un proceso offline que no interactúa con el sistema digital. Si se digitaliza en el futuro, se reconsiderará. |

#### Exclusiones por privacidad

| Dato no capturado | Justificación |
|-------------------|---------------|
| IP completa | Solo se infiere y almacena el país (`ip_country`). La IP nunca persiste. |
| Email completo | Solo se almacena el dominio (`email_domain`). El email es PII según la Ley 1581 de Colombia (Protección de Datos) y CCPA en California. |
| Nombres de empleados | No se incluyen en `properties`. El `userId` del envelope es un seudónimo no reversible. |
| Datos de clientes | El sistema de inventario no debe cruzar datos de clientes. Cualquier referencia a un cliente en una incidencia (`customer_complaint`) se registra solo como categoría, sin nombre ni contacto. |
| Stack traces completos | Truncados a 200 caracteres y saneados. Los stack traces pueden contener nombres de variables, rutas de archivos y URLs que filtren información del sistema o del usuario. |
| Tokens JWT | Nunca se registran. El `userId` se extrae del token, pero el token mismo no persiste. |

#### Exclusiones por costo

| Dato no capturado | Justificación |
|-------------------|---------------|
| Every database query | El volumen de queries en 14 locales generaría terabytes/mes. No hay un consumidor de negocio para este dato. |
| Session recordings | El almacenamiento de video/reenactment de sesiones cuesta >$100/mes por local para una solución SaaS. No hay ROI demostrado. |
| Full request/response bodies | El payload de las peticiones (ej. lista completa de productos) puede ser grande y repetitivo. Solo se capturan los campos del allowlist. |

---

Esta sección completa la Fase 3 del plan de telemetría. Con la estrategia de entrega definida, el plan está listo para la implementación empezando por la instrumentación de los 6 eventos obligatorios (Fase 1 de priorización) y su envío al almacenamiento.
