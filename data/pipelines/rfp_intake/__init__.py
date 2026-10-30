"""RFP Intake Pipeline — Recepción, clasificación y análisis de RFPs.

Parte 1: orquestador → workers por departamento → sintetizador.
Handoff a Parte 2 via ticket_id + handoff_payload en rfp_ticket.
"""