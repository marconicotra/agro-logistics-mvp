# Prompt 34 - Tests

## Contexto

Ya existe una primera implementacion backend. Este prompt amplia y endurece la suite de tests antes de considerar el MVP backend mergeable.

## Docs Que Debes Leer Antes

- `docs/20-testing-strategy.md`
- `docs/08-state-machine.md`
- `docs/09-event-log-design.md`
- `docs/12-whatsapp-agent-architecture.md`
- `docs/19-api-design.md`
- `docs/21-security-privacy.md`
- `skills/*.skill.md`
- `agents/*.md`

## Objetivo

Generar tests robustos para dominio, estado, event log, webhooks, orquestacion, adapter KAPSO mockeado y admin API.

## Scope

Cubrir:

- Domain models.
- State transitions.
- EventLog.
- Idempotencia webhook.
- Conversation orchestration.
- KAPSO adapter mock.
- Admin API.
- Casos borde.

Usar fixtures realistas de hacienda:

- Carga incompleta.
- Productor con ubicacion ambigua.
- Carrier responde "si".
- Carrier responde "puede ser".
- Oferta duplicada.
- Cancelacion posterior.
- Webhook fuera de orden.

## Fuera De Scope

- No reescribir arquitectura.
- No cambiar reglas de dominio.
- No agregar features para facilitar tests.
- No usar servicios externos reales si pueden mockearse.

## Output Esperado

- Suite de tests ampliada.
- Fixtures realistas.
- Tests de error/fallback.
- Tests de idempotencia y eventos.
- Documentacion corta de como correr tests si falta.

## Criterios De Aceptacion

- Tests pasan.
- Webhook duplicado no duplica `Message`, `TripOffer` ni `EventLog`.
- Webhook fuera de orden no rompe estado.
- AI no entiende mensaje -> handoff/fallback.
- Cancelacion genera riesgo y requiere operador.
- Assignment confirmado genera EventLog y Trip.
- Controllers mutantes cubiertos.

## Checklist Final

- [ ] Lei testing strategy.
- [ ] Agregue fixtures realistas.
- [ ] Cubri state transitions.
- [ ] Cubri EventLog.
- [ ] Cubri KAPSO adapter mock.
- [ ] Cubri orchestrator.
- [ ] Cubri admin API.
- [ ] Corri toda la suite.

