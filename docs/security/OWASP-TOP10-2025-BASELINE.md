# OWASP Top 10:2025 — Línea Base de Seguridad

> **Fecha:** 2026-11-04
> **Proyecto:** Brasaland Supplier Directory (Monorepo)
> **Propósito:** Documentar el estado actual de seguridad antes de correcciones,
> sirviendo como línea base para demostrar mejora.
> **Hash/Rama:** `feature/owasp-top10-audit`

---

## 1. Endurecimiento del Servidor — Estado Actual

### 1.1 Usuario de acceso dedicado (no root)

```dockerfile
# services/Dockerfile — Línea 1
FROM python:3.12-slim   # ← Corre como root por defecto
```

```dockerfile
# uis/Dockerfile — Línea 1
FROM node:20-alpine      # ← Corre como root por defecto
```

**Estado: ❌ Sin usuario dedicado.** Ambos contenedores ejecutan sus procesos como `root`. No hay instrucción `USER` en ninguno de los dos Dockerfiles.

---

### 1.2 Acceso SSH directo como root

No hay configuración SSH expuesta en el repositorio. Los contenedores no tienen servidor SSH instalado (imágenes slim/alpine).

**Estado: ✅ N/A** (SSH no está presente en los contenedores)

---

### 1.3 Permisos explícitos de carpetas

La estructura de volúmenes en `docker-compose.yml` es:

```yaml
volumes:
  - ./services/api:/app          # Código (read-write)
  - ./services/reporting:/app/reporting  # Código (read-write)
  - ./data:/app/data             # Datos (read-write)
  - ./docs/company-knowledge-base:/app/docs/company-knowledge-base:ro  # Config (read-only)
  - /app/.venv                   # Virtual env anónimo
```

**Estado: ❌ Sin permisos explícitos.** No hay diferenciación de permisos entre carpetas. Todo corre como root. Los directorios de código, logs y datos comparten el mismo nivel de acceso.

---

### 1.4 Firewall — Puertos expuestos

```yaml
# docker-compose.yml — Puertos mapeados al host
ports:
  - "8020:8020"    # API backend (FastAPI)
  - "6379:6379"    # Redis (sin autenticación)
  - "6333:6333"    # Qdrant gRPC
  - "6334:6334"    # Qdrant HTTP
  - "5555:5555"    # Flower (monitoreo Celery — sin auth)
```

```dockerfile
# services/Dockerfile
EXPOSE 8020   # ← Solo declara 8020, pero docker-compose expone más
```

**Estado: ❌ Puertos abiertos innecesarios.** Redis (6379) y Flower (5555) están expuestos al host sin autenticación. Qdrant (6333/6334) también accesible desde el host.

---

## 2. Auditoría OWASP Top 10:2025

### A01:2025 — Broken Access Control (Pérdida de Control de Acceso)

#### Backend (API)

| Endpoint | ¿Protegido? | Evidencia |
|----------|------------|-----------|
| `POST /auth/login` | ✅ Público | `routes/auth.py:50` — sin `Depends(get_current_user)` |
| `POST /auth/forgot-password` | ✅ Público | `routes/auth.py:88` — sin `Depends(get_current_user)` |
| `POST /auth/reset-password` | ✅ Público | `routes/auth.py:103` — sin `Depends(get_current_user)` |
| `POST /auth/change-password` | ✅ Requiere auth | `routes/auth.py:115` — `current_user = Depends(get_current_user)` |
| `GET /auth/me` | ✅ Requiere auth | `routes/auth.py:121` — `Depends(get_current_user)` |
| `POST /supplier` | ✅ Requiere auth | `routes/suppliers.py:15` — `dependencies=[Depends(get_current_user)]` |
| `GET /suppliers` | ✅ Requiere auth | Router-level dep |
| `GET /suppliers/{id}` | ✅ Requiere auth | Router-level dep |
| `PATCH /suppliers/{id}/rate` | ✅ Requiere auth | Router-level dep |
| `PATCH /suppliers/{id}/status` | ✅ Requiere auth | Router-level dep |
| `POST /users` | ❌ Registro público | `routes/users.py:39` — sin `Depends(get_current_user)` |
| `GET /users` | ❌ Sin verificación de rol | `routes/users.py` — requiere auth pero sin check de admin |
| `GET /health` | ✅ Público | `main.py:295` — intencional |
| `POST /knowledge/query` | ❌ **Público** | `routes/knowledge.py:66` — sin `Depends(get_current_user)` |
| `GET /tasks/{task_id}` | ❌ **Público** | `main.py:174` — sin auth |
| WebSocket `/chat/ws` | ⚠️ **Token por query param** | `chat/ws.py:132` — token va en URL o primer frame |
| `POST /api/incidents` | ❌ **Público** | `routes/incidents.py:44` — sin `Depends(get_current_user)` |
| Memory endpoints | ❌ Sin verificar | `memory/routes.py` — sin revisar |

**🔴 Crítico:**
1. `/knowledge/query` — expone el agente de IA sin autenticación (costo y data leakage).
2. `/api/incidents` — CRUD de incidencias sin auth.
3. `/tasks/{task_id}` — expone resultados de Celery (posible info leakage).
4. WebSocket chat — token en query-param (logeable en servidores proxy).
5. `PATCH /sppliers/{supplier_id}/rate` — **typo en la ruta** (`sppliers` en vez de `suppliers`), pero igualmente autenticada.

#### Frontend (Website)

| Aspecto | Estado | Evidencia |
|---------|--------|-----------|
| Token almacenado en `localStorage` | ❌ Riesgo XSS | `lib/auth.ts:4` — `AUTH_TOKEN_KEY = "brasaland.access_token"` |
| `ProtectedRoute` solo valida token | ✅ | `components/auth/ProtectedRoute.tsx` |
| Sin Content-Security-Policy | ❌ | HTML no tiene meta CSP |

#### Sistema Agéntico

| Aspecto | Estado | Evidencia |
|---------|--------|-----------|
| Agent Memory System (POST /knowledge/query) | ❌ Sin auth | Cualquiera puede consultar el agente |
| Memory proposals requieren confirmación | ✅ | `memory/store.py` — solo escribe tras confirmación |
| Validación de datos prohibidos en memoria | ✅ | `memory/store.py:48` — `_FORBIDDEN_PATTERNS` |

---

### A02:2025 — Security Misconfiguration (Configuración de Seguridad Incorrecta)

#### 🔴 Crítico: JWT_SECRET_KEY con fallback inseguro

```yaml
# docker-compose.yml
JWT_SECRET_KEY: ${JWT_SECRET_KEY:-dev-secret-key}  # ← fallback hardcodeado
```

```python
# security.py — Línea 42
def get_secret_key() -> str:
    secret = os.getenv("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY is required.")  # ← solo falla si no hay variable
```

El fallback `dev-secret-key` en docker-compose.yml significa que en desarrollo se usa una clave JWT predecible.

#### 🔴 Crítico: CORS demasiado permisivo

```python
# main.py — Línea 117
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:4011",
        "http://127.0.0.1:4011",
    ],
    allow_credentials=True,
    allow_methods=["*"],   # ← Todos los métodos HTTP
    allow_headers=["*"],   # ← Todos los headers
)
```

`allow_methods=["*"]` y `allow_headers=["*"]` excesivamente permisivos.

#### 🟡 Medio: Encabezados de seguridad HTTP faltantes

No se detectan en `main.py` middlewares que agreguen:
- `Strict-Transport-Security`
- `X-Content-Type-Options`
- `X-Frame-Options`
- `Content-Security-Policy`

#### 🟡 Medio: Redis sin autenticación

```yaml
# docker-compose.yml — Redis
redis:
  image: redis:7-alpine
  command: ["redis-server", "--maxmemory-policy", "noeviction"]  # ← sin --requirepass
```

#### 🟡 Medio: Flower (monitoreo Celery) sin autenticación

```yaml
# docker-compose.yml — Flower
flower:
  image: mher/flower:2.0
  ports:
    - "5555:5555"
  # ← No se especifica --auth ni --basic_auth
```

---

### A03:2025 — Software Supply Chain Failures (Fallas en la Cadena de Suministro)

#### 🔴 Crítico: Dependencias sin verificación de integridad

```dockerfile
# services/Dockerfile
RUN uv sync --frozen          # ← Usa lockfile pero no verifica firmas
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/  # ← Imagen mutable (latest)
```

```yaml
# docker-compose.yml — Imágenes sin pinning de digest
image: qdrant/qdrant:v1.15.5      # ← Version tag pero sin SHA256
image: redis:7-alpine              # ← Tag mutable
image: mher/flower:2.0             # ← Tag mutable
```

#### 🟡 Medio: Base images sin escaneo de vulnerabilidades

- `python:3.12-slim` — no se usa `python:3.12-slim@sha256:...`
- `node:20-alpine` — no se usa digest

---

### A04:2025 — Cryptographic Failures (Fallas Criptográficas)

#### ✅ Bueno: Passwords con bcrypt

```python
# security.py
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
```

#### ✅ Bueno: JWT con HS256

```python
# security.py
ALGORITHM = "HS256"
```

#### 🟡 Medio: JWT_SECRET_KEY en texto plano

- No se usa asimetría (RS256/ES256) para firma JWT.
- La clave secreta está en variable de entorno (o .env), no en un keystore.

#### 🟡 Medio: Reset password token tiene propósito específico

```python
# security.py — Línea 103
token = jwt.encode(
    {"sub": user_id, "jti": token_id, "purpose": "password_reset", ...},
    ...
)
```

✅ Punto positivo: incluye `purpose` y `jti` para evitar reuso.

#### ✅ Bueno: Expiración de tokens configurable

```python
ACCESS_TOKEN_EXPIRE_MINUTES = 30  # defecto
PASSWORD_RESET_TOKEN_EXPIRE_MINUTES = 15  # defecto
```

---

### A05:2025 — Injection (Inyección)

#### Backend — SQL

```python
# routes/inventory.py
# Usa SQLModel (SQLAlchemy) — parametrizado ✅

# database.py — SQLModel
# SQLModel usa query builders parametrizados ✅
```

#### Backend — NoSQL (TinyDB)

```python
# database.py
# TinyDB es JSON-based, no SQL — pero sin sanitización de queries
# routes/incidents.py — Línea 35
document = get_incidents_db().get(query.id == incident_id)
# TinyQuery usa comparación directa, no es inyectable como SQL
```

#### Backend — Agent prompts

```python
# routes/knowledge.py — Línea 66
result = graph.invoke(
    {"question": payload.question, ...}  # ← Input directo al LLM
)
```

⚠️ **Riesgo:** prompt injection a través del endpoint sin autenticar.

#### Frontend — Sin sanitización de inputs

```tsx
// uis/application/app/suppliers/page.tsx
// Los inputs de formularios se envían directamente al backend
```

**Estado: 🟢** SQL parametrizado. ⚠️ Prompt injection es riesgo real (A01).

---

### A06:2025 — Insecure Design (Diseño Inseguro)

#### 🟡 Medio: Rate limiting ausente

No hay `slowapi` ni middleware de rate limiting en `main.py`. Los endpoints `/auth/login` y `/knowledge/query` son vulnerables a fuerza bruta y abuso de recursos.

#### 🟡 Medio: Sin limitación de tamaño en requests

```python
# main.py — Sin middleware para limitar payload size
# El agente (knowledge/query) acepta cualquier question sin límite de longitud
```

```python
# routes/knowledge.py
class KnowledgeQueryRequest(BaseModel):
    question: str = Field(min_length=1)  # ← Sin max_length
```

#### 🟡 Medio: No hay validación de profundidad de objetos

---

### A07:2025 — Authentication Failures (Fallas de Autenticación)

#### 🟡 Medio: Sin bloqueo por intentos fallidos

```python
# routes/auth.py — Línea 62
raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
# ← No hay contador de intentos ni lockout
```

#### 🟡 Medio: Sin MFA/2FA

- Solo autenticación por password + JWT.

#### ✅ Bueno: Password reset con token de un solo uso

```python
# auth.py — consume_password_reset_token() impide reuso
```

#### ✅ Bueno: Diferencia entre roles (admin, manager, user)

```python
# auth_models.py
class UserRoleEnum(str, Enum):
    admin = "admin"
    manager = "manager"
    user = "user"
```

---

### A08:2025 — Software or Data Integrity Failures (Fallas de Integridad)

#### 🟡 Medio: TinyDB — datos sin integridad transaccional

```python
# database.py — TinyDB usa archivos JSON planos
# Sin transacciones, sin validación de integridad en escritura
```

#### 🟡 Medio: Sin firma de artefactos en CI/CD

- No hay verificación de checksums en dependencias.
- Los archivos JSON de TinyDB no tienen checksum.

#### ✅ Bueno: Memory System con auditoría

```python
# memory/store.py — log_audit_event() registra cada operación
```

---

### A09:2025 — Security Logging & Alerting Failures (Fallas de Registro y Alerta)

#### 🟡 Medio: Logging solo para timing

```python
# main.py — Línea 69
logger.info(f"{request.method} {request.url.path} → {response.status_code} | {duration:.1f}ms")
# Solo log de rendimiento, no de seguridad
```

#### ✅ Bueno: Telemetría estructurada

```python
# telemetry_util.py — emit_telemetry_event() con eventos de seguridad (login, stock edit)
```

#### ��� Crítico: Sin alerting

- No hay integración con sistemas de alerta (PagerDuty, Slack, email).
- Los errores solo se loggean, no alertan.

---

### A10:2025 — Mishandling of Exceptional Conditions (Manejo Inadecuado de Excepciones)

#### 🟡 Medio: Error handler genérico sin detalle

```python
# main.py — Línea 276
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    emit_api_error_event(...)
    return JSONResponse(status_code=500, content={"error": {"message": "Error interno del servidor."}})
# ✅ No filtra información sensible en producción
```

#### 🟡 Medio: Detalles de error en validación

```python
# main.py — Línea 250
@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(...):
    error = exc.errors()[0]
    # ✅ Muestra solo field y message, no stack trace
```

---

## 3. Resumen de Hallazgos Críticos

| # | Categoría OWASP | Hallazgo | Severidad |
|---|-----------------|----------|-----------|
| 1 | A01 | `/knowledge/query` sin autenticación — agente expuesto | 🔴 Crítica |
| 2 | A01 | `/api/incidents` sin autenticación | 🔴 Crítica |
| 3 | A01 | `/tasks/{task_id}` sin autenticación | 🔴 Crítica |
| 4 | A02 | `JWT_SECRET_KEY` con fallback `dev-secret-key` | 🔴 Crítica |
| 5 | A02 | CORS methods/headers demasiado permisivos (`*`) | 🔴 Crítica |
| 6 | A02 | Redis expuesto sin autenticación | 🔴 Crítica |
| 7 | A02 | Flower expuesto sin autenticación | 🔴 Crítica |
| 8 | A03 | Imágenes sin pinning de digest SHA256 | 🟡 Alta |
| 9 | A05 | Sin rate limiting en login ni agent query | 🟡 Alta |
| 10 | A06 | `KnowledgeQueryRequest.question` sin `max_length` | 🟡 Alta |
| 11 | A06 | `question` sin `max_length` | 🟡 Alta |
| 12 | A09 | Sin alerting ante eventos de seguridad | 🟡 Alta |
| 13 | A10 | Token JWT en query param de WebSocket | 🟡 Alta |

---

## 4. Evidencia de Comandos (Línea Base)

```bash
# Verificar puertos expuestos
docker compose ps --format "table {{.Name}}\t{{.Ports}}"

# Verificar usuario en contenedor
docker exec brasaland-backend whoami
# → root

# Verificar JWT por defecto
docker compose exec backend env | grep JWT_SECRET_KEY
# → dev-secret-key (si no se configuró)

# Verificar Redis sin auth
redis-cli -h localhost -p 6379 PING
# → PONG

# Verificar Flower sin auth
curl -s http://localhost:5555/ | head -5
# → (responde sin credenciales)
```

---

> **Próximo paso:** Corregir todos los hallazgos críticos marcados como 🔴,
> documentando cada corrección con evidencia reproducible (antes/después).
