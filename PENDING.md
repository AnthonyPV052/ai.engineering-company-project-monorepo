# Pendientes — Sistema de Memoria del Agente

> **Contexto:** Este proyecto se desarrolló en un Codespaces con 32 GB de almacenamiento que resultó insuficiente para el código fuente, imágenes Docker (backend ~918 MB cada una) y datos de Supabase. Los pasos 1-5 de la migración están completos, pero el almacenamiento se agotó antes de poder verificar el flujo completo end-to-end.

## ✅ Completado

### Infraestructura
- [x] Contenedores funcionales: backend, worker, redis, qdrant, flower
- [x] Conexión a Supabase PostgreSQL vía pooler IPv4
- [x] pgvector v0.8.2 instalado y funcional

### Migración 003 — Agent Memory Store
- [x] SQL actualizado a `vector(1024)` (el embedding `pplx-embed-v1-0.6b` genera 1024 dimensiones)
- [x] Tablas creadas: `agent_memories`, `memory_proposals`, `memory_audit_log`
- [x] Índices: IVFFlat (cosine, 200 lists), unicidad parcial por sesión, timestamps, etc.

### Código
- [x] `database.py`: `init_db()` con `exclude_tables` para no pisar esquemas de migración
- [x] `main.py`: lifespan captura `OperationalError`, importa `memory.models` antes de init_db, registra `memory_router`
- [x] `graph/state.py`: `session_id`, `base_language`, `memory_proposal` en `AgentState`
- [x] `graph/routing.py`: redirige a `generate` si hay `pending_proposal_was_present`
- [x] `graph/tracing.py`: `memory_proposal` y `session_id` opcionales en `finish_trace()`
- [x] `graph/nodes.py`: `generate_node` usa `generate_answer_with_memory`, busca memorias previas, crea propuestas
- [x] `routes/knowledge.py`: pre-procesa intención del usuario frente a propuesta pendiente (classifier), resuelve propuestas
- [x] `memory/generation.py`: `field_validator` coerce `confidence` de string ("alta") a float (0.9)
- [x] `memory/store.py`: CRUD completo con validaciones, embedding 1024, categorías permitidas, patrones prohibidos

## ❌ Pendiente — Verificación End-to-End

El flujo completo de memoria no pudo probarse porque:
1. El archivo `services/api/memory/generation.py` se corrompió (0 bytes) tras hot-reload justo cuando se agotó el disco
2. Aunque se corrigió el SQL a `vector(1024)`, `store.py` también se corrompió y no se pudo restaurar por falta de espacio
3. Los archivos nuevos en `services/api/memory/` y `services/api/tests/` nunca se escribieron completamente

### Pasos para retomar en un Codespaces con más almacenamiento (>64 GB recomendado)

```bash
# 1. Verificar que los archivos de memoria existen y no están corruptos
ls -la services/api/memory/
cat services/api/memory/generation.py  # Debe tener >100 líneas
cat services/api/memory/store.py       # Debe tener >250 líneas
cat services/api/memory/classifier.py
cat services/api/memory/routes/__init__.py
cat services/api/memory/models.py

# 2. Verificar tablas en Supabase
docker compose exec backend uv run python3 -c "
from database import _get_engine
from sqlmodel import Session, text
with Session(_get_engine()) as session:
    rows = session.execute(text(\"\"\"
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public'
        AND table_name IN ('agent_memories','memory_proposals','memory_audit_log')
    \"\"\")).fetchall()
    for r in rows: print(f'  ✓ {r[0]}')
"

# 3. Reconstruir imágenes y levantar contenedores
docker compose build --no-cache backend worker
docker compose up -d

# 4. Probar respuesta del agente (debe responder correctamente desde RAG)
curl -s -X POST http://localhost:8020/knowledge/query \
  -H "Content-Type: application/json" \
  -d '{"question":"¿Cómo se maneja la merma no explicada?","session_id":"e2e-001"}'

# 5. Pregunta que debería generar propuesta de memoria
curl -s -X POST http://localhost:8020/knowledge/query \
  -H "Content-Type: application/json" \
  -d '{"question":"El gerente de Medellín prefiere que le reporten las incidencias por WhatsApp en lugar del sistema","session_id":"e2e-002"}'

# 6. Ver propuesta pendiente
curl -s -X POST http://localhost:8020/memory/proposal/pending \
  -H "Content-Type: application/json" \
  -d '{"session_id":"e2e-002"}'

# 7. Aprobar la propuesta
curl -s -X POST http://localhost:8020/memory/proposal/resolve \
  -H "Content-Type: application/json" \
  -d '{"session_id":"e2e-002","proposal_id":"<ID_DEL_PASO_6>","resolution":"approved"}'

# 8. Buscar memoria por similitud semántica
curl -s -X POST http://localhost:8020/memory/search \
  -H "Content-Type: application/json" \
  -d '{"query":"WhatsApp gerente Medellín reportar incidencias"}'

# 9. Ver auditoría
curl -s http://localhost:8020/memory/audit?limit=10
```

### Casos de prueba que cubrir

| # | Escenario | Paso crítico |
|---|-----------|--------------|
| 1 | Pregunta RAG normal → answer OK, memory_proposal=null | Verificar que el LLM evalúa correctamente: conocimiento documentado no merece memoria episódica |
| 2 | Hecho operativo (ej: "El gerente de Miami prefiere email") → should_store=true | Verificar que el LLM clasifica como dato episódico relevante |
| 3 | Usuario responde "sí" → propuesta se aprueba → se persiste en agent_memories | Verificar el flujo classifier → resolve_proposal → store_memory |
| 4 | Usuario responde "no" → propuesta se rechaza → audit trail | Verificar que no queda en agent_memories |
| 5 | Usuario cambia de tema → propuesta se descarta automáticamente | Verificar classify_intention devuelve topic_change |
| 6 | Búsqueda semántica de memoria persistida | Verificar que search_memories devuelve resultados con score > 0.85 |
| 7 | Dos sesiones simultáneas con propuestas pendientes | Verificar que el índice parcial único no bloquea |
| 8 | Familiar: consultar "¿recuerdas algo sobre..." con memoria guardada | Verificar que aparece en memoria_context del generate_node |

### Problemas conocidos

1. **Dimensión del embedding:** `pplx-embed-v1-0.6b` → 1024D. Si se cambia el modelo de embedding, hay que actualizar `vector(1024)` en BD y las validaciones en `store.py`.
2. **LLM devuelve confidence como string:** El modelo deepseek-v4-flash a veces devuelve "alta" en lugar de 0.9. El `field_validator` en `MemorySuggest` mapea strings, pero si el LLM devuelve un valor no mapeado, se asigna 0.0 por defecto.
3. **Hot-reaload + Docker volumes:** Los volúmenes montan `./services/api:/app`. Cuando uvicorn recarga en caliente y el disco se llena, los archivos pueden quedar truncados (0 bytes). **Solución:** usar `--reload-dir` más específico o desactivar reload en producción.