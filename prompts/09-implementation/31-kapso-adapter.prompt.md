# Prompt 31 - KAPSO Adapter

## Contexto

El dominio, state machine y EventLog ya existen. Ahora implementar KAPSO como adapter de canal, sin logica de negocio.

## Docs Que Debes Leer Antes

- `docs/12-whatsapp-agent-architecture.md`
- `docs/23-kapso-integration-strategy.md`
- `docs/14-technical-architecture.md`
- `docs/19-api-design.md`
- `docs/21-security-privacy.md`

## Objetivo

Implementar adapter KAPSO reemplazable para inbound/outbound WhatsApp.

## Scope

Implementar:

- Interfaz generica `WhatsAppProvider`.
- `KapsoProvider`.
- Normalizacion inbound a evento interno.
- Envio outbound basico.
- Validacion webhook HMAC.
- Idempotencia por provider + key.
- `correlation_id`.
- `provider_message_id`.
- `conversation_id` externo.
- `workflow_execution_id` si viene.
- Logs tecnicos sin datos sensibles innecesarios.
- Tests de adapter con payloads mock.

## Fuera De Scope

- No implementar logica de negocio.
- No cambiar estados de dominio directamente.
- No implementar matching.
- No implementar pricing.
- No crear `Assignment`.
- No confirmar viajes.
- No guardar reglas comerciales en KAPSO.

## Output Esperado

- Adapter KAPSO aislado.
- Contrato interno normalizado.
- Validacion HMAC testeada.
- Idempotencia testeada.
- Outbound mockeable.

## Criterios De Aceptacion

- KAPSO adapter puede reemplazarse por otro provider.
- Inbound normalizado no toca dominio directamente.
- HMAC invalido rechaza webhook.
- Webhook duplicado no se procesa dos veces.
- Logs no imprimen raw message completo por defecto.
- Tests pasan.

## Checklist Final

- [ ] Lei docs KAPSO.
- [ ] Cree interfaz provider generica.
- [ ] Implemente KapsoProvider sin negocio.
- [ ] Valide HMAC.
- [ ] Agregue idempotencia.
- [ ] Agregue tests.
- [ ] No cambie estados de dominio desde adapter.

