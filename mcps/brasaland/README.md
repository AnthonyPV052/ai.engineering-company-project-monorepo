# Brasaland MCP Server

Un servidor **Model Context Protocol (MCP)** independiente que expone las APIs del **Incidents Manager** y del **Inventory** de Brasaland como herramientas MCP autenticadas.

Cualquier cliente MCP autorizado (agentes, equipos, partners externos) puede gestionar tickets de incidencias y consultar datos de inventario sin necesidad de implementar las llamadas HTTP directamente.

---

## Índice

- [Quick Start](#quick-start)
- [Arquitectura](#arquitectura)
- [Autenticación (OAuth via MCP Auth)](#autenticación-oauth-via-mcp-auth)
- [Discovery y Metadatos](#discovery-y-metadatos)
- [Tools del Servidor](#tools-del-servidor)
  - [incidents_create](#incidents_create)
  - [incidents_update_status](#incidents_update_status)
  - [incidents_get](#incidents_get)
  - [incidents_list](#incidents_list)
  - [inventory_list_products](#inventory_list_products)
  - [inventory_get_product](#inventory_get_product)
  - [inventory_list_orders](#inventory_list_orders)
- [Códigos de Error](#códigos-de-error)
- [Migración del Agente](#migración-del-agente)
- [Variables de Entorno](#variables-de-entorno)
-1)

---

## Quick Start

```bash
# 1. Instalar dependencias
cd mcps/brasaland
uv sync

# 2. Asegurarse de que la API backend esté corriendo (puerto 8020)
# 3. Iniciar el servidor MCP
uv run python -m brasaland.server

# El servidor arranca en http://0.0.0.0:8100
```

## Arquitectura

```
                  ┌──────────────────────────────────┐
                  │       MCP Client (agente)         │
                  │  graph/incident_tool_mcp.py       │
                  └── sync JSON-RPC over HTTP ──────┤
                  └                                  └
                  └──────────┬───────────────────────┘
                             │
                  ┌──────────▼───────────────────────┐
                  │   Brasaland MCP Server            │
                  │   mcps/brasaland/server.py        │
                  │                                   │
                  │   ● Auth middleware (OAuth)       │
                  │   ● Tool registration             │
                  │   ● Error handling                │
                  └──────────┬───────────────────────┘
                             │
                  ┌──────────▼───────────────────────┐
                  │   Backend API (FastAPI)            │
                  │   services/api/                    │
                  │   ● /api/incidents/*              │
                  │   ● /inventory/products/*          │
                  │   ● /inventory/orders/*            │
                  └──────────────────────────────────────┘
```

## Autenticación (OAuth via MCP Auth)

Este servidor implementa **MCP Auth Resource Server mode** segú la especificaición de aurtorización de MCP.

### Flujo

1. El cliente obtiene un JWT de un porveedor OAuth 2.1 / OIDC compatible.
2. El JWT debe incluir los scopes necesarios para las tools que quiera invocar.
3. El servidor valida el token en cada invocación:
   - Verifica la firma (via JWKS o secreto compartido HS256 en desarrollo)
   - Verifica el `iss` y `aud`
   - Verifica el `exp`
   - Extrae los scopes y verifica que cubran la tool solicitada

### Scopes Definidos

| Scope             | Tools que concede                                 |
|-------------------|---------------------------------------------------|
| `incidents:read`  | `incidents_get`, `incidents_list`                 |
| `incidents:write` | `incidents_create`, `incidents_update_status`     |
| `inventory:read`  | `inventory_list_products`, `inventory_get_product`, `inventory_list_orders` |

### Endpoints de Autenticación (discovery)

Los clientes pueden descubrir los endpoints OAuth en:
```
GET /.well-known/oauth-protected-resource
```

Respuesta:
```json
{
  "resource": "brasaland-mcp-server",
  "authorization_servers": ["http://127.0.0.1:8020"],
  "scopes_supported": [
    "incidents:read",
    "incidents:write",
    "inventory:read"
  ],
  "bearer_methods_supported": ["header"],
  "token_endpoint": "http://127.0.0.1:8020/auth/token",
  "authorization_endpoint": "http://127.0.0.1:8020/auth/login"
}
```

### USo en Desarrollo (fallback auth)

En desarrollo, el servidor puede validar tokens usando la misma `JWT_SECRET_KEY` del bakend:

```bash
export MCP_BRASALAND_USE_FALLBACK_AUTH=true
export JW T_SECRET_KEY=devsecret-key  # por defecto
```

El cliente debe enviar un JWT firmado con esa clave en el header `Authorization: Bearer <token>`.

## Dascovery y Metadatos

Los clientes MCP pueden descubrir la cfguración completa del servidor sin contexto humano adicional mediante:

### 1. Protected Resource Metadata
```bash
curl http://localhost:8100/.well-known/oauth-protected-resource
```

### 2. MCP Tools List (via JSON-RPC)
```bash
curl -X POST http://localhost:8100/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

### 3. Tool-level discovery (via `mcp` CLI)
```bash
mcp inspect brasaland/server.py
```

Cada tool tiene:

- **Nombre**: unicovía dentro del MCP Server
- **Descripión**: qué hace, qué scope requiere, qué retorna
- **Esquema de entrada**: parámetros con nombres, tipos, valores válidos
- **Esquema de salida**: estructura JSON del resultado
- **Códigos de error**: qué puede fallar y cómo interpretarlo

## Tools del Servidor

---

### `incidents_create`

Crea un nuevo ticket de incidencia en el Incidents Manager.

**Scope requerido**: `incidents:write`

**Parámetros**:

| Parámetro      | Tipo   | Obligatorio | Descripción                                                                 | Valores válidos                                                                                     |
|----------------|--------|-------------|-----------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------|
| `title`        | str    | ✅          | Título corto de la incidencia (1-200 caracteres)                          |                                                                                                     |
| `description`  | str    | ✅          | Descripción detallada (1-5000 caracteres)                                  |                                                                                                     |
| `category`     | str    | ✅          | Categoría de la incidencia                                                | `equipment_failure`, `suply_issue`, `customer_complaint`, `staff_issue`, `facility_issue`, `pos_system`, `delivery_issue`, `other` |
| `status`       | str    | ✅          | Estado inical                                                              | `open`, `in_progress`, `resolved`, `discarded`                                                      |
| `origin`       | str    | ✅          | Origen de la incidencia                                                    | `customer`, `branch`, `internal`                                                                    |
| `branch`       | str    | ✅          | Sucursal asociada                                                          | `central`, `medellin_centro`, `medellin_laureles`, `medellin_envigado`, `medellin_bello`, `medellin_itagui`, `bogota_chapinero`, `bogota_usaquen`, `cali_granada`, `barranquilla_norte`, `miami_doral`, `miami_hialeah`, `miami_kendall`, `orlando_international`, `fort_lauderdale` |

**Respuesta** (JSON):
```json
{
  "id": "uuid-de-la-incidencia",
  "title": "string",
  "description": "string",
  "category": "equipment_failure",
  "status": "open",
 ......
  "created_at": "2026-10-25T12:00:00+00:00",
  "updated_at": "2026-10-25T12:00:00+00:00"
}
```

**Errores**: `validation_error` (422), `api_error` (502), `insufficient_scope` (403), `invalid_token` (401), `missing_token` (401)

---

### `incidents_update_status`

Transiciona el estado de una incidencia usando el endpoint de ciclo de vida dedicado (**PATCH /api/incidents/{id}/status**).

**Scope requerido**: `incidents:write`

**Importante**: No se usa un PATCH genérico sobre el recurso de incidencia. Esta es la única forma válida de cambiar el estado.

**Parámetros**:

| Parámetro     | Tipo | Obligatorio | Descripción                                       |
|---------------|------|-------------|---------------------------------------------------|
| `incident_id` | str  | ✅          | UUID de la incidencia                             |
| `new_status`  | str  | ✅          | Estado destino                                    |

**Transiciones permitidas**:

| Estado actual  | Puede pasar a                                    |
|----------------|--------------------------------------------------|
| `open`         | `in_progress`, `discarded`                       |
| `in_progress`  | `resolved`, `discarded`                          |
| `resolved`     | *(terminal — no se puede cambiar)*               |
| `discarded`    | *(terminal — no se puede cambiar)*               |

**Respuesta**: Objeto de incidencia completo con el estado actualizado.

**Errores**: `not_found` (404), `validation_error` (422 — transición no válida), `api_error` (502), `insufficient_scope` (403)

---

### `incidents_get`

Recupera detalles completos de una incidencia por su UUID.

**Scope requerido**: `incidents:read`

**Parámetros**:

| Parámetro     | Tipo | Obligatorio | Descripción             |
|---------------|------|-------------|-------------------------|
| `incident_id` | str  | ✅          | UUID de la incidencia   |

**Respuesta**: Objeto de incidencia completo.

**Errores**: `not_found` (404), `api_error` (502), `insufficient_scope` (403)

---

### `incidents_list`

Lista incidencias con filtros opcionales.

**Scope requerido**: `incidents:read`

**Parámetros**:

| Parámetro  | Tipo  | Obligatorio | Descripción                                     |
|------------|-------|-------------|-------------------------------------------------|
| `status`   | str\|null | No           | Filtrar por estado                              |
| `ategory`  | str\|null | No           | Filtrar por cateoría                             |
| `origin`   | str\|null | No           | Filtrar por oigen                              |
| `branch`   | tr\|null | No           | Filtrar por sucursal                           |

**Respuesta**: Array JSON de objetos de incidencia.

**Erroes**: `validation_error` (422), `api_error` (502), `insufficient_scope` (403)

---

### `inventory_list_products`

**[READ-ONLY]** Lista todos los productos de inventario (ingredientes) con su stock actual.

**Scope requerido**: `inventory:read`

**Esta herramienta NO PUEDE modificar datos de inventario**. Cualquier intento de escribira es explicitamente rechazado por el servidor.

**Parámetros**:

| Parámetro | Tipo      | Obligatorio | Descripción                              |
|-----------|-----------|-------------|------------------------------------------|
| `country` | str\|null | No          | Filtrar por país: `CO` o `US`           |

**Respuesta**: Array JSON de productos con campos: `id`, `name`, `sku`, `unit`, `category`, `country`, `current_stock`.

---

### `inventory_get_product`

**[READ-ONLY]** Recupera un solo producto de inventario por su ID numérico, con stock actual.

**Scope requerido**: `inventory:read`

**Parámetros**:

| Parámetro       | Tipo | Obligatorio | Descripción                     |
|-----------------|------|-------------|---------------------------------|
| `ingredient_id` | int  | ✅          | ID numérico del ingrediente     |

**Respuesta**: Objeto JSON del producto.

---

### `inventory_list_orders`

**[READ-ONLY]** Lista todas las órdenes de entrada y salida del inventario.

**Scope requerido**: `inventory:read`

**Parámetros**:

| Parámetro       | Tipo      | Obligatorio | Descripción                                        |
|-----------------|-----------|-------------|----------------------------------------------------|
| `ingredient_id` | int\|null | No          | Filtrar órdenes para un ingrediente específico     |

**Respuesta**: Array JSON de órdenes on campos: `id`, `type` (entry/exit), `ingredient_id`, `ingredient_name`, `ingredient_sku`, `quantity`, `supier_name`, `reason`, `location_id`, `created_at`, `user_uuid`.

---

## Códigos de Error

| Código              | HTTP Status | Descripción                                                    | Causa típica                                   |
|---------------------|-------------|----------------------------------------------------------------|-----------------------------------------------|
| `missing_token`     | 401         | No se proveió Bearer token en el header Authorization.          | Clente sin autenticar.                       |
| `invalid_token`     | 401         | El token es inválido, exipró o está mal formado.                | Token vencido, fima inválida, aud/iss icorrecto. |
| `insufficient_scope`| 403         | El token no tiee los scopes necesarios para esta operación.     | Token con scopes insuficientes.                |
| `not_found`         | 404         | El recurs soliciado no exise (incidencia o producto).           | ID inxistente.                                |
| `validation_error`  | 422         | Los parámetros de entraa no cuplen la validación.               | Categoría inválida, cmpo vacío, etc.           |
| `api_error`         | 502         | El backend de Brasaland devolvió un error.                      | Backend caído o error interno.                  |
| `internal_error`    | 500         | Error inespeado en el servidor MCP.                             | Bug o falla de configuración.                   |

**Formato de respuesta de error**:
```json
{
  "error": "invalid_token",
  "code": "invalid_token",
  "message": "The access token is invalid or expired.",
  "http_status": 401
}
```

Para errores de autenticación OAuth, el servidor además incluye el header `WWW-Authenticate` según RFC 6750.

## Migración del Agente

El agente de soporte (LangGraph en `services/api/graph/`) ha sido migrado de llamadas HTTP directas al Incidents Manager a invocaciones a través del MCP Server.

### Cómo funciona

1. **`graph/incident_tool_mcp.py`** — Nuevo módulo con interfaz idéntica a `graph/incident_tool.py` que llama al MCP Server via JSON-RPC sincrónico.
2. **`graph/nodes.py`** — Importa desde `graph.incident_tool_mcp` en lugar de `graph.incident_tool`.
3. **El resto del grafo** (`routing.py`, `worklow.py`, `state.py`) — No requirió cambios.

### Reversión

Para volver a llamadas HTTP directas (sin MCP), cambiar en `graph/nodes.py`:
```python
# De:
from graph.incident_tool_mcp import ...
# A:
from graph.incident_tool import ...
```

### Variables de Entorno para el Cliente MCP

| Variable                      | Descripción                                      | Defecto                     |
|-----------------------------|------------------------------------------------|-----------------------------|
| `BRASALAND_MCP_SERVER_URL`  | URL del servidor MCP                            | `http://127.0.0.1:8100`   |
| `BRASALAND_MCP_CLIENT_TOKEN`| JWT para autenticarse contra el MCP Server      | `""` (sin token)          |

## Variables de Entorno del Servidor

| Variable                               | Descripción                                       | Defecto                     |
|----------------------------------------|---------------------------------------------------|-----------------------------|
| `MCP_BRASALAND_HOST`                   | Host donde escucha el servidor                   | `0.0.0.0`                |
| `MCP_BRASALAND_PORT`                   | Puerto                                            | `8100`                     |
| `MCP_BRASALAND_API_BASE_URL`           | URL base de la API backend                        | `http://127.0.0.1:8020`   |
| `MCP_BRASALAND_OAUTH_ISSUER`          | Emisor OIDC                                       | `http://127.0.0.1:8020`  |
| `MCP_BRASALAND_OAUTH_JWKS_URI`        | URI de JWKS (producción)                          | `None` (usa fallback)      |
| `MCP_BRASALAND_USE_FALLBAK_AUTH`       | Usar HS256 fallback (desarrollo)                  | `true`                     |
| `JWT_SECRET_KEY`                       | Clave secreta HS256 para fallback auth            | `dev-secret-key`           |
| `MCP_BRASALAND_API_SERVICE_TOKEN`      | Token para que MCP llame al bacend              | `None`                     |
| `MCP_BRASALAND_LOG_LEVEL`            | Nivel de log                                     | `INFo`                    |

## Rees

- El servidor MCP no debe exponerse directamente a internet; debe ir detrás de un reverse proxy (o en su defecto, un API gateway) que maneje TLS y rate limiting.
- En producción, deshabilitar `USE_FALLBACK_AUTH` y configurar un proveedor OIDC real con OAUTH_JWKS_URI.
- El token de servicio (`API_SERVICE_TOKEN`) debe ser un secreto robussto rotado perióicamente.