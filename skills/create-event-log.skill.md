# Create Event Log

## Nombre

`Create Event Log`

## Objetivo

Preparar un evento auditable y consistente con el diseno de `EventLog`.

## Inputs

- `eventType`.
- `actorType`.
- `actorId`, si existe.
- `entityType`.
- `entityId`.
- Entidades relacionadas.
- Estado anterior y nuevo, si aplica.
- Resumen.
- Fuente.
- Payload conceptual.

## Outputs

- Evento estructurado listo para registrar.
- Campos faltantes del evento.
- Advertencias de auditoria.

## Reglas

- Todo evento debe tener `eventType`, `occurredAt`, `actorType`, `entityType`, `entityId`, `summary` y `source`.
- Si cambia estado, incluir `previousState` y `newState`.
- No registrar confirmaciones criticas como si fueran de AI Agent.
- Incluir `correlationId` cuando el evento pertenezca a un flujo de conversacion.
- No sobrescribir eventos historicos.

## Casos Borde

- Evento generado desde mensaje sin usuario identificado.
- Cambio de estado sin estado anterior disponible.
- Sugerencia de AI Agent que no es decision final.
- Cancelacion sin motivo informado.
- Varios eventos derivados del mismo mensaje.

## Ejemplo Input/Output

Input:

```text
eventType: OFFER_RECEIVED
actorType: Carrier
entityType: Offer
entityId: offer pendiente
relatedEntityIds: loadId, messageId
summary: carrier responde interesado con precio estimado
source: whatsapp
```

Output:

```text
eventType: OFFER_RECEIVED
actorType: Carrier
entityType: Offer
relatedEntityIds: loadId, messageId
summary: carrier responde interesado con precio estimado
source: whatsapp
warnings: entityId debe completarse al persistir la Offer
```

## Que Agentes La Usan

- `Operations Dispatcher Agent`
- `Producer Conversation Agent`
- `Carrier Conversation Agent`
- `Matching Agent`
- `Pricing Agent`
- `Data Quality Agent`
- `Admin Ops Agent`

