# Prompts De Implementacion

Este directorio conserva prompts historicos de implementacion y revision creados para una etapa anterior de AGRO Logistics. No representa el roadmap actual ni debe ejecutarse como una secuencia de bootstrap.

El roadmap vigente esta en [`docs/plan-y-bitacora.md`](../docs/plan-y-bitacora.md), y las reglas de producto en [`docs/04-mvp-scope.md`](../docs/04-mvp-scope.md) y los documentos de dominio. Antes de reutilizar un prompt, actualizarlo con esos documentos, comprobar que el objetivo siga pendiente y revisar cambios locales.

Los prompts estan pensados para ejecucion secuencial. Cada prompt debe producir un cambio chico, revisable y alineado con la documentacion existente.

## Como Usar Los Prompts

1. Abrir el prompt correspondiente.
2. Copiarlo completo en Codex.
3. Ejecutarlo en un branch limpio o con cambios controlados.
4. Revisar el diff antes de pasar al siguiente prompt.
5. Correr tests definidos o agregados por cada etapa.
6. No avanzar si hay decisiones de dominio no documentadas.

## Secuencia Historica (No Usar Como Roadmap)

1. `prompts/09-implementation/28-backend-bootstrap.prompt.md`
2. `prompts/09-implementation/29-domain-models.prompt.md`
3. `prompts/09-implementation/30-state-machine-event-log.prompt.md`
4. `prompts/09-implementation/31-kapso-adapter.prompt.md`
5. `prompts/09-implementation/32-conversation-orchestrator.prompt.md`
6. `prompts/09-implementation/33-admin-ops-api.prompt.md`
7. `prompts/09-implementation/34-tests.prompt.md`
8. `prompts/10-review/35-review-implementation.prompt.md`

## Reglas Antes De Correr Cada Prompt

- Leer los documentos listados en el prompt.
- Confirmar que el prompt anterior este implementado y testeado.
- No mezclar tareas de prompts distintos.
- No agregar features fuera del MVP.
- No mover logica de negocio a KAPSO, controllers o adapters.
- Mantener backend como unica fuente de verdad.
- Todo cambio de estado debe pasar por domain/application services y generar `EventLog`.

## Documentos Base A Conocer

- `README.md`
- `AGENTS.md`
- `skills/README.md`
- `docs/04-mvp-scope.md`
- `docs/05-operating-model.md`
- `docs/07-domain-model.md`
- `docs/08-state-machine.md`
- `docs/09-event-log-design.md`
- `docs/12-whatsapp-agent-architecture.md`
- `docs/14-technical-architecture.md`
- `docs/15-database-architecture.md`
- `docs/16-database-modelling.md`
- `docs/19-api-design.md`
- `docs/20-testing-strategy.md`
- `docs/21-security-privacy.md`
- `docs/23-kapso-integration-strategy.md`

## Como Validar Outputs

- El diff debe estar limitado al scope del prompt.
- Los tests nuevos o existentes deben pasar.
- La implementacion debe usar nombres consistentes con docs.
- No debe haber decisiones criticas automaticas.
- No debe haber logica de negocio en KAPSO adapter.
- No debe haber cambios de estado sin `EventLog`.
- No debe haber secretos en el repo.

## Como Evitar Que Codex Invente Reglas

- Exigir lectura de docs relevantes en cada prompt.
- Si falta una regla de negocio, pedir que la marque como TODO/documentacion pendiente.
- No aceptar supuestos no documentados para pricing, matching o asignacion.
- Mantener cada prompt chico y con fuera de scope explicito.
- Usar el prompt de review antes de merge.

## Primer Prompt Para Empezar A Codear

Los prompts de esta carpeta pueden servir como referencia de decisiones iniciales. No empezar por `28-backend-bootstrap.prompt.md`: el backend ya existe y cualquier nueva tarea debe salir de la bitacora actual.
