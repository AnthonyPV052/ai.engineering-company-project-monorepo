"""Canal de chat en vivo del *Manager support agent* — Parte 2.

Paquete del transporte WebSocket. No contiene lógica de negocio del agente: el
grafo (``services/api/graph``) sigue siendo el mismo y este paquete sólo aporta
sesión, pub/sub y protocolo.

- ``events``      contrato de eventos (nombres, payloads, códigos de cierre)
- ``sessions``    entidad ``ChatSession`` persistida + historial de mensajes
- ``pubsub``      canal ``chat.<session_id>`` (productor → consumidores WS)
- ``generation``  orquestación de turnos: stream de tokens + abort real
- ``ws``          router FastAPI con el endpoint WebSocket
"""

from __future__ import annotations

__all__ = ["events", "generation", "pubsub", "sessions", "ws"]
