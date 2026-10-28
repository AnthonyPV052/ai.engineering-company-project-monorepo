-- ============================================================================
-- Agent Memory Store — Híbrido relacional + vectorial (pgvector)
-- 
-- Este esquema es un store separado del RAG (colecciones Qdrant
-- "brasaland_knowledge"). Las memorias de agente son hechos episódicos
-- aprobados por supervisores, NO documentos curados de conocimiento.
-- Mezclarlos rompería los evals de retrieval y los controles de poison.
-- ============================================================================

-- Extensión pgvector para búsqueda semántica
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- Tabla: agent_memories
-- Propósito: Almacena hechos operativos aprendidos por el agente.
--            Cada registro es un hecho atómico aprobado por un supervisor.
--            NO almacena conversaciones completas, solo conocimiento
--            episódico reutilizable.
-- ============================================================================
CREATE TABLE IF NOT EXISTS agent_memories (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Hecho memorizado (texto legible)
    summary         TEXT NOT NULL,
    
    -- Categorización para consolidación
    location        VARCHAR(128) NOT NULL DEFAULT '',  -- "Medellín", "Miami Beach", "" si es global
    category        VARCHAR(64) NOT NULL DEFAULT '',    -- "horarios", "proveedores", "incidentes_conocidos", "preferencias"
    
    -- Embedding para búsqueda semántica (dimensión configurable, ej. 768 o 1536)
    embedding       vector(1024),
    
    -- Metadatos de confianza
    confidence      FLOAT NOT NULL DEFAULT 1.0,
    
    -- Quién aprobó esto
    approved_by     VARCHAR(256) NOT NULL DEFAULT '',
    approved_at     TIMESTAMPTZ,
    
    -- Ciclo de vida
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    -- Contador de usos (cuántas veces se recuperó como contexto)
    usage_count     INT NOT NULL DEFAULT 0,
    last_used_at    TIMESTAMPTZ,
    
    -- Soft-delete / archive
    archived        BOOLEAN NOT NULL DEFAULT FALSE,
    archived_at     TIMESTAMPTZ,
    
    -- Versión de consolidación (para deduplicación)
    consolidated_version INT NOT NULL DEFAULT 1,
    parent_memory_id     UUID,  -- si esta memoria es una consolidación de otras
    
    CONSTRAINT fk_parent_memory
        FOREIGN KEY (parent_memory_id) REFERENCES agent_memories(id)
        ON DELETE SET NULL
);

-- Índices
CREATE INDEX IF NOT EXISTS ix_agent_memories_location
    ON agent_memories (location);

CREATE INDEX IF NOT EXISTS ix_agent_memories_category
    ON agent_memories (category);

CREATE INDEX IF NOT EXISTS ix_agent_memories_archived
    ON agent_memories (archived);

CREATE INDEX IF NOT EXISTS ix_agent_memories_created_at
    ON agent_memories (created_at DESC);

-- Índice vectorial (IVFFlat para búsqueda approximate; ajustar listas según
-- volumen esperado; con 14 locations, 200 listas es suficiente para empezar)
CREATE INDEX IF NOT EXISTS ix_agent_memories_embedding
    ON agent_memories
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 200);

-- Índice compuesto para consolidación por location+categoría
CREATE INDEX IF NOT EXISTS ix_agent_memories_loc_cat
    ON agent_memories (location, category);

-- ============================================================================
-- Tabla: memory_proposals (propuestas pendientes)
-- Propósito: Solo puede haber UNA propuesta pendiente a la vez por sesión.
--            El agente nunca escribe directamente en agent_memories.
--            Primero propone, el usuario confirma o rechaza, y solo entonces
--            se persiste (o se descarta).
-- ============================================================================
CREATE TABLE IF NOT EXISTS memory_proposals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- La conversación que originó la propuesta
    session_id      VARCHAR(256) NOT NULL,
    conversation_id UUID,
    
    -- Texto propuesto para la memoria
    proposed_summary    TEXT NOT NULL,
    proposed_location   VARCHAR(128) NOT NULL DEFAULT '',
    proposed_category   VARCHAR(64) NOT NULL DEFAULT '',
    proposed_confidence FLOAT NOT NULL DEFAULT 0.8,
    
    -- Contexto: qué dijo el usuario que motivó la propuesta
    trigger_message TEXT NOT NULL DEFAULT '',
    
    -- Estado: pending | approved | rejected | discarded | edited
    status          VARCHAR(16) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected', 'discarded', 'edited')),
    
    -- Si fue aprobada, referencia a la memoria creada
    approved_memory_id UUID,
    
    -- Metadata de resolución
    resolved_by     VARCHAR(256) NOT NULL DEFAULT '',
    resolved_at     TIMESTAMPTZ,
    resolution_note TEXT NOT NULL DEFAULT '',
    
    -- Timestamps
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT fk_approved_memory
        FOREIGN KEY (approved_memory_id) REFERENCES agent_memories(id)
        ON DELETE SET NULL,
        
    -- La unicidad parcial se aplica mediante un índice separado.
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_proposal_per_session
    ON memory_proposals (session_id)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS ix_memory_proposals_session_status
    ON memory_proposals (session_id, status);

-- ============================================================================
-- Tabla: audit_log (registro auditable de todas las decisiones de memoria)
-- Propósito: Cada propuesta, sea aprobada, rechazada o descartada, queda
--            registrada. Es la pista de auditoría.
-- ============================================================================
CREATE TABLE IF NOT EXISTS memory_audit_log (
    id              BIGSERIAL PRIMARY KEY,
    
    -- Relación con la propuesta (si aplica)
    proposal_id     UUID,
    
    -- Tipo de evento
    event_type      VARCHAR(32) NOT NULL,  -- 'proposal_created', 'approved', 'rejected', 'discarded', 'edited', 'consolidated', 'memory_used'
    
    -- Descripción legible
    description     TEXT NOT NULL DEFAULT '',
    
    -- Datos del evento (JSON estructurado)
    event_data      JSONB NOT NULL DEFAULT '{}'::jsonb,
    
    -- Contexto de la conversación
    session_id      VARCHAR(256) NOT NULL DEFAULT '',
    
    -- Quién (usuario o sistema)
    actor           VARCHAR(256) NOT NULL DEFAULT 'system',
    
    -- Timestamp
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_memory_audit_log_proposal
    ON memory_audit_log (proposal_id);

CREATE INDEX IF NOT EXISTS ix_memory_audit_log_event_type
    ON memory_audit_log (event_type);

CREATE INDEX IF NOT EXISTS ix_memory_audit_log_created_at
    ON memory_audit_log (created_at DESC);

CREATE INDEX IF NOT EXISTS ix_memory_audit_log_session
    ON memory_audit_log (session_id);