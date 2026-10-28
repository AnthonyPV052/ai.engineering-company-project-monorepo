# `scripts` folder

This folder contains **helper scripts** for the monorepo: development automation, maintenance utilities, repetitive tasks (setup, lint, migrations, data generation, etc.), and internal tooling.

- **Main purpose**: group support tools that do not belong to a specific app, agent, or pipeline but make the team’s work easier.
- **Recommendation**: document each script (what it does, parameters, requirements, usage examples) and keep them reproducible (and safe) across environments.

> _Spanish version: [README.es.md](./README.es.md)._

## `seed_incidents.py`

Carga `incidents-brasaland.csv` en el almacén TinyDB de `services/api`.
Normaliza categorías, estados y ubicaciones, asigna `origin="customer"`, no
inserta filas inválidas y es idempotente mediante un identificador estable.

```bash
python scripts/seed_incidents.py --validate-only

python scripts/seed_incidents.py
```

## `nightly_export.py`

Exporta la telemetría del día anterior, ejecuta el pipeline y registra la
corrida en `job_runs`. Es un proceso independiente de FastAPI; el cron externo
y las variables necesarias están documentados en
[`docs/nightly-export.md`](../docs/nightly-export.md).
