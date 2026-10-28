# `data/pipelines` folder

This folder groups **all data pipelines in the monorepo** related to the company: ingestion, ETL/ELT, cleaning, transformation, and loading into analytical or production systems.

Each subfolder or file under `data/pipelines/` should represent **one pipeline or job set** (for example `sales-etl`, `telemetry-stream`, `customer-segmentation`) and include the required configuration (scripts, orchestration, connectors, schemas, etc.).

- **Main purpose**: consolidate in one place the data movement and transformation logic that powers the company’s applications and analytics.
- **Recommendation**: document pipelines as you add them—their goal, data sources and sinks, dependencies, and how to run them in development, testing, and production.

> _Spanish version: [README.es.md](./README.es.md)._

## RAG Brasaland

`rag.py` expone la única entrada pública de consulta:

```python
from data.pipelines.rag import query
answer = query("¿Qué alérgenos tiene la Ensalada Tropical?")
```

`query()` orquesta `retrieve()` y `generate_answer()`. La recuperación usa el
mismo `embed()` de `services/api/rag.py`, consulta `brasaland_knowledge`,
filtra por `min_score` y devuelve únicamente payloads serializables.

El modelo de generación se configura con `GEN_MODEL`; por defecto es
`litellm/madrid-spain/openrouter/deepseek/deepseek-v4-flash`. `EMBED_MODEL` se
reserva exclusivamente al modelo de embeddings.
