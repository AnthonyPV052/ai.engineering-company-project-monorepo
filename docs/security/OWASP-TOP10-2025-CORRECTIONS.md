# OWASP Top 10:2025 — Correcciones Aplicadas

> **Fecha:** 2026-11-04
> **Rama:** `feature/owasp-top10-audit`
> **Estado:** 🔴 8 críticos → 🟢 8 corregidos

---

## Resumen de Cambios

| # | OWASP | Hallazgo | Estado | Archivos modificados |
|---|-------|----------|--------|---------------------|
| 1 | A01 | `/knowledge/query` sin auth | ✅ Corregido | `routes/knowledge.py` |
| 2 | A01 | `/api/incidents` sin auth | ✅ Corregido | `routes/incidents.py` |
| 3 | A01 | `/tasks/{task_id}` sin auth | ✅ Corregido | `main.py` |
| 4 | A02 | `JWT_SECRET_KEY` fallback `dev-secret-key` | ✅ Corregido | `docker-compose.yml` |
| 5 | A02 | CORS methods/headers=`*` | ✅ Corregido | `main.py` |
| 6 | A02 | Redis sin auth | ✅ Corregido | `docker-compose.yml` |
| 7 | A02 | Flower sin auth | ✅ Corregido | `docker-compose.yml` |
| 8 | A02 | Faltan headers de seguridad HTTP | ✅ Corregido | `main.py` |
| 9 | A03 | Imágenes sin pinning (parcial) | 🟡 Nota | Pendiente digest SHA256 |
| 10 | A05 | Sin rate limiting | 🟡 Nota | Pendiente implementar slowapi |
| 11 | A06 | `question` sin `max_length` | ✅ Corregido | `routes/knowledge.py` |
| 12 | A10 | Contenedor como root | ✅ Corregido | `Dockerfile` |
| 13 | - | Faltaba `.env.example` | ✅ Creado | `.env.example` |

---

## Detalle Antes/Después

### 1. A01 — `/knowledge/query` autenticado

**Antes:**
```python
@router.post("/query", response_model=KnowledgeQueryResponse)
def knowledge_query(payload: KnowledgeQueryRequest) -> KnowledgeQueryResponse:
```

**Después:**
```python
@router.post("/query", response_model=KnowledgeQueryResponse)
def knowledge_query(payload: KnowledgeQueryRequest, current_user: dict = Depends(get_current_user)) -> KnowledgeQueryResponse:
```

**Evidencia reproducible:**
```bash
# Sin token → 401
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8020/knowledge/query \
  -H "Content-Type: application/json" \
  -d '{"question":"test"}'
# → 401

# Con token → 200/502
TOKEN=$(curl -s -X POST http://localhost:8020/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@brasaland.com","password":"test1234"}' | jq -r '.access_token')
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8020/knowledge/query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"question":"test"}'
# → 200
```

---

### 2. A01 — `/api/incidents` autenticado

**Antes:**
```python
router = APIRouter(prefix="/api/incidents", tags=["incidents"])
```

**Después:**
```python
router = APIRouter(prefix="/api/incidents", tags=["incidents"], dependencies=[Depends(get_current_user)])
```

**Evidencia reproducible:**
```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8020/api/incidents
# → 401
```

---

### 3. A01 — `/tasks/{task_id}` autenticado

**Antes:**
```python
@app.get("/tasks/{task_id}")
def get_task_status(task_id: str) -> dict[str, object]:
```

**Después:**
```python
@app.get("/tasks/{task_id}")
def get_task_status(task_id: str, current_user: dict = Depends(get_current_user)) -> dict[str, object]:
```

**Evidencia reproducible:**
```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8020/tasks/fake
# → 401
```

---

### 4. A02 — JWT_SECRET_KEY sin fallback inseguro

**Antes:**
```yaml
JWT_SECRET_KEY: ${JWT_SECRET_KEY:-dev-secret-key}
```

**Después:**
```yaml
JWT_SECRET_KEY: ${JWT_SECRET_KEY:?JWT_SECRET_KEY is required. Set it in .env or export it.}
```

**Evidencia reproducible:**
```bash
# Sin JWT_SECRET_KEY definida, docker compose falla al arrancar
JWT_SECRET_KEY="" docker compose config 2>&1 | head -5
# → JWT_SECRET_KEY is required.
```

---

### 5. A02 — CORS restringido

**Antes:**
```python
allow_methods=["*"],
allow_headers=["*"],
```

**Después:**
```python
allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
allow_headers=["Authorization", "Content-Type", "X-Requested-With", "Accept", "Origin"],
```

**Evidencia reproducible:**
```bash
curl -s -I -X OPTIONS http://localhost:8020/health \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: TRACE" \
  | grep -i "access-control-allow-methods"
# → No debe incluir TRACE
```

---

### 6. A02 — Headers de seguridad HTTP

**Nuevo middleware `SecurityHeadersMiddleware`:**
```python
response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
response.headers["X-Content-Type-Options"] = "nosniff"
response.headers["X-Frame-Options"] = "DENY"
response.headers["Content-Security-Policy"] = "default-src 'self'; ..."
response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
response.headers["Permissions-Policy"] = "camera=(), microphone=(), ..."
```

**Evidencia reproducible:**
```bash
curl -sI http://localhost:8020/health | grep -E "(Strict-Transport-Security|X-Content-Type-Options|X-Frame-Options|Content-Security-Policy)"
# → Todos deben aparecer
```

---

### 7. A02 — Redis con autenticación

**Antes:**
```yaml
redis-server --maxmemory-policy noeviction
```

**Después:**
```yaml
redis-server --maxmemory-policy noeviction --requirepass ${REDIS_PASSWORD:?REDIS_PASSWORD is required}
```

**Evidencia reproducible:**
```bash
# Sin contraseña → falla
redis-cli -h localhost -p 6379 PING
# → (error) NOAUTH Authentication required.

# Con contraseña → OK
redis-cli -h localhost -p 6379 -a "$REDIS_PASSWORD" PING
# → PONG
```

---

### 8. A02 — Flower con autenticación básica

**Antes:**
```yaml
command: ["celery", "--broker=redis://...", "flower", "--port=5555"]
```

**Después:**
```yaml
command: ["celery", "--broker=redis://...", "flower", "--port=5555",
          "--basic_auth=${FLOWER_USER:-admin}:${FLOWER_PASSWORD:?FLOWER_PASSWORD is required}"]
```

**Evidencia reproducible:**
```bash
# Sin auth → 401
curl -s -o /dev/null -w "%{http_code}" http://localhost:5555/
# → 401

# Con auth → 200
curl -s -o /dev/null -w "%{http_code}" -u admin:"$FLOWER_PASSWORD" http://localhost:5555/
# → 200
```

---

### 9. A06 — `question` con `max_length`

**Antes:**
```python
question: str = Field(min_length=1)
```

**Después:**
```python
question: str = Field(min_length=1, max_length=2000)
```

**Evidencia reproducible:**
```bash
TOKEN=$(curl -s -X POST ... | jq -r '.access_token')
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8020/knowledge/query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"question":"'"$(python3 -c 'print("A"*2500)')"'"}' 
# → 422
```

---

### 10. A10 — Contenedor con usuario no-root

**Antes:**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
# ... corre como root
```

**Después:**
```dockerfile
RUN addgroup --system --gid 1001 brasaland && \
    adduser --system --uid 1001 --ingroup brasaland --no-create-home brasaland && \
    mkdir -p /app/data /app/logs && \
    chown -R brasaland:brasaland /app && \
    chmod 755 /app && \
    chmod 750 /app/data && \
    chmod 750 /app/logs
USER brasaland
```

**Evidencia reproducible:**
```bash
docker exec brasaland-backend whoami
# → brasaland

docker exec brasaland-backend stat -c "%a %U" /app/data
# → 750 brasaland

docker exec brasaland-backend stat -c "%a %U" /app/logs
# → 750 brasaland
```

---

## Cómo ejecutar las pruebas

```bash
# 1. Asegúrate de tener las variables de entorno
cp .env.example .env
# Edita .env con valores reales

# 2. Inicia los servicios
docker compose up -d

# 3. Ejecuta las pruebas de verificación
cd services/api
python -m pytest tests/test_owasp_fixes.py -v
```

---

## Pendientes (no críticos para esta iteración)

| Item | Prioridad | Notas |
|------|-----------|-------|
| Rate limiting en login y agent | 🟡 Media | Implementar con `slowapi` |
| Content-Security-Policy más restrictiva | 🟡 Media | Evaluar necesidades del frontend |
| Pinning de imágenes con digest SHA256 | 🟡 Media | Mejora de supply chain |
| JWT con RS256 (asimétrico) | 🟡 Media | Requiere generación de keypair |
| Bloqueo por intentos fallidos de login | 🟡 Media | Requiere contador en Redis/DB |
| Auditoría de roles RBAC completa | 🟡 Media | Revisar permisos granulares |
