# Nightly export

El job `nightly_export` se ejecuta como proceso externo, nunca como startup task,
background task o hilo de FastAPI.

## Cron

Después de aplicar `migrations/001_create_job_runs.sql`, configurar en el host:

```cron
15 2 * * * cd /workspaces/AnthonyPV052-ai.engineering-company-project-monorepo && /usr/bin/python3 scripts/nightly_export.py >> /var/log/brasaland/nightly_export.log 2>&1
```

`DATABASE_URL` debe estar disponible para el proceso. Se puede reprocesar una
fecha concreta sin tocar el código:

```bash
TARGET_DATE=2026-09-13 python scripts/nightly_export.py
```

El pipeline actual del repositorio es semanal y se invoca con la semana ISO que
contiene `TARGET_DATE`. Para desplegar otro pipeline, definir
`NIGHTLY_PIPELINE_COMMAND` como comando shell tokenizable (por ejemplo,
`python -m data.pipelines.telemetry_kpi_daily.run --no-prefect`).

La tabla `job_runs` es el lock distribuido: una fila `processing` impide una
segunda ejecución y una fila `completed` para la misma fecha hace el job
idempotente.

## Evidencia de concurrencia e idempotencia

Para probarlo en un entorno con `job_runs` migrado, lanzar dos procesos con la
misma fecha:

```bash
TARGET_DATE=2026-09-13 python scripts/nightly_export.py & \
TARGET_DATE=2026-09-13 python scripts/nightly_export.py & wait
```

Solo uno puede adquirir `processing`; el otro termina silenciosamente. Una
ejecución posterior observa `completed` y no vuelve a exportar ni ejecutar el
pipeline. Si exportación o pipeline fallan, `job_run` registra `failed`,
`finished_at` y `error_message`.
