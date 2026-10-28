## Estado Actual

### Almacenamiento

Todos los eventos de telemetría se almacenan en la tabla `telemetry_events` dentro de **Supabase (PostgreSQL)**.

| Campo | Tipo | Descripción |
|---|---|---|
| `id` | `BIGINT` (PK, auto) | Identificador único del registro |
| `event_type` | `TEXT` NOT NULL | Nombre del evento según taxonomía `entidad_accion` |
| `timestamp` | `TIMESTAMP` NOT NULL | Momento exacto en que ocurrió el evento (UTC) |
| `service` | `TEXT` NOT NULL | Origen del evento (`backend` o `frontend`) |
| `tags` | `JSONB` NOT NULL | Propiedades específicas del evento + metadatos del envelope |
| `received_at` | `TIMESTAMP` NOT NULL | Momento en que el servidor recibió el evento |
| `user_id` | `TEXT` NULLABLE | Identificador del usuario que generó el evento |
| `session_id` | `TEXT` NULLABLE | Identificador de sesión del usuario |

La tabla se crea automáticamente al arrancar la aplicación mediante `init_db()` en `services/api/database.py`.

### Eventos capturados hasta `2026-09-02`

Basado en datos reales del endpoint `GET /telemetry/report`:

| Tipo de evento | Conteo (últ. 7d) | Dominio | Origen |
|---|---|---|---|
| `web_vital_recorded` | 114 | rendimiento | frontend |
| `page_visited` | 30 | navegación | frontend |
| `auth_login_attempted` | 5 | autenticación | backend |
| `session_expired` | 4 | autenticación | frontend |
| `demo_valid_event` | 2 | pruebas | - |
| `otro_evento_valido` | 2 | pruebas | - |
| `another_valid_event` | 1 | pruebas | - |
| `inbound_order_created` | 1 | inventario | backend |
| `outbound_order_created` | 1 | inventario | backend |
| `valid_event_in_mixed_batch` | 1 | pruebas | - |

**Nota:** No se han registrado eventos de tipo `api_error_occurred` en los últimos 7 días (`error_rate_by_type: []`).

### Pipeline de ingestión

La ingesta ocurre a través del endpoint `POST /telemetry/events`:

1. El cliente (frontend o backend) envía un lote de eventos en el envelope estándar.
2. Cada evento se valida individualmente contra el modelo Pydantic `TelemetryEvent`:
   - **Válido** → se persiste en `telemetry_events` mediante SQLModel.
   - **Inválido** → se rechaza individualmente sin cancelar el lote.
3. La respuesta devuelve `{"received": N, "stored": M, "rejected": R}`.

El frontend utiliza un batcher con intervalo de 10 segundos y tamaño máximo de 20 eventos por lote, implementado en `uis/website/src/services/telemetry.ts`.

### Pipeline de análisis

El endpoint `GET /telemetry/report` (en `services/api/telemetry/report.py`) ejecuta tres métricas técnicas mediante Pandas:

| Métrica | Eventos fuente | Pregunta técnica |
|---|---|---|
| `events_per_day` | Todos los eventos | ¿Cuántos eventos de cada tipo por día? |
| `error_rate_by_type` | `api_error_occurred` | ¿Qué proporción de errores corresponde a cada tipo? |
| `auth_failure_rate` | `auth_login_attempted` | ¿Qué % de intentos de login fallan cada día? |

El resultado se cachea en memoria con TTL de 60 segundos para evitar recalcular en cada request.

### Reporte actual

```json
{
  "period": {
    "from": "2026-08-26",
    "to": "2026-09-02"
  },
  "metrics": {
    "events_per_day": [
      {"date": "2026-08-31", "event_type": "another_valid_event", "count": 1},
      {"date": "2026-08-31", "event_type": "auth_login_attempted", "count": 4},
      {"date": "2026-08-31", "event_type": "demo_valid_event", "count": 2},
      {"date": "2026-08-31", "event_type": "inbound_order_created", "count": 1},
      {"date": "2026-08-31", "event_type": "otro_evento_valido", "count": 2},
      {"date": "2026-08-31", "event_type": "outbound_order_created", "count": 1},
      {"date": "2026-08-31", "event_type": "page_visited", "count": 18},
      {"date": "2026-08-31", "event_type": "session_expired", "count": 2},
      {"date": "2026-08-31", "event_type": "valid_event_in_mixed_batch", "count": 1},
      {"date": "2026-08-31", "event_type": "web_vital_recorded", "count": 72},
      {"date": "2026-09-01", "event_type": "auth_login_attempted", "count": 1},
      {"date": "2026-09-01", "event_type": "page_visited", "count": 12},
      {"date": "2026-09-01", "event_type": "session_expired", "count": 2},
      {"date": "2026-09-01", "event_type": "web_vital_recorded", "count": 42}
    ],
    "error_rate_by_type": [],
    "auth_failure_rate": [
      {"date": "2026-08-31", "attempts": 4, "failures": 2, "failure_rate": 0.5},
      {"date": "2026-09-01", "attempts": 1, "failures": 0, "failure_rate": 0}
    ]
  }
}
```

### Brecha de negocio

El reporte técnico `GET /telemetry/report` responde preguntas operativas: **¿cuántos eventos por tipo y por día? ¿qué proporción de errores corresponde a cada tipo? ¿qué % de intentos de login fallan?** Estas métricas son útiles para el equipo de ingeniería, pero no responden a las preguntas de Mariana (CEO) y Felipe (Director de Operaciones):

| El reporte técnico responde → | El reporte de negocio **debe** responder → |
|---|---|
| Volumen de eventos `inbound_order_created` por día | **Costo de compra por local** (suma de costos de cada orden de compra) |
| Conteo de eventos `stock_waste_registered` | **Costo de merma por local** (suma de costos de cada registro de merma) |
| N/A | **Ratio de merma** (costo de merma / costo de compra) |
| N/A | **Frecuencia de quiebre de stock** (conteo de `stock_threshold_triggered`) |
| N/A | **Frecuencia de alertas de precio** (conteo de `ingredient_price_variance_detected`) |

La brecha es clara: el pipeline actual entrega **conteos de eventos**, no **agregaciones monetarias o de negocio por local y por semana**. El pipeline de desempeño de negocio cierra esta brecha transformando eventos crudos en KPIs accionables para la operación.

---

## Fase 2 — Diseño del Pipeline

### A) Propósito del pipeline

Transformar la telemetría de eventos operativos en el **Reporte Semanal de Costo y Merma por Local** que Mariana (CEO) y Felipe (Director de Operaciones) abren cada lunes sin intervención técnica. Este pipeline calcula los 5 KPIs definidos en `pipeline-context.md` — **costo de compra por local, costo de merma por local, ratio de merma, frecuencia de quiebre de stock, frecuencia de alertas de precio** — a partir de 4 métricas obligatorias de telemetría: `inbound_order_created`, `stock_waste_registered`, `stock_threshold_triggered`, `ingredient_price_variance_detected`.

### B) Formato de extracción

| Propiedad | Valor |
|---|---|
| **Fuente principal** | `telemetry_events` (Supabase PostgreSQL, esquema `public`) |
| **Tablas de dominio adicionales** | Ninguna en v1. Todo dato de origen proviene de `telemetry_events`, filtrado por `event_type` |
| **Formato del payload** | Cada evento es una fila con `event_type`, `timestamp`, `tags` (JSONB), `service`, `user_id`, `session_id`. Los valores de costo y cantidad viajan dentro de `tags` como `properties.unit_cost`, `properties.total_cost`, `properties.quantity`, etc. |
| **Frecuencia de actualización** | Continua — los eventos llegan vía `POST /telemetry/events` desde frontend y backend en tiempo real, con batching cada 10s desde el frontend |
| **Calidad del dato** | Cada evento se valida con Pydantic al ingreso. Los eventos malformados se rechazan individualmente sin afectar el lote. No hay reglas de calidad aguas abajo aún (se asume que lo que llega a `telemetry_events` es válido) |

### C) Diagrama del flujo de datos

```mermaid
flowchart TB
    subgraph Extracción
        A["telemetry_events (Supabase PostgreSQL)"]
        B["SQL: SELECT ... WHERE event_type IN (inbound_order_created, stock_waste_registered, stock_threshold_triggered, ingredient_price_variance_detected)"]
        A --> B
    end

    subgraph Transformación
        C["Pandas DataFrame por cada event_type"]
        D["Agrupar por location_id + week_start"]
        E["Calcular KPIs: total_purchase_cost | total_waste_cost | waste_ratio | stockout_events_count | price_alert_events_count"]
        B --> C --> D --> E
    end

    subgraph Carga
        F["Upsert: reporting.weekly_location_performance (clave: location_id + week_start)"]
        G["GET /reporting/weekly-location-performance (sirve desde la tabla)"]
        E --> F --> G
    end
```

### D) Manejo de actualizaciones y duplicados

| Aspecto | Estrategia |
|---|---|
| **Registros que se actualizan** | No se actualizan registros individuales — el pipeline es **batch semanal y recalculado**. Cada corrida vuelve a leer `telemetry_events` desde cero y recalcula todas las filas de la semana objetivo, sobrescribiendo lo que haya en `reporting.weekly_location_performance`. |
| **Evitar duplicados** | **Upsert** con clave única `(location_id, week_start)`. Si el pipeline se ejecuta dos veces para la misma semana (por fallo parcial o reintento), el `ON CONFLICT (location_id, week_start) DO UPDATE` reemplaza los valores anteriores sin generar filas duplicadas. |
| **Capa donde se aplica** | En la base de datos destino — PostgreSQL `INSERT ... ON CONFLICT ... DO UPDATE` dentro del flow de carga. No se necesita deduplicación en memoria. |

### E) Tablas de destino y endpoints

#### Tabla destino

```sql
create table reporting.weekly_location_performance (
  id uuid primary key default gen_random_uuid(),
  location_id text not null,
  country text not null,
  week_start date not null,
  total_purchase_cost numeric not null default 0,
  total_waste_cost numeric not null default 0,
  waste_ratio numeric not null default 0,
  stockout_events_count integer not null default 0,
  price_alert_events_count integer not null default 0,
  currency text not null,
  computed_at timestamptz not null default now(),
  unique (location_id, week_start)
);
```

#### Endpoints en `services/reporting/`

| Endpoint | Método | Función/Flow que invoca | Propósito |
|---|---|---|---|
| `GET /reporting/kpis` | `GET` | `get_weekly_kpis()` en `data/pipelines/business_performance.py` — consulta `reporting.weekly_location_performance` y opcionalmente filtra por `location_id` | Feed de datos para el dashboard: KPIs de una semana (por defecto la más reciente) para todos los locales |
| `GET /reporting/status` | `GET` | `get_pipeline_status()` en `data/pipelines/business_performance.py` — consulta `reporting.pipeline_runs` | Estado y metadata de la última corrida del pipeline |
| `POST /reporting/run` | `POST` | Dispara `run_business_performance_pipeline()` en `data/pipelines/business_performance.py` | Ejecución manual del pipeline completo (extracción → transformación → carga) |

> **Nota sobre nomenclatura:** Los endpoints definidos en `pipeline-context.md` sección 6 (`/weekly-location-performance`, `/pipeline-runs/latest`, `/pipeline-runs`) son los nombres originales. En esta implementación se adoptan los nombres `/kpis`, `/status`, `/run` por ser más semánticos y consistentes con el diseño de la Fase 5. Ambos conjuntos de rutas son equivalentes en funcionalidad.

### F) Reglas de diseño obligatorias

1. ❌ **Este pipeline no escribe en `telemetry_events`.** Lee exclusivamente en modo `SELECT` de esa tabla. Nunca realiza `INSERT`, `UPDATE` o `DELETE` contra ella.
2. ❌ **No modifica `services/telemetry/analysis.py` ni `GET /telemetry/report`.** El pipeline de análisis técnico (métricas Pandas con TTL cache) y el pipeline de negocio (KPIs semanales con upsert) son independientes y conviven sin acoplarse.
3. ✅ **Solo se permiten campos aditivos si el CONTEXT los exige.** Los 5 KPIs (sección 2 del `pipeline-context.md`) son la lista completa de campos calculados. No se agregan métricas exploratorias ni derivados no solicitados.
4. ✅ **El pipeline es idempotente.** Ejecutar la misma corrida dos veces para la misma semana produce exactamente los mismos valores en `reporting.weekly_location_performance`.
5. ✅ **Separación de monedas.** `total_purchase_cost` y `total_waste_cost` se almacenan en la moneda local del local (`COP` o `USD`) según el campo `currency`. No se convierten ni se suman entre países.

---

## Fase 3 — Resiliencia e Idempotencia

### 1) Estrategia de idempotencia

El pipeline garantiza idempotencia mediante **upsert basado en la clave única `(location_id, week_start)`** en la tabla `reporting.weekly_location_performance`:

| Aspecto | Detalle |
|---|---|
| **Clave de deduplicación** | `(location_id, week_start)` — constraint `UNIQUE` en la tabla destino |
| **Capa donde se aplica** | **Carga** (base de datos destino). No se hace deduplicación en memoria ni en transformación. |
| **Mecanismo** | `INSERT INTO reporting.weekly_location_performance (...) VALUES (...) ON CONFLICT (location_id, week_start) DO UPDATE SET total_purchase_cost = EXCLUDED.total_purchase_cost, total_waste_cost = EXCLUDED.total_waste_cost, waste_ratio = EXCLUDED.waste_ratio, stockout_events_count = EXCLUDED.stockout_events_count, price_alert_events_count = EXCLUDED.price_alert_events_count, computed_at = now()` |
| **¿Qué ocurre en la segunda corrida tras un fallo?** | El pipeline se ejecuta completo de nuevo (extracción → transformación → carga). Como la lectura de `telemetry_events` cubre toda la semana objetivo (sin estado incremental), los datos son los mismos. El `ON CONFLICT` sobrescribe la fila existente con valores idénticos si no hay nuevos eventos, o actualiza si algún evento llegó entre la primera corrida fallida y la segunda. El resultado es siempre el mismo para un mismo conjunto de eventos de origen. |
| **Fallo a medio escribir** | Si la carga falla después de insertar algunas filas pero antes de completar el lote, la tabla destino queda con datos parciales. La segunda corrida simplemente sobrescribe esas filas vía upsert, dejando la tabla completa y consistente. |
| **Fallo en extracción o transformación** | No hay efecto en la tabla destino porque nunca se llega a la carga. La segunda corrida empieza desde cero sin consecuencias. |

### 2) Log de ejecución

Cada ejecución del pipeline registra una fila en `reporting.pipeline_runs` con la siguiente estructura:

| Campo | Tipo | Justificación de auditoría |
|---|---|---|
| `id` | `UUID` (PK) | Identificador único de la corrida |
| `pipeline_name` | `TEXT NOT NULL` | Nombre del pipeline (`business_performance`) — permite tener varios pipelines compartiendo la misma tabla |
| `started_at` | `TIMESTAMPTZ NOT NULL` | Marca temporal de inicio — permite medir duración y ordenar corridas |
| `finished_at` | `TIMESTAMPTZ` | Marca temporal de finalización — `NULL` mientras la corrida está en ejecución o falló antes de registrar el fin |
| `status` | `TEXT NOT NULL` | Estado final: `completed`, `failed`, `running` — permite filtrar fallos y alertar |
| `rows_processed` | `INTEGER DEFAULT 0` | Número de filas en `telemetry_events` que entraron al pipeline en esta corrida |
| `rows_upserted` | `INTEGER DEFAULT 0` | Número de filas escritas/actualizadas en `reporting.weekly_location_performance` |
| `week_start` | `DATE NOT NULL` | Semana objetivo del pipeline — permite saber qué semana se procesó |
| `error_message` | `TEXT` | Mensaje de error si `status = failed` — primera línea de debugging sin entrar a logs del sistema |
| `triggered_by` | `TEXT DEFAULT 'manual'` | Quién o qué disparó la corrida (`manual`, `scheduler`, `webhook`) — trazabilidad de origen |

**Tabla de destino del log:**

```sql
create table reporting.pipeline_runs (
  id uuid primary key default gen_random_uuid(),
  pipeline_name text not null,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  status text not null default 'running',
  rows_processed integer default 0,
  rows_upserted integer default 0,
  week_start date not null,
  error_message text,
  triggered_by text default 'manual'
);
```

### 3) Recuperabilidad

| Escenario | Mecanismo de recuperación |
|---|---|
| **Caída de base de datos durante extracción** | El pipeline lanza excepción de conexión. Como no se ha escrito nada en la tabla destino, no hay estado inconsistente. Se reintenta desde el flow de Prefect con backoff exponencial. |
| **Caída de base de datos durante carga** | Si la conexión se pierde a mitad del upsert, algunas filas pueden haber quedado escritas. Al recuperarse la base de datos, la siguiente corrida del pipeline sobrescribe esas filas vía upsert. Semánticamente es idempotente: mismo `(location_id, week_start)` → mismo resultado. |
| **Caída del proceso Python (pipeline abortado)** | No hay checkpoint intermedio porque el pipeline es **todo-o-nada por semana**. No se persiste estado parcial. Al reiniciar, el flow de Prefect se ejecuta completo desde extracción. |
| **Checkpoint que persiste el pipeline** | El único checkpoint es la fila en `reporting.pipeline_runs` con `status = 'running'` al inicio y `status = 'completed'` o `failed'` al final. Si la corrida se cae antes de escribir el `completed`, el próximo operador o scheduler ve `running` colgado y puede decidir reintentar. |
| **Retoma tras caída** | El pipeline no necesita retomar desde un punto medio — es batch semanal completo. Siempre lee `telemetry_events` desde cero para la semana objetivo y recalcula. La tabla `pipeline_runs` permite detectar corridas fallidas, pero la lógica de negocio no depende de ese estado. |

---

## Fase 4 — Mapeo a Prefect

### 1) Flow principal

```python
from prefect import flow, task
from prefect.tasks import task_input_hash
from datetime import date, timedelta
import pandas as pd
from sqlalchemy import create_engine, text

# ─── Blocks de configuración ───────────────────────────────────────
# Los siguientes valores se resuelven desde Prefect blocks en lugar de
# variables de entorno o secretos locales. Ver sección 4) Blocks.
# -------------------------------------------------------------------

@flow(name="business_performance_pipeline")
def run_business_performance_pipeline(week_start: date | None = None):
    """
    Flow principal del pipeline de desempeño de negocio.
    Calcula los 5 KPIs semanales y los escribe en reporting.weekly_location_performance.
    
    Args:
        week_start: Lunes de la semana ISO a procesar. Por defecto, la semana más
                    reciente con datos en telemetry_events.
    """
    source_conn = get_source_connection()
    target_conn = get_target_connection()
    
    events = extract_events(source_conn, week_start)
    kpis = transform_kpis(events, week_start)
    load_kpis(target_conn, kpis, week_start)
    
    log_pipeline_run(target_conn, week_start, len(kpis))
```

### 2) Tres tasks mínimas

```python
@task(
    name="extract_events",
    description="Extrae eventos de telemetry_events filtrados por event_type y semana",
    retries=2,
    retry_delay_seconds=30,
    cache_key_fn=task_input_hash,
    cache_expiration=timedelta(hours=1)
)
def extract_events(source_conn, week_start: date):
    """
    Task de extracción.
    
    Query SQL que selecciona solo los event_type relevantes para los KPIs:
    - inbound_order_created → total_purchase_cost
    - stock_waste_registered → total_waste_cost
    - stock_threshold_triggered → stockout_events_count
    - ingredient_price_variance_detected → price_alert_events_count
    
    Filtra por semana ISO: timestamp BETWEEN week_start AND week_start + 6 days.
    
    Retries: 2 reintentos con 30s de espera para tolerar caídas transitorias.
    Cache: 1 hora (para que corridas repetidas del mismo week_start no 
           golpeen la base de datos si los datos no han cambiado).
    """
    query = text("""
        SELECT 
            event_type,
            timestamp,
            location_id,
            tags->'properties'->>'unit_cost' as unit_cost,
            tags->'properties'->>'total_cost' as total_cost,
            tags->'properties'->>'quantity' as quantity,
            tags->>'country' as country
        FROM telemetry_events
        WHERE event_type IN (
            'inbound_order_created',
            'stock_waste_registered',
            'stock_threshold_triggered',
            'ingredient_price_variance_detected'
        )
        AND timestamp >= :week_start
        AND timestamp < :week_end
    """)
    
    df = pd.read_sql(query, source_conn, params={
        "week_start": week_start,
        "week_end": week_start + timedelta(days=7)
    })
    
    return df


@task(
    name="transform_kpis",
    description="Agrupa eventos por location_id y calcula los 5 KPIs semanales"
)
def transform_kpis(events: pd.DataFrame, week_start: date):
    """
    Task de transformación.
    
    Toma el DataFrame plano de eventos y produce un DataFrame agregado
    con una fila por location_id + week_start y los 5 KPIs calculados.
    
    Operaciones:
    1. Extraer location_id de cada evento (desde tags).
    2. Particionar por event_type.
    3. Para cada grupo: sumar costos (inbound/stock_waste) o contar eventos
       (stock_threshold / ingredient_price_variance).
    4. Calcular waste_ratio = total_waste_cost / total_purchase_cost.
    5. Asignar currency según country (COP/USD).
    """
    if events.empty:
        return pd.DataFrame(columns=[
            "location_id", "country", "week_start",
            "total_purchase_cost", "total_waste_cost", "waste_ratio",
            "stockout_events_count", "price_alert_events_count", "currency"
        ])
    
    # Compras
    purchases = events[events.event_type == "inbound_order_created"]
    purchase_agg = purchases.groupby(["location_id", "country"]).agg(
        total_purchase_cost=("total_cost", "sum")
    ).reset_index() if not purchases.empty else pd.DataFrame()
    
    # Merma
    waste = events[events.event_type == "stock_waste_registered"]
    waste_agg = waste.groupby(["location_id", "country"]).agg(
        total_waste_cost=("total_cost", "sum")
    ).reset_index() if not waste.empty else pd.DataFrame()
    
    # Quiebres de stock
    stockouts = events[events.event_type == "stock_threshold_triggered"]
    stockout_agg = stockouts.groupby(["location_id", "country"]).size().reset_index(
        name="stockout_events_count"
    ) if not stockouts.empty else pd.DataFrame()
    
    # Alertas de precio
    price_alerts = events[events.event_type == "ingredient_price_variance_detected"]
    price_alert_agg = price_alerts.groupby(["location_id", "country"]).size().reset_index(
        name="price_alert_events_count"
    ) if not price_alerts.empty else pd.DataFrame()
    
    # Merge de todos los aggregates
    kpis = purchase_agg.merge(waste_agg, on=["location_id", "country"], how="outer")
    kpis = kpis.merge(stockout_agg, on=["location_id", "country"], how="outer")
    kpis = kpis.merge(price_alert_agg, on=["location_id", "country"], how="outer")
    
    # Rellenar nulos
    kpis = kpis.fillna(0)
    
    # Calcular ratio de merma
    kpis["waste_ratio"] = kpis.apply(
        lambda row: row["total_waste_cost"] / row["total_purchase_cost"]
        if row["total_purchase_cost"] > 0 else 0.0,
        axis=1
    )
    
    # Asignar moneda
    kpis["currency"] = kpis["country"].map({"CO": "COP", "US": "USD"}).fillna("COP")
    kpis["week_start"] = week_start
    
    return kpis


@task(
    name="load_kpis",
    description="Escribe los KPIs en reporting.weekly_location_performance mediante upsert"
)
def load_kpis(target_conn, kpis: pd.DataFrame, week_start: date):
    """
    Task de carga.
    
    Toma el DataFrame de KPIs y ejecuta un upsert en 
    reporting.weekly_location_performance con ON CONFLICT DO UPDATE.
    
    También registra la corrida en reporting.pipeline_runs.
    
    No tiene reintentos — si falla, el flow completo se reintenta desde
    extracción gracias a la idempotencia del upsert.
    """
    from sqlalchemy import text
    
    if kpis.empty:
        return
    
    upsert_sql = text("""
        INSERT INTO reporting.weekly_location_performance 
            (location_id, country, week_start, 
             total_purchase_cost, total_waste_cost, waste_ratio,
             stockout_events_count, price_alert_events_count, currency,
             computed_at)
        VALUES 
            (:location_id, :country, :week_start,
             :total_purchase_cost, :total_waste_cost, :waste_ratio,
             :stockout_events_count, :price_alert_events_count, :currency,
             now())
        ON CONFLICT (location_id, week_start) DO UPDATE SET
            total_purchase_cost = EXCLUDED.total_purchase_cost,
            total_waste_cost = EXCLUDED.total_waste_cost,
            waste_ratio = EXCLUDED.waste_ratio,
            stockout_events_count = EXCLUDED.stockout_events_count,
            price_alert_events_count = EXCLUDED.price_alert_events_count,
            computed_at = now()
    """)
    
    with target_conn.begin() as tx:
        for _, row in kpis.iterrows():
            tx.execute(upsert_sql, row.to_dict())
```

### 3) States relevantes

| State | Cuándo ocurre | Acción del pipeline |
|---|---|---|
| **`Running`** | Desde que se invoca el flow hasta que termina o falla | El log en `pipeline_runs` se marca con `status = 'running'`. Si el proceso se cae, queda visible como colgado para el operador. |
| **`Completed`** | Todas las tasks terminan sin error | El log se actualiza a `status = 'completed'`, se registra `finished_at` y `rows_upserted`. |
| **`Failed`** | Cualquier task lanza una excepción no recuperable (tras agotar reintentos) | El log se actualiza a `status = 'failed'` con `error_message`. El pipeline puede reintentarse manualmente sin riesgo de duplicación. |
| **`Cached`** (task `extract_events`) | Si se ejecuta el mismo `week_start` dentro de la ventana de cache de 1h | Usa el resultado en cache sin ejecutar SQL. |

### 4) Blocks de configuración

| Block | Tipo | Propósito |
|---|---|---|
| **SupabaseCredentials** | `SQLAlchemyConnector` | Cadena de conexión a Supabase PostgreSQL (`postgresql://user:pass@host:port/db`). Se usa tanto para extraer de `telemetry_events` como para cargar en `reporting.*`. |
| **PipelineSettings** | `JSON` | Configuración del pipeline: `default_week_start` (estratégia de resolución de la semana por defecto), `batch_size` (filas por lote de upsert), `retry_delays`. |
| **Notifications** | `Webhook` | (Opcional) Webhook a Slack/email para alertar cuando `status = 'failed'`. |

### 5) Flow de backfill (opcional)

```python
@flow(name="backfill_weekly_performance")
def backfill_weekly_performance(start_week: date, end_week: date):
    """
    Flow opcional de backfill.
    
    Ejecuta el pipeline principal para cada semana en el rango [start_week, end_week],
    una por una. Útil cuando se incorporan locales nuevos o se corrige data upstream.
    
    Es idempotente: puede ejecutarse múltiples veces sin duplicar datos.
    """
    current = start_week
    while current <= end_week:
        run_business_performance_pipeline(week_start=current)
        current += timedelta(days=7)

### 6) Entrypoint CLI

El pipeline puede ejecutarse directamente desde la terminal sin necesidad de un orquestador Prefect:

```bash
# Ejecutar pipeline para una semana especifica
python -m data.pipelines.pipeline --week-start 2026-08-31

# Ejecutar pipeline para la semana mas reciente (lunes anterior a hoy)
python -m data.pipelines.pipeline

# Con logging detallado
python -m data.pipelines.pipeline --week-start 2026-08-31 --verbose
```

**Frecuencia de ejecucion:** La ejecucion prevista es **semanal, cada lunes a las 06:00 UTC** (antes del inicio de la operacion). El encargado de operaciones (Felipe) debe tener los numeros frescos al llegar. En v1 el disparo es manual via CLI o endpoint `POST /reporting/pipeline-runs`; en v2 se integrara con un scheduler (cron o Prefect schedules).

**Archivo principal:** `data/pipelines/pipeline.py` -- contiene el bloque `if __name__ == "__main__":` que invoca `main()`, la cual parsea argumentos CLI y ejecuta el flow `run_business_performance_pipeline()`.

```python
# Bloque CLI en data/pipelines/pipeline.py:
if __name__ == "__main__":
    main()  # argparse: --week-start, --verbose
```
```

---

## Fase 5 — Integración con la aplicación

### 1) Tres endpoints nuevos en `services/reporting/`

El módulo `services/reporting/` expone tres endpoints REST, todos bajo un router FastAPI separado del módulo de telemetría:

| Endpoint | Método | Propósito | Respuesta |
|---|---|---|---|
| `GET /reporting/status` | `GET` | Estado del pipeline: última corrida, si hay una ejecución en curso, próxima ejecución programada | `{"last_run": {...}, "current": "idle|running", "next_scheduled": "..."}` |
| `POST /reporting/pipeline-runs` | `POST` | Disparo manual del pipeline para una semana específica (o la más reciente por defecto) | `{"status": "accepted", "run_id": "...", "week_start": "..."}` |
| `GET /reporting/weekly-location-performance` | `GET` | Feed de datos para el dashboard: devuelve los KPIs de una semana (por defecto la más reciente), para todos los locales o filtrado por `location_id` | `{"week_start": "...", "locations": [...]}` (mismo formato que `weekly-location-performance`) |

### 2) Qué función o flow llama cada endpoint

| Endpoint | Archivo en `data/pipelines/` | Función/Flow invocada |
|---|---|---|
| `GET /reporting/pipeline-runs/latest` | `data/pipelines/pipeline.py` | `get_pipeline_status()` (en services/reporting/router.py) — función que consulta `reporting.pipeline_runs` y devuelve metadata de la última corrida |
| `POST /reporting/pipeline-runs` | `data/pipelines/pipeline.py` | `run_business_performance_pipeline(week_start=...)` -- flow de Prefect — flow de Prefect que ejecuta todo el pipeline (extracción → transformación → carga). El endpoint devuelve inmediatamente con `"status": "accepted"` mientras el flow corre en segundo plano (o en un thread asíncrono). |
| `GET /reporting/weekly-location-performance` | `data/pipelines/pipeline.py` (via router) | `get_weekly_kpis(week_start=..., location_id=...)` -- consulta directa a `weekly_location_performance` — función que consulta `reporting.weekly_location_performance` y opcionalmente filtra por local |

**Ninguna lógica ETL vive en `services/reporting/`.** Los endpoints son solo una capa de presentación que invoca funciones definidas en `data/pipelines/business_performance.py`. El archivo `services/reporting/main.py` contiene únicamente los routers y la lógica de serialización/respuesta HTTP.

### 3) Separación estricta del módulo de telemetría

| Regla | Justificación |
|---|---|
| ❌ **No se modifica `services/telemetry/analysis.py`** | Las tres funciones `events_per_day()`, `error_rate_by_type()` y `auth_failure_rate()` son el pipeline de análisis técnico con TTL cache. El pipeline de negocio es independiente y no necesita tocarlas. |
| ❌ **No se toca `GET /telemetry/report`** | El endpoint de reporte técnico sigue sirviendo métricas de rendimiento operativo (volumen de eventos, errores, auth). El nuevo `GET /reporting/kpis` sirve KPIs de negocio. Son dos dominios diferentes que conviven sin acoplarse. |
| ✅ **`services/reporting/` es un módulo nuevo** | Todo el código de los endpoints de reporting vive en `services/reporting/main.py` con su propio router. No comparte archivos ni dependencias directas con `services/telemetry/`. |
| ✅ **`data/pipelines/business_performance.py` es la única fuente de lógica ETL** | Los flows, tasks y funciones de transformación viven aquí. Ni `services/reporting/` ni `services/telemetry/` contienen lógica de pipeline. |
