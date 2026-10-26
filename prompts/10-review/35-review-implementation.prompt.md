# Prompt 35 - Review Implementation

## Contexto

Usar este prompt al final de una etapa de implementacion o antes de merge. Actua como auditor tecnico del MVP.

## Docs Que Debes Leer Antes

- `README.md`
- `AGENTS.md`
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

## Objetivo

Revisar la implementacion contra documentacion, arquitectura y reglas MVP.

## Scope

Auditar:

- Consistencia con docs.
- Acoplamiento indebido con KAPSO.
- Logica de negocio en controllers.
- Logica de negocio en adapters.
- Ausencia de `EventLog`.
- Falta de tests.
- Endpoints que cambian estado sin auditoria.
- Naming inconsistente.
- Data model inconsistente.
- Riesgos de seguridad.
- Secretos commiteados.
- Idempotencia de webhooks.
- Transiciones de estado.

## Fuera De Scope

- No implementar fixes grandes en este prompt.
- No redefinir dominio.
- No agregar features.
- No aceptar cambios que contradigan documentacion.

## Output Esperado

Devolver una revision con:

- Issues criticos.
- Issues medios.
- Mejoras recomendadas.
- Checklist de bloqueo antes de merge.
- Archivos/lineas cuando sea posible.

## Criterios De Aceptacion

La revision debe bloquear merge si encuentra:

- KAPSO cambiando dominio.
- Assignment o trip confirmado sin operador.
- Cambio de estado sin EventLog.
- Webhook no idempotente.
- Logica critica en controller.
- Secretos o datos sensibles en logs.
- Tests ausentes para transiciones criticas.

## Checklist De Revision

- [ ] Lei docs requeridos.
- [ ] Revise boundaries por capa.
- [ ] Revise state machine.
- [ ] Revise EventLog en mutaciones.
- [ ] Revise idempotencia.
- [ ] Revise seguridad basica.
- [ ] Revise tests.
- [ ] Clasifique issues por severidad.

## Formato De Respuesta Requerido

Usar este formato:

```text
Issues criticos
- [archivo:linea] Descripcion, impacto, recomendacion.

Issues medios
- [archivo:linea] Descripcion, impacto, recomendacion.

Mejoras recomendadas
- Descripcion.

Checklist bloqueo antes de merge
- [ ] Item.
```

