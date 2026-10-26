# Prompt 32 - Conversation Orchestrator

## Contexto

El adapter KAPSO entrega eventos normalizados. Ahora implementar el orquestador conversacional backend que crea conversaciones, mensajes y cargas segun reglas.

## Docs Que Debes Leer Antes

- `docs/05-operating-model.md`
- `docs/07-domain-model.md`
- `docs/08-state-machine.md`
- `docs/09-event-log-design.md`
- `docs/12-whatsapp-agent-architecture.md`
- `agents/producer-conversation-agent.md`
- `agents/carrier-conversation-agent.md`
- `skills/extract-load-data.skill.md`
- `skills/detect-missing-fields.skill.md`

## Objetivo

Implementar un orquestador conversacional testeable y desacoplado de AI provider.

## Scope

Implementar:

- Recepcion de mensajes normalizados.
- Cargar o crear `ConversationSession`.
- Registrar `Message`.
- Invocar AI extraction layer mockeable.
- Detectar datos faltantes.
- Crear o actualizar `ShipmentRequest` segun reglas.
- Generar respuesta simple cuando corresponde.
- Derivar a humano si hay faltantes criticos, ambiguedad o baja confianza.
- Crear `EventLog` por mensaje, extraccion y cambios.
- Fallback si AI falla.

## Fuera De Scope

- No implementar provider AI real obligatorio.
- No implementar UI.
- No implementar matching avanzado.
- No confirmar assignments.
- No resolver cancelaciones automaticamente.
- No poner logica en KAPSO.

## Output Esperado

- Conversation orchestrator como application service.
- AI extraction interface mockeable.
- Tests con mensajes realistas.
- Fallback humano cuando AI falla o hay baja confianza.

## Criterios De Aceptacion

- Mensaje entrante crea `Message` y `ConversationSession`.
- Datos de carga generan `ShipmentRequest` incompleta si falta informacion.
- Faltantes criticos generan `HUMAN_REVIEW_REQUESTED` o respuesta de pregunta.
- AI failure no rompe la operacion.
- KAPSO no es dependencia del dominio.
- Tests pasan.

## Checklist Final

- [ ] Lei docs y agents/skills relevantes.
- [ ] Implemente orchestrator como service.
- [ ] Registre Message y EventLog.
- [ ] Agregue AI interface mockeable.
- [ ] Maneje datos incompletos.
- [ ] Maneje fallback humano.
- [ ] Corri tests.

