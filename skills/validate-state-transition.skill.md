# Validate State Transition

## Nombre

`Validate State Transition`

## Objetivo

Validar que una transicion propuesta respete las maquinas de estado de `LivestockLoad`, `Offer`, `Assignment` y `Trip`.

## Inputs

- `entityType`.
- Estado origen.
- Evento propuesto.
- Estado destino.
- Actor.
- Contexto minimo de la entidad.

## Outputs

- `isValid`.
- Motivo.
- Requiere operador o no.
- Evento sugerido si aplica.
- Riesgos de consistencia.

## Reglas

- Usar las maquinas de estado definidas en `docs/08-state-machine.md`.
- Rechazar transiciones invalidas.
- Marcar como humana toda confirmacion critica.
- `Assignment.CONFIRMED` solo puede ser confirmado por `Operator`.
- `Trip` no puede iniciar sin `Assignment.CONFIRMED`.
- Cancelaciones requieren actor, motivo si existe y revision humana.

## Casos Borde

- `LivestockLoad INCOMPLETE -> PUBLISHED`.
- `Offer INTERESTED -> Assignment.CONFIRMED`.
- `Assignment PROPOSED -> CONFIRMED` por AI Agent.
- `Trip PLANNED -> COMPLETED`.
- Reapertura por correccion critica.

## Ejemplo Input/Output

Input:

```text
entityType: LivestockLoad
from: INCOMPLETE
event: LOAD_PUBLISHED
to: PUBLISHED
actor: System
```

Output:

```text
isValid: false
reason: una carga incompleta no puede publicarse sin revision humana
requiresHumanReview: true
```

## Que Agentes La Usan

- `Operations Dispatcher Agent`
- `Carrier Conversation Agent`
- `Data Quality Agent`
- `Admin Ops Agent`

