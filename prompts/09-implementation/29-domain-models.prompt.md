# Prompt 29 - Domain Models

## Contexto

El backend base ya existe. Ahora implementar modelos de dominio y persistencia basica sin canal, sin KAPSO y sin logica avanzada.

Backend sigue siendo source of truth.

## Docs Que Debes Leer Antes

- `docs/07-domain-model.md`
- `docs/08-state-machine.md`
- `docs/15-database-architecture.md`
- `docs/16-database-modelling.md`
- `DATA_CATALOG.md`
- `docs/14-technical-architecture.md`

## Objetivo

Implementar entidades core del dominio y modelo de datos base, manteniendo separacion clara entre necesidad, oferta, asignacion y ejecucion.

## Scope

Implementar:

- Entidades core segun `docs/07-domain-model.md`.
- Modelos internos para:
  - `User`
  - `Producer`
  - `Carrier`
  - `Vehicle`
  - `ShipmentRequest` como implementacion de `LivestockLoad`
  - `TripOffer` como implementacion de `Offer`
  - `Assignment`
  - `Trip`
  - `ConversationSession`
  - `Message`
  - `EventLog`
  - `Location`
  - `Document`
  - `PaymentTerms`
  - `RiskFlag`
- Schemas/DTOs si el stack los usa.
- Repositorios basicos.
- Validaciones minimas de campos requeridos.
- Timestamps y soft delete cuando aplique.
- Mapeo claro de nombres: `ShipmentRequest = LivestockLoad`, `TripOffer = Offer`.

## Fuera De Scope

- No implementar WhatsApp.
- No implementar KAPSO.
- No implementar matching avanzado.
- No implementar pricing definitivo.
- No implementar state machine completa todavia.
- No implementar endpoints admin todavia.
- No implementar AI extraction.

## Output Esperado

- Modelos de dominio/persistencia creados.
- Repositorios basicos con operaciones simples.
- Tests minimos de creacion/validacion de modelos.
- Documentacion corta si hay decisiones de naming.

## Criterios De Aceptacion

- `ShipmentRequest`, `Trip`, `TripOffer` y `Assignment` estan separados.
- `Message` y `ConversationSession` no contienen reglas de negocio.
- No hay logica de canal en entidades.
- No hay pricing definitivo ni assignment automatico.
- Tests pasan.
- Nombres y campos son consistentes con docs.

## Checklist Final

- [ ] Lei docs requeridos.
- [ ] Modele entidades core.
- [ ] Separe necesidad/oferta/asignacion/viaje.
- [ ] Agregue repositorios basicos.
- [ ] Agregue tests minimos.
- [ ] No agregue KAPSO ni WhatsApp.
- [ ] No invente reglas de negocio.

