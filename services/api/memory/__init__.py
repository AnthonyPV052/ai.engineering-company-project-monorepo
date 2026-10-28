"""Agent Memory System for Brasaland.

Este paquete implementa un sistema de memoria episódica para el agente de
soporte a gerentes de localización de Brasaland.

Arquitectura
------------
Híbrido relacional + vectorial:
  - PostgreSQL + pgvector para almacenamiento persistente y búsqueda semántica.
  - Store separado del RAG (Qdrant "brasaland_knowledge"). Las memorias de
    agente son hechos episódicos aprobados por supervisores, NO documentos
    curados de conocimiento. Mezclarlos rompe evals de retrieval y controles
    de poison.

Flujo
-----
1. El agente responde al usuario + genera un campo `propuesta_memoria`
   estructurado en la misma llamada (auto-evaluación).
2. Si hay propuesta, se guarda como "pending" en memory_proposals.
3. El usuario aprueba, rechaza, edita, o ignora la propuesta.
4. Si aprueba → se persiste en agent_memories con embedding.
5. Si rechaza/ignora → se registra en audit_log, la propuesta se cierra.
6. En consultas futuras, el agente recupera memorias relevantes por
   similitud coseno (umbral > 0.85) y las inyecta como contexto.

Política de Consolidación
-------------------------
- Memorias se agrupan por location + categoría.
- Consolidación semanal: fusiona entradas duplicadas o muy similares
  dentro del mismo grupo.
- Entradas con confidence < 0.3 se archivan automáticamente.
- Entradas con usage_count = 0 por más de 90 días se archivan.

Límites
-------
- Solo una propuesta pendiente por sesión a la vez.
- El agente NUNCA escribe directamente en agent_memories.
- Las categorías permitidas: "horarios", "proveedores",
  "incidentes_conocidos", "preferencias", "general".
"""

__version__ = "0.1.0"