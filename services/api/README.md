# Services API

Backend FastAPI para el directorio de proveedores, autenticación y gestor
centralizado de incidencias.

## Variables de entorno

Crear archivo `.env` dentro de `services/api` usando `.env.example`:

- `JWT_SECRET_KEY`: clave para firma JWT.
- `ACCESS_TOKEN_EXPIRE_MINUTES`: expiración del access token en minutos.
- `PASSWORD_RESET_TOKEN_EXPIRE_MINUTES`: expiración del enlace de restablecimiento (por defecto, 15 minutos).
- `RESEND_API_KEY`: API key de Resend para enviar los correos de restablecimiento.
- `RESEND_FROM_EMAIL`: remitente con dominio verificado en Resend.
- `APP_BASE_URL`: URL pública de website para construir el enlace de restablecimiento.

## Ejecutar con Docker

```bash
# Desde la raíz del monorepo
docker compose up --build backend
```

La API quedará accesible en `http://localhost:8020`.

La colección `brasaland_knowledge` no se crea al arrancar la API: hay que
indexar explícitamente la base de conocimiento. Con el backend levantado y el
gateway de embeddings accesible/configurado (`LLM_GATEWAY`, `LLM_API_KEY` y
`EMBED_MODEL`), ejecuta desde la raíz del monorepo:

```bash
docker compose exec backend uv run python -c 'from rag import setup; print(setup())'
```

El comando debe informar la colección y el número de documentos/chunks
indexados. El backend monta los Markdown fuente en modo sólo lectura desde
`docs/company-knowledge-base/`; si se modifica el volumen en Compose, recrea el
servicio (`docker compose up -d backend`) antes de indexar. `setup()` usa
*clean-and-reload*, así que no lo ejecutes mientras otro proceso esté usando
la colección para consultas.

El worker corre separado: `docker compose up worker` para iniciarlo y
`docker compose stop worker` para detenerlo. Flower está disponible en
`http://localhost:5555`. Sin Docker, desde este directorio, usa
`REDIS_URL=redis://localhost:6379/0 celery -A celery_app worker --loglevel=INFO`.

`POST /reporting/pipeline-runs` devuelve `202 {"task_id": "..."}` y
`GET /tasks/{task_id}` consulta `pending`, `started`, `success` o `failure`.

### Stack local sin Docker

Instala Redis con el gestor del sistema y sincroniza dependencias con `uv sync`.
Después, desde `services/api`, ejecuta en terminales separadas:

```bash
sudo service redis-server start
REDIS_URL=redis://127.0.0.1:6379/0 uv run celery -A celery_app worker --loglevel=INFO -E
REDIS_URL=redis://127.0.0.1:6379/0 uv run python -m flower --broker=redis://127.0.0.1:6379/0 flower --port=5555 --address=0.0.0.0
```

Flower queda accesible en `http://localhost:5555`. La opción `-E` habilita los
eventos necesarios para que Flower muestre tareas en ejecución y completadas.

## Ejecutar sin Docker

### Opción A — Con `uv` (recomendado)

Asegúrate de tener Python >= 3.11 y `uv` instalado:

```bash
pip install uv
```

Luego:

```bash
cd services/api
uv sync          # Instala dependencias (incluyendo prefect para el pipeline)
uv run seed      # Carga datos de ejemplo
uv run uvicorn main:app --reload --port 8020
```

El comando `seed` carga tanto los proveedores de ejemplo como el histórico de
`incidents-brasaland.csv` en `data/incidents.json`; puede ejecutarse varias veces
sin duplicar incidencias.

### Opción B — Con Python del sistema

Si `prefect` ya está instalado globalmente (suele estar preinstalado en entornos
de desarrollo del monorepo), puedes usar `python3 -m uvicorn` directamente:

```bash
cd services/api
python3 -m uvicorn main:app --reload --port 8020
```

Esto evita recrear el `.venv` local y usa las dependencias globales, incluyendo
`prefect` y `pandas`.

## Endpoints

### Públicos

- `GET /health`
- `POST /users` (registro de usuario)
- `POST /auth/login`
- `POST /auth/forgot-password` (siempre devuelve respuesta genérica para evitar enumeración de usuarios)
- `POST /auth/reset-password`

### Protegidos (Bearer JWT)

#### Auth

- `GET /auth/me`
- `POST /auth/change-password`

#### Users

- `GET /users` (solo admin)
- `GET /users/{user_id}` (usuario dueño o admin)
- `PUT /users/{user_id}` (usuario dueño o admin; role e is_active solo admin)
- `DELETE /users/{user_id}` (usuario dueño o admin)
- `GET /users/{user_id}/profile` (usuario dueño o admin)

#### Profiles

- `GET /profiles/me`
- `PUT /profiles/me`

#### Suppliers

- `POST /supplier`
- `GET /suppliers`
- `GET /suppliers/{id}`
- `PATCH /suppliers/{id}/rate`
- `PATCH /sppliers/{id}/rate`
- `PATCH /suppliers/{id}/status`
- `DELETE /suppliers`
- `DELETE /suppliers/{id}`

### Incidents

Estos endpoints son públicos mientras no se defina un requisito de autorización
para la operación de incidencias.

- `POST /api/incidents`
- `GET /api/incidents?status=&origin=&branch=&category=`
- `GET /api/incidents/{id}`
- `PATCH /api/incidents/{id}/status`
- `GET /api/incidents/summary`

Las transiciones de estado permitidas son `open → in_progress|discarded` e
`in_progress → resolved|discarded`; `resolved` y `discarded` son finales.

### Agente de soporte y conocimiento

`POST /knowledge/query` enruta automáticamente cada pregunta al RAG, a la
consulta de solo lectura `GET /api/incidents/{id}`, o a ambos en ese orden.
El agente consulta incidencias cuando la pregunta hace referencia a un
ticket/caso; para resolver su estado se debe incluir el ID explícito. La tool
tiene un límite de 7 segundos y, ante timeout, fallo o ticket inexistente, el
agente responde honestamente que no pudo confirmar su estado.
`GET /knowledge/traces/{trace_id}` muestra los nodos ejecutados y los campos
`sources` y `execution_order` de la corrida completada. La URL de la API se
configura mediante `INCIDENTS_API_URL` (por defecto
`http://127.0.0.1:8020/api/incidents`). El router local de incidencias no exige
autenticación; si se configura una API externa protegida, `INCIDENTS_API_TOKEN`
se envía como Bearer token. `sources` refleja fuentes realmente ejecutadas (no
incluye RAG si el nodo de recuperación se omitió), y `execution_order` conserva
el orden efectivo de nodos.

Si los servicios externos de embeddings/generación o Qdrant no están
disponibles, el agente registra el error técnico en el trace y responde que
no pudo consultar conocimiento, en vez de tratarlo como una búsqueda válida
sin resultados. En solicitudes mixtas conserva cualquier estado de ticket
confirmado.

La recuperación RAG espera hasta 75 segundos por defecto (`AGENT_RAG_RETRIEVAL_TIMEOUT_SECONDS`), incluyendo embedding y búsqueda. El embedding tiene un timeout configurable de 30 segundos y un reintento en timeout explícito (`RAG_EMBEDDING_TIMEOUT_SECONDS`, `RAG_EMBEDDING_RETRIES`); errores DNS/conexión fallan rápido. Qdrant tiene timeout de 20 segundos y hasta dos intentos sólo en `ConnectTimeout` (`RAG_QDRANT_TIMEOUT_SECONDS`, `RAG_QDRANT_RETRIEVAL_ATTEMPTS`). En Docker Compose, `QDRANT_URL` por defecto usa el puerto publicado del host (`host.docker.internal:6333`), porque en el entorno Codespaces probado la ruta directa al IP de servicio `qdrant` resuelve pero su TCP expira; se puede overridear `QDRANT_URL` si el bridge de Docker está sano. El backend no puede alcanzar DNS externo desde el contenedor en este Codespace, aunque la resolución en el host funciona; eso requiere reparar el DNS/egress del bridge o proporcionar un resolver/proxy aprobado y accesible. El aumento de timeouts no disimula ese fallo; se conserva el fallback seguro.

El contrato tipado de la tool se define en `graph/incident_tool.py`:
`IncidentToolInput(ticket_id: str | null)` y `IncidentToolOutput`, que incluye
el resultado (`found`, `not_found`, `missing_id`, `timeout` o `service_error`)
y `incident`. Si existe, `incident` se valida contra `IncidentResponse`, con
`id`, `title`, `description`, `category`, `status`, `origin`, `branch`,
`created_at` y `updated_at`, igual que la respuesta del API.
