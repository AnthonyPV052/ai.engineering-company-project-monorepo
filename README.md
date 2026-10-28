# AI Engineering Company Project — Student Template

[![4Geeks Academy](https://img.shields.io/badge/4Geeks-Academy-blue)](https://4geeksacademy.com)
[![AI Engineering](https://img.shields.io/badge/track-AI%20Engineering-green)](https://4geeksacademy.com/es/programas-de-carrera/ingenieria-ia)

_Base template for transversal projects in the AI Engineering Career Program — 4Geeks Academy._

> _Instrucciones disponibles en español en [README.es.md](./README.es.md)._

---

## Purpose

This repository is the **starter template** for transversal projects. You will work on real company scenarios (Brasaland, TrackFlow, Nexova), building deliverables that map to course milestones (Web, Programming, Backend, Telemetry, RAG, Agents, Workflows, Real-time).

- Create a template from this repository.
- Replace the placeholder `CONTEXT.md` with your assigned company context.
- Use `skills/` and the directory-level `README.md` files as working guidance.

---

## Current status of the template

The repository currently provides a **base folder structure and documentation skeleton**. It does not include runnable apps or global scripts yet.

- `CONTEXT.md` is a placeholder and must be replaced with your assigned company context.
- There is no root `AGENTS.md` yet.
- Shared package metadata exists in `packages/shared/package.json` (`@repo/shared-types`), but no workspace runner is configured at root.

---

## Repository structure

```text
ai-engineering-company-project-template/
├── README.md
├── README.es.md
├── CONTEXT.md                # Placeholder to be replaced with assigned context
├── agents/                   # Agent patterns/templates and tools docs
├── apps/                     # Product apps (web, APIs, dashboards)
├── data/                     # raw, process, pipelines, eval
├── docs/                     # Project and architecture documentation
├── packages/
│   └── shared/               # Shared package (@repo/shared-types)
├── scripts/                  # Script conventions/documentation
├── shared/                   # Shared assets/conventions at repo level
├── skills/                   # Reusable agent skills
└── workflows/                # Automation/orchestration documentation
```

---

## How to start

1. **Use this repository as a template** and create your own project repo.
2. **Clone** your repository (or open it in Codespaces).
3. **Replace** `CONTEXT.md` with the full context for your assigned company.
4. **Review** each top-level folder `README.md` to understand intended responsibilities (`apps/`, `data/`, `skills/`, etc.).
5. **Start implementing** milestone deliverables in `apps/`, reusing `packages/shared/` and `data/` as needed.

---

## Run locally without Docker

The Brasaland backend can be started locally with Redis and Qdrant instead of
Docker. The commands below assume Linux, `uv`, and a Python version supported
by `services/api/pyproject.toml` are installed.

### 1. Install backend dependencies

From the repository root:

```bash
cd services/api
uv sync
```

Make sure `services/api/.env` contains the required application settings. In
particular, the RAG query endpoint uses `LLM_GATEWAY`, `LLM_API_KEY`,
`EMBED_MODEL`, and `GEN_MODEL` when they are configured.

### 2. Start Redis

In a separate terminal:

```bash
redis-server --daemonize yes --bind 127.0.0.1 --port 6379
redis-cli ping                    # expected: PONG
```

### 3. Start Qdrant

Download the Qdrant binary once from the repository root, then start it in a
separate terminal:

```bash
mkdir -p .local/bin .local/qdrant
curl -L --fail --silent --show-error \
	https://github.com/qdrant/qdrant/releases/download/v1.15.5/qdrant-x86_64-unknown-linux-gnu.tar.gz \
	| tar -xz -C .local/bin

QDRANT__STORAGE__STORAGE_PATH="$PWD/.local/qdrant" \
	.local/bin/qdrant --uri http://127.0.0.1:6333
```

```bash
set -a && . ./services/api/.env && set +a

QDRANT_URL=http://127.0.0.1:6333 \
  services/api/.venv/bin/python - <<'PY'
from data.pipelines.rag import setup

print(setup())
PY
```


Qdrant is available at `http://127.0.0.1:6333`.

### 4. Start the API

In another terminal, from `services/api`:

```bash
cd services/api
set -a && . ./.env && set +a
REDIS_URL=redis://127.0.0.1:6379/0 \
QDRANT_URL=http://127.0.0.1:6333 \
	uv run uvicorn main:app --reload --host 127.0.0.1 --port 8020
```

The API is available at `http://127.0.0.1:8020`. Verify it with:

```bash
curl http://127.0.0.1:8020/health
```

### 5. Start Celery and Flower (optional)

Celery is required for asynchronous pipeline tasks. Run the worker in a
separate terminal:

```bash
cd services/api
REDIS_URL=redis://127.0.0.1:6379/0 \
	uv run celery -A celery_app worker --loglevel=INFO -E
```

Flower is optional and provides a task monitor at `http://127.0.0.1:5555`:

```bash
cd services/api
REDIS_URL=redis://127.0.0.1:6379/0 \
	uv run python -m flower \
	--broker=redis://127.0.0.1:6379/0 flower \
	--port=5555 --address=127.0.0.1
```

The knowledge-base query endpoint is then available at:

```text
POST http://127.0.0.1:8020/knowledge/query
```

For example:

```bash
curl -X POST http://127.0.0.1:8020/knowledge/query \
	-H 'Content-Type: application/json' \
	-d '{"question":"¿Cuál es el protocolo de alérgenos?"}'
```

---

## Milestones (reference)

| Milestone | Focus        | Typical deliverables                        |
| --------- | ------------ | ------------------------------------------- |
| 0         | Prework      | Environment setup, first prompts            |
| 1         | Web          | Corporate website, forms, SEO               |
| 2         | Programming  | Business logic, scoring, calculations       |
| 3         | AI-driven UI | AI-generated interfaces                     |
| 4         | Next.js      | Portals, loyalty app, operations UI         |
| 5         | Backend      | Central API (locations, menus, sales, etc.) |
| 6         | Telemetry    | Data pipeline, dashboards                   |
| 7         | RAG & Memory | Semantic knowledge base, search             |
| 8         | Agents       | Support, onboarding, training agents        |
| 9         | Workflows    | n8n automations                             |
| 10        | Real-time    | Live dashboards, alerts, streaming          |

---

## Links

- [4Geeks Academy — AI Engineering](https://4geeksacademy.com/es/programas-de-carrera/ingenieria-ia)
- [How to start a coding project](https://4geeks.com/lesson/how-to-start-a-project)

---

## Contributors

This template was built as part of the 4Geeks Academy AI Engineering Career Program by [@marcogonzalo](https://www.linkedin.com/in/marcogonzalo) and [@alezanchezr](https://x.com/alesanchezr) and many other contributors. Find out more about our [AI Engineering Course](https://4geeksacademy.com/en/career-programs/ai-engineering), and [other courses](https://4geeksacademy.com/en/program-comparison).

You can find other templates and resources like this at the [4Geeks Academy GitHub page](https://github.com/4geeksacademy).

_This template is maintained by 4Geeks Academy for the AI Engineering track. For exclusive use in the programme._
