# Sistema de Memoria del Agente — Estado de verificación

> **Actualizado:** 2026-10-28. Se completó la verificación end-to-end del flujo de memoria en el entorno Codespaces. Los servicios backend, Redis y Qdrant quedaron activos al terminar.

## ✅ Infraestructura y esquema

- PostgreSQL/Supabase operativo, con pgvector 0.8.2; tablas `agent_memories`, `memory_proposals` y `memory_audit_log` presentes.
- `agent_memories.embedding` y el código de persistencia/búsqueda usan `vector(1024)`, consistente con `pplx-embed-v1-0.6b`.
- La unicidad parcial permite propuestas pendientes en sesiones diferentes.
- Qdrant `v1.15.5` contiene la colección `brasaland_knowledge` indexada con 18 chunks. La búsqueda funciona; el cliente `qdrant-client 1.19.1` muestra advertencia de diferencia de versiones, sin bloquear las pruebas.

## ✅ Flujos end-to-end verificados

| Caso | Resultado |
|---|---|
| Pregunta de conocimiento documentado sobre merma | Respuesta RAG correcta, sin propuesta de memoria. |
| Preferencia operativa recurrente | Se generó propuesta para preferencia del gerente de Medellín: reportes por WhatsApp. |
| Aprobación explícita | Propuesta aprobada y memoria persistida en `agent_memories` con embedding 1024D. |
| Búsqueda directa | La búsqueda exacta recupera la memoria (score 1.0). |
| Rechazo | Propuesta `e6d821c2-5dc4-49cb-9673-0cb5b51d792c` está `rejected`, `approved_memory_id` es NULL; auditoría incluye `classification_ambiguous`, `classification_rejected` y `rejected`. No hay memoria persistida de esa propuesta. |
| Cambio de tema | Propuesta pendiente se marca `discarded` y se registra en auditoría. |
| Sesiones distintas | `e2e-concurrent-a` y `e2e-concurrent-b` mantienen propuestas `pending` diferentes; se registró `proposal_created` para ambas. |
| Consulta explícita de recuerdo sin contexto RAG | Tras la corrección de routing/umbral, el endpoint devuelve: “Sí, según la memoria confirmada, el gerente de Medellín prefiere recibir los reportes por WhatsApp.” |

### Búsqueda semántica y umbral

- El umbral normal se mantiene en `0.85`; una paráfrasis general obtuvo score `0.7666` y no supera el umbral. No se relajó la política global.
- Para preguntas identificadas explícitamente como recuerdo (`recuerdas`/`remember` y patrones de preferencia), `generate_node` usa umbral local `0.60`; el resto conserva `0.85`. La pregunta amplia “¿Recuerdas algo sobre el gerente de Medellín?” puntuó `0.6273` frente a la memoria confirmada, por debajo del anterior `0.70`; así se explica el fallo concreto. Las respuestas siguen distinguiendo memorias confirmadas de fuentes/políticas corporativas.
- No reducir globalmente el umbral sin una evaluación más amplia de precisión/recall.

## ✅ Cambios en código

- `services/api/graph/routing.py`: clasifica preguntas explícitas de recuerdo y enruta a `generate` aunque la recuperación RAG esté vacía.
- `services/api/graph/nodes.py`: busca memorias para ese camino, usa `threshold=0.60` solo en recuerdo explícito y evita llamar al generador si no hay contexto ni memorias coincidentes. Las preguntas sin recuerdo conservan el fallback `no_context`.
- `services/api/graph/routing.py` y `nodes.py`: los imperativos explícitos “Recuerda esto/que...” también pasan a generación sin contexto RAG. El prompt aclara que cambios duraderos de disponibilidad de menú por local pueden proponerse y que requieren aprobación explícita antes de persistirse.
- `tests/pipelines/test_agent_routing.py`: cubre routing de recuerdo, fallback sin resultados, paso de memorias aprobadas al generador y mantiene la evaluación existente de fallos mixtos.
- Se corrigió un test de fallback mixto que parcheaba la función generadora obsoleta.

## ✅ Tests ejecutados

Ejecutados en el contenedor backend (Python 3.12):

```text
34 passed in 7.88s
```

Incluye:
- `tests/pipelines/test_agent_routing.py` — 17 tests
- `tests/pipelines/test_rag.py` — 5 tests
- `services/api/tests/test_memory_policy.py` — 12 tests

La suite completa del repositorio no se ejecutó; estos son los tests de routing, RAG y política de memoria relacionados con los cambios.

## ⚠️ Observaciones operativas

- El gateway de embeddings aplica rate limit de 15 solicitudes/minuto. La indexación RAG de 18 chunks se completó aplicando espera entre requests.
- El entorno local no tiene `pytest`; los tests se ejecutaron dentro de `brasaland-backend`.
- `docker compose` monta `services/api` en `/app` y el backend usa `uvicorn --reload`; tener presente el riesgo de recarga si se alteran archivos mientras hay falta de disco.
- Redis y worker/Flower no estaban activos al cierre de esta ejecución; backend, Redis y Qdrant sí estaban activos según el último estado comprobado. El flujo de memoria validado no depende del worker.

## Pendientes residuales

- Ampliar evaluación de la detección de intención de recuerdo en idiomas y formulaciones adicionales.
- Medir precisión/recall del umbral local `0.60` con más memorias y paráfrasis antes de generalizarlo.
- Ejecutar suite completa de tests en un entorno con dependencias instaladas.
- Opcional: detener los contenedores de backend, Redis y Qdrant al terminar el trabajo.
