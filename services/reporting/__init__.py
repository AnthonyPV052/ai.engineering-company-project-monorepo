"""Módulo de reporting — endpoints para el pipeline de desempeño de negocio.

Expone los KPIs calculados por el pipeline a través de tres endpoints
bajo ``/reporting/*``:

- ``GET  /reporting/weekly-location-performance`` — KPIs semanales por local
- ``GET  /reporting/pipeline-runs/latest``        — Estado de la última corrida
- ``POST /reporting/pipeline-runs``               — Disparar corrida manual
"""