## Estado actual de desarrollo
 - Página "Home" de Braqsaland creada
 - Talent pipeline tracker creado.
 - Formulario de contacto creado y navegable desde la página principal
## próximos pasos previstos
- Añadir features para resolver los problemas pendientes.

## avances recientes
- Se implementó el indexador RAG de Brasaland: parsing semántico de la base de
	conocimiento, embeddings mediante gateway configurable, colección Qdrant
	`brasaland_knowledge` e idempotencia clean-and-reload documentada.
- Se ajustó el analizador de incidencias para compatibilidad con incidents-brasaland.csv.
- Se actualizó el expected de evaluación de incidencias con las métricas del dataset objetivo.
- Se implementó un backend de proveedores con FastAPI, TinyDB y seeder idempotente.
- Se añadió interfaz de proveedores en backoffice y navegación desde la web.
- Se creó la estructura solicitada en monorepo: services/api y uis/application/app/suppliers.
- Se implementó AUTH-01 en services/api: módulos users/profiles en TinyDB, login JWT, dependencia get_current_user y protección de rutas sensibles.
- Se corrigió la resolución de `src/data/sample` para que el build de Next.js use el módulo TypeScript `sample.ts`.
- Se integró AUTH-01 en website: login, registro, almacenamiento local de JWT, guard cliente y Bearer en el directorio de proveedores.
- Se añadió el perfil de usuario en el backoffice, con edición de datos opcionales, acceso de perfil, aviso de campos pendientes y navegación a inicio.
- Se incorporó recuperación y cambio de contraseña: tokens de un solo uso, envío por Resend y vistas públicas/protegidas en website.
- Se implementó el gestor centralizado de incidencias en services/api: CRUD de lectura/creación, filtros, resumen agregado, transiciones de estado y manejo uniforme de errores.
- Se añadió el gestor de incidencias al backoffice: registro con validación y feedback, listado filtrable con actualización de estado y panel de resumen resiliente.
- Se conectó el seeder del histórico `incidents-brasaland.csv` al almacenamiento TinyDB del API y al comando estándar de seed.
- Se añadió el job nocturno independiente de FastAPI: migración `job_runs`, máquina de estados con lock distribuido, exportación idempotente de telemetría y documentación del cron externo.
- Se completó la validación de Fase 5/5b/6 del RAG: pruebas unitarias aisladas, evaluación Recall@3 reproducible, respuesta segura sin contexto y exposición separada de `setup`, `embed`, `retrieve` y `query`.
- Se implementó la fase 2 del RAG en `data/pipelines/rag.py`: recuperación
  semántica con umbral, generación separada y API pública `query()` con reglas
  anti-alucinación, alérgenos y monedas.
- Se añadió POST `/knowledge/query` en FastAPI, conectado exclusivamente a `data/pipelines.rag.query`, y página BackOffice `/backoffice/knowledge` con estados de carga y error.
- Se corrigió el cierre de trazas del agente (acepta fuentes y orden de ejecución), que provocaba HTTP 502 incluso tras completar el grafo.
- Se corrigió la tool de incidencias para usar HTTP de la biblioteca estándar disponible en la imagen activa; el GET confirmado responde y valida `IncidentResponse` manteniendo el límite de 7 s.
- Se añadió degradación explícita para indisponibilidad RAG: timeout de recuperación, error técnico en la traza, fallback seguro y preservación del estado de incidencia confirmado en solicitudes mixtas.
- Diagnóstico operativo: el contenedor no resuelve el DNS de `llm.4geeks.ai` ni el host Supabase configurado; Qdrant resuelve por DNS interno pero HTTP no responde desde backend. No se cambiaron endpoints ni credenciales externas.
- Validación Docker: consultas incident-only, mixtas y RAG-only devuelven HTTP 200; los fallos de documentación se comunican honestamente y no ocultan el estado verificado del ticket.
- Auditoría de tool del agente: GET de incidencias no requiere auth en el router local; se admite `INCIDENTS_API_TOKEN` Bearer para un servicio externo protegido. Las fuentes de respuesta/traza se derivan de nodos realmente ejecutados, excluyendo retrieval omitido.
- Se añadieron dos evals de routing (ticket explícito y política de proveedores), además de checks para token/GET/timeout tipado y fallbacks de no encontrado/error. No se pudo instalar `pytest` por fallo DNS de PyPI; se ejecutaron equivalentes focalizados en el entorno `uv` de Docker (5 rutas y checks de trazas, transporte y fallback), todos pasaron. `compileall` y `git diff --check` también pasaron.
- Se elevó el presupuesto del nodo de retrieval RAG a 60 s (configurable mediante `AGENT_RAG_RETRIEVAL_TIMEOUT_SECONDS`) y el timeout HTTP de Qdrant a 20 s (`RAG_QDRANT_TIMEOUT_SECONDS`), con defaults alineados en Compose. La documentación aclara que esto ayuda con latencia transitoria, no con DNS/conectividad permanentemente fallida.
- Se elevó el presupuesto del nodo RAG a 75 s; embeddings usa timeout de 30 s con un retry de timeout explícito, y Qdrant usa timeout de 20 s con reintento acotado de `ConnectTimeout`. Compose fue recreado con `QDRANT_URL` vía `host.docker.internal`; el endpoint HTTP responde, aunque no reporta colecciones.
- Validación desde backend: `LLM_GATEWAY` continúa sin resolución DNS (`gaierror`) y el embedding falla con `APIConnectionError`; Qdrant está accesible pero su lista de colecciones está vacía. Confirmar el Qdrant publicado y reparar DNS/egress del contenedor o proporcionar resolver/proxy aprobado antes de ejecutar indexación. No se cambiaron credenciales ni DNS externos.
