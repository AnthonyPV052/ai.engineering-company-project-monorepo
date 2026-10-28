export const INCIDENTS_REQUIRED_FIELDS = [
  "incidente_id",
  "cliente_id",
  "categoria",
  "estado",
  "fecha_creacion",
] as const;

export const INCIDENTS_ALLOWED_CATEGORIES = [
  "queja",
  "solicitud",
  "fallo_operativo",
] as const;

export const INCIDENTS_ALLOWED_STATES = [
  "abierto",
  "en_proceso",
  "resuelto",
  "cerrado",
] as const;

export const INCIDENTS_CSV_FIELDS = [
  "incidente_id",
  "cliente_id",
  "email_cliente",
  "telefono_cliente",
  "categoria",
  "estado",
  "prioridad",
  "fecha_creacion",
  "tiempo_resolucion_horas",
] as const;

export const INCIDENTS_EXPECTED_SUMMARY = {
  total_registros: 100,
  registros_validos: 88,
  registros_invalidos: 12,
  incidencias_por_categoria: {
    queja: 30,
    solicitud: 28,
    fallo_operativo: 30,
  },
  incidencias_por_estado: {
    abierto: 20,
    en_proceso: 22,
    resuelto: 24,
    cerrado: 22,
  },
  tiempo_promedio_resolucion_horas: 19.18,
};
