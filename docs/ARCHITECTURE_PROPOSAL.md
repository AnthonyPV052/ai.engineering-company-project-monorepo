# Backend Architecture Proposal - Brasaland Digital

## 1. Business context and backend goals

Brasaland opera 14 restaurantes en Colombia y Estados Unidos con dos monedas (COP y USD), distintos flujos operativos y una necesidad urgente de visibilidad en tiempo real. El estado actual presenta baja integracion de sistemas (POS no unificados, pedidos por WhatsApp, reportes en Excel/PDF) y poca trazabilidad para la direccion ejecutiva.

### Objetivos del backend

- Centralizar datos operativos (ventas, locales, inventario, compras, clientes y RRHH operativo basico) en una API unica.
- Proveer informacion confiable y casi en tiempo real para dashboards de operaciones y direccion.
- Soportar crecimiento por dominios sin mezclar reglas de negocio con detalles de transporte (HTTP) o persistencia.
- Habilitar integraciones futuras (apps moviles, CRM, BI, automatizaciones y asistentes de IA) mediante contratos API estables.
- Garantizar seguridad, auditabilidad y configuracion por entorno para operar en dos paises.

## 2. Chosen architectural pattern and justification

Se propone una arquitectura en capas con orientacion por dominio (layered + domain-oriented modules).

### Capas

- Presentacion/API: routers FastAPI, validacion de entrada/salida con Pydantic y manejo de dependencias.
- Aplicacion/Servicios: casos de uso y reglas de negocio (calculo de KPIs, validaciones operativas, orquestacion entre fuentes).
- Dominio: entidades, contratos y lenguaje de negocio compartido.
- Datos/Infraestructura: repositorios, ORM/adaptadores, conectores externos y telemetria.

### Justificacion para Brasaland

- Necesidad multipais: separa reglas de conversion monetaria y reporting por pais de los detalles de cada fuente de datos.
- Escalabilidad funcional: cada area (operaciones, compras, marketing, RRHH, calidad) puede evolucionar como dominio con fronteras claras.
- Mantenibilidad: evita que los routers se conviertan en puntos de logica compleja.
- Testabilidad: permite pruebas unitarias en servicios y dominio sin depender de HTTP o base de datos.
- Integracion progresiva: facilita reemplazar hojas de calculo y sistemas legacy por adaptadores sin romper contratos API.

## 3. Backend structure proposal (folders/modules/domains)

La propuesta se implementa dentro del monorepo, en una aplicacion backend dedicada (por ejemplo en apps/brasaland-api) y consumiendo tipos compartidos de packages/shared cuando aplique.

```text
apps/
  brasaland-api/
    app/
      main.py
      api/
        v1/
          router.py
          health.py
          auth.py
          stores.py
          sales.py
          inventory.py
          suppliers.py
          customers.py
          hr.py
          training.py
          executive.py
      services/
        sales_service.py
        inventory_service.py
        supplier_service.py
        customer_service.py
        hr_service.py
        training_service.py
        executive_service.py
      domain/
        entities/
          store.py
          sale.py
          supplier.py
          employee.py
        value_objects/
          money.py
          date_range.py
        interfaces/
          sales_repository.py
          supplier_repository.py
      repositories/
        sql/
          sales_repository_sql.py
          supplier_repository_sql.py
        external/
          pos_adapter.py
          spreadsheet_adapter.py
      schemas/
        sales.py
        inventory.py
        suppliers.py
        customers.py
        hr.py
        executive.py
      core/
        config.py
        security.py
        dependencies.py
        logging.py
        exceptions.py
      db/
        base.py
        session.py
        models/
      telemetry/
        metrics.py
        traces.py
      tests/
        unit/
        integration/
```

### Limites de responsabilidad

- api: solo HTTP, codigos de estado, autenticacion/autorizacion por dependencia, sin logica de negocio pesada.
- schemas: contratos de entrada/salida Pydantic, desacoplados de entidades internas.
- services: casos de uso y reglas; orquesta repositorios y servicios auxiliares.
- domain: conceptos nucleares y contratos de repositorio.
- repositories: implementaciones concretas para DB y sistemas externos.
- core: configuracion centralizada, DI compartida, seguridad y observabilidad.

## 4. FastAPI endpoint and router organization

Se usara versionado con prefijo comun /api/v1 y routers por dominio, no un archivo unico de rutas.

### Estrategia de routers

- app/api/v1/router.py como agregador principal.
- Un APIRouter por dominio con tags claras.
- Separacion entre endpoints publicos (health, auth login inicial) y protegidos (operacion diaria).

### Ejemplo de agrupacion de endpoints

- /api/v1/health
- /api/v1/auth
- /api/v1/stores
- /api/v1/sales
- /api/v1/inventory
- /api/v1/suppliers
- /api/v1/customers
- /api/v1/hr
- /api/v1/training
- /api/v1/executive

### Convenciones FastAPI aplicadas

- Routers divididos por dominio para escalar sin acoplamiento.
- Schemas Pydantic separados de servicios para contratos estables.
- Dependency Injection (Depends) para auth, DB session, permisos, contexto de pais/moneda.
- Settings centralizados via app/core/config.py y variables de entorno.
- Estructura predecible para incorporar nuevos dominios sin romper consistencia.

## 5. Frontend-backend separation strategy

La separacion frontend-backend sera explicita desde el inicio para evitar acoplamientos con la app de seguimiento de candidatos existente y futuras apps de Brasaland.

### Decisiones

- Integracion contract-first: el frontend consume exclusivamente schemas/versiones publicadas por la API.
- Backend sin dependencias de UI: no incluir logica de presentacion en servicios ni en dominio.
- CORS por entorno:
  - local: origenes de desarrollo habilitados.
  - staging/prod: lista blanca estricta por dominio.
- Configuracion por entorno con .env y settings tipados:
  - .env.local
  - .env.staging
  - .env.production
- Versionado de API para cambios no retrocompatibles (/api/v1, /api/v2).
- Monorepo decision: mantener frontend y backend en el mismo repositorio para compartir contexto de negocio, documentacion y tipos comunes; evitar repo separado en la fase inicial para acelerar entrega.

## 6. Risks and attention points with mitigations

### Riesgo 1: fronteras de dominio difusas

- Impacto: logica duplicada entre operaciones, executive y sales; incremento de deuda tecnica.
- Mitigacion:
  - Definir ownership por dominio y reglas de contribucion.
  - Revisiones de arquitectura en PRs para validar limites.
  - Contratos de servicio y repositorio explicitados en domain/interfaces.

### Riesgo 2: reglas de negocio dentro de routers

- Impacto: baja testabilidad, endpoints fragiles, mantenimiento costoso.
- Mitigacion:
  - Politica de "thin routers": routers solo validan y delegan.
  - Cobertura unitaria enfocada en services.
  - Checklist de code review que bloquee logica de negocio en api.

### Riesgo 3: deriva de configuracion entre entornos

- Impacto: incidentes en produccion por CORS, credenciales, monedas o zonas horarias.
- Mitigacion:
  - Settings centralizados y tipados.
  - Validacion de variables obligatorias al boot.
  - Pipeline CI con smoke tests por entorno.


## 7. Initial technical decisions and next steps

### Decisiones iniciales

- Framework backend: FastAPI.
- Organizacion: arquitectura en capas orientada por dominio.
- Contratos: Pydantic para request/response.
- Persistencia: repositorios desacoplados del framework web.
- Seguridad inicial: JWT para endpoints protegidos y RBAC basico por rol.
- Observabilidad: logging estructurado y metricas de salud/latencia desde el inicio.

### Siguientes pasos

1. Crear esqueleto de app backend en apps/brasaland-api con estructura propuesta.
2. Implementar primero dominios core: stores, sales, inventory y executive.
3. Definir OpenAPI inicial y alinear contratos con consumidores frontend.
4. Configurar CI minimo: lint, tests unitarios y chequeo de settings.
5. Incorporar telemetria de ventas near real-time y primer dashboard ejecutivo.

Esta propuesta busca un equilibrio entre velocidad de entrega y solidez arquitectonica para soportar crecimiento multipais, nuevos canales digitales y decisiones operativas basadas en datos confiables.
