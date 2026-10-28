# Arquitectura de memoria persistente de Brasaland

## Decisión

La memoria del agente usa **PostgreSQL + pgvector**, en las tablas dedicadas `agent_memories`, `memory_proposals` y `memory_audit_log`, creadas por `migrations/003_create_agent_memory.sql`. PostgreSQL aporta transacciones, filtros por location/categoría, estados de aprobación y auditoría; pgvector permite recuperar hechos relevantes por similitud semántica. Es una sola base operacional, con separación lógica y esquema propio para memoria episódica.

La colección Qdrant `brasaland_knowledge` sigue siendo exclusivamente el RAG curado, de solo lectura para el agente. El agente no inserta propuestas ni memorias en Qdrant. Esta separación evita que una corrección individual altere el conocimiento corporativo, sus evaluaciones de retrieval o su proceso de curación. No se añade Redis como store de memoria: su uso actual es infraestructura de colas/cache y no reemplaza la persistencia auditable.

## Contrato de escritura y lectura

- La generación devuelve `answer` y `propuesta_memoria` en la misma llamada al modelo. La salida se valida como JSON; no hay una segunda llamada de extracción ni un segundo agente.
- Solo `create_proposal` puede crear una propuesta. El agente nunca escribe directamente en `agent_memories`.
- Una propuesta se muestra al usuario; solo una aprobación explícita o una edición explícita aprobada crea memoria. El rechazo no crea ni modifica memoria.
- La API recibe `session_id` estable para asociar turnos. `base_language` puede ser `es` o `en` y controla el idioma de la confirmación; no se presupone español si el cliente elige inglés.
- El índice único parcial `uq_pending_proposal_per_session` garantiza como máximo una propuesta pendiente por sesión. La intención del siguiente turno se clasifica con salida estructurada; solo aprobación, rechazo o edición explícitos resuelven la propuesta. Ambigüedad permanece pendiente y un cambio claro de tema la descarta; ninguno se interpreta como aprobación. La pregunta del turno sigue al flujo normal del agente.
- `search_memories` consulta exclusivamente `agent_memories` y filtra registros archivados; `memory_used` deja auditoría de recuperación. Esos resultados se pasan diferenciados del contexto RAG.

## Hechos permitidos y prohibidos (BRIEFING normativo)

**Se permite proponer** únicamente conocimiento reutilizable en estas clases:
1. Correcciones operativas recurrentes por location: horarios reales, día de entrega de un proveedor específico o excepción local a un procedimiento estándar.
2. Contexto de una escalación resuelta que explique un patrón repetible.
3. Preferencias de comunicación de un gerente de local.

**Nunca se debe proponer ni guardar**:
- Datos personales de clientes de Brasa Points, salvo lo estrictamente operativo que no requiera memoria del agente.
- Cifras de nómina o compensación individual del personal.
- Datos de una conversación puntual sin patrón reutilizable, como una queja de un cliente un día.

La generación también debe devolver `should_store=false` para consultas puntuales (por ejemplo, ticket promedio de ayer), agradecimientos/cierres y traducciones de una sola vez. La validación de servidor aplica categorías permitidas y patrones de exclusión sensibles como defensa adicional; no reemplaza revisión humana ni garantiza detectar toda paráfrasis. El modelo debe fallar a `false` cuando no esté seguro.

## Autoevaluación: casos de control

**Sí proponer, sujeto a confirmación**:
- “El proveedor de vegetales de Medellín entrega los miércoles, no los martes”: corrección operativa local reutilizable.
- “Miami Beach cierra a las 11 pm los fines de semana desde el cambio del mes pasado”: horario recurrente de una location.
- “La alerta repetida de ventas en cero en la location 7 se debió al apagón programado”: explicación de escalación repetible.

**No proponer**:
- “¿Cuál fue el ticket promedio de ayer en Bogotá?”: dato puntual existente en telemetría/pipeline.
- “Gracias, eso resuelve mi duda”: cierre sin nuevo hecho.
- “Traduce esto al inglés para el reporte de Ashley”: tarea de una sola vez.
- Una queja de un cliente específico en un día: conversación puntual, aunque incluya datos descriptivos.
- Nombre/teléfono de un cliente de Brasa Points o salario de un empleado: categoría prohibida.

## Auditoría

`memory_audit_log` registra creación de propuestas, clasificación estructurada del turno frente a propuesta, decisión/resolución, recuperación y mantenimiento, con `session_id`, `actor`, timestamp, propuesta y datos estructurados. Los eventos de propuesta incluyen el mensaje originador; las resoluciones incluyen el mensaje de decisión en `note`/`event_data`. No se persiste el historial completo del chat como memoria.

## Consolidación, archivo y expiración

La consolidación agrupa conceptualmente por `location + category`, pero **no fusiona automáticamente hechos diferentes**: elegir una fila de mayor confianza y archivar el resto podría destruir excepciones operativas válidas. La tarea de mantenimiento archiva hechos con confianza menor a 0.3 y hechos nunca recuperados, con más de 90 días. El umbral conserva datos durante una ventana operativa razonable y evita retener indefinidamente registros que no han resultado útiles; una memoria usada recientemente no expira por esta regla. El archivo es reversible/consultable para auditoría, no un borrado físico.

La función `consolidate_memories()` está expuesta en `/memory/consolidate`; debe programarse en el scheduler operativo (por ejemplo, semanalmente) antes de considerarse una tarea automática recurrente. No se afirma que ya haya un beat periódico configurado.

## Ciclo aprobado (escenario verificable)

1. Turno de sesión `manager-7`: “Corrijo un patrón que se repite: el proveedor de carne de Medellín entrega los martes, no los lunes”.
2. En una sola generación el agente responde y emite una propuesta `proveedores`; ofrece guardarla en el idioma base. `memory_proposals` queda `pending`; `agent_memories` no cambia.
3. Siguiente turno de la misma sesión: “Sí, guárdalo”. El clasificador devuelve `approved`. La transacción inserta el embedding y el hecho aprobado, actualiza la propuesta y escribe auditoría. Si la transacción falla, no queda memoria parcial.
4. Conversación futura, por ejemplo `manager-8`, pregunta por el día de entrega del proveedor de carne de Medellín. La consulta semántica puede recuperar la memoria confirmada y pasarla como contexto diferenciado, sin escribir nada en `brasaland_knowledge`.

## Ciclo rechazado (escenario verificable)

1. Una interacción genera una propuesta pendiente con mensaje originador en auditoría; todavía no se escribe una memoria.
2. El gerente responde “No, no lo guardes”. La clasificación es `rejected`; se cierra la propuesta y se registra el mensaje/decisión.
3. `agent_memories` no recibe una fila ni se actualiza ninguna memoria existente. La pregunta adicional que venga en ese mismo turno continúa normalmente por el agente.

## Despliegue y límites actuales

Antes de activar el flujo, ejecutar la migración 003 en PostgreSQL con la extensión `vector` habilitada. La migración fija `vector(1536)`; el modelo de embeddings configurado debe producir exactamente 1536 dimensiones. La creación SQLModel de arranque excluye estas tres tablas para que no se generen tipos incompatibles. La búsqueda requiere PostgreSQL/pgvector y no es funcional con TinyDB. Ejecutar pruebas con un PostgreSQL real y el gateway configurado antes de afirmar que los ciclos de ejemplo se han demostrado en producción.
