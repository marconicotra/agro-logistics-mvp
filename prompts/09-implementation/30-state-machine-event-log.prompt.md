# Prompt 30 - State Machine And Event Log

## Contexto

Los modelos de dominio ya existen. Ahora implementar maquinas de estado, validacion de transiciones y EventLog centralizado.

## Docs Que Debes Leer Antes

- `docs/08-state-machine.md`
- `docs/09-event-log-design.md`
- `docs/07-domain-model.md`
- `docs/16-database-modelling.md`
- `docs/20-testing-strategy.md`

## Objetivo

Implementar servicios centralizados para:

- State machines.
- Validacion de transiciones.
- Registro de `EventLog`.
- Idempotencia basica de eventos criticos.

## Scope

Implementar:

- Maquinas de estado para:
  - `ShipmentRequest`
  - `TripOffer`
  - `Assignment`
  - `Trip`
- Servicio `validate_state_transition`.
- Servicio centralizado de eventos.
- Registro de `previous_state` y `new_state`.
- Idempotencia basica para eventos criticos con `idempotency_key`.
- Tests unitarios para transiciones validas e invalidas.
- Tests que verifiquen eventos generados por cambios de estado.

## Fuera De Scope

- No implementar KAPSO adapter.
- No implementar endpoints API completos.
- No implementar AI.
- No implementar matching avanzado.
- No implementar pricing definitivo.

## Output Esperado

- Domain service de transiciones.
- Event logging service.
- Tests unitarios claros.
- Errores explicitos para transiciones invalidas.

## Criterios De Aceptacion

- Transiciones invalidas de docs fallan.
- `Assignment.CONFIRMED` solo puede ocurrir con actor operador.
- `Trip` no puede iniciar sin assignment confirmado.
- Todo cambio de estado probado genera `EventLog`.
- Eventos duplicados con misma idempotency key no duplican efectos.
- Tests pasan.

## Checklist Final

- [ ] Lei state machine y event log docs.
- [ ] Implemente validacion centralizada.
- [ ] Implemente EventLog service.
- [ ] Cubri transiciones invalidas.
- [ ] Cubri idempotencia basica.
- [ ] Corri tests.
- [ ] No implemente canal ni controllers con negocio.

