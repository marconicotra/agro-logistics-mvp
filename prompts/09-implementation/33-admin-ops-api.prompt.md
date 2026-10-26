# Prompt 33 - Admin Ops API

## Contexto

El dominio, EventLog, adapter y orquestador conversacional ya existen. Ahora implementar endpoints operativos para el operador/admin sin construir UI completa.

## Docs Que Debes Leer Antes

- `docs/19-api-design.md`
- `docs/14-technical-architecture.md`
- `docs/08-state-machine.md`
- `docs/09-event-log-design.md`
- `docs/21-security-privacy.md`
- `agents/operations-dispatcher-agent.md`
- `agents/admin-ops-agent.md`

## Objetivo

Implementar API de operacion/admin definida en docs, usando application services existentes.

## Scope

Implementar endpoints para:

- Cargas pendientes.
- Cargas con datos faltantes.
- Ofertas por carga.
- Validar carga.
- Publicar carga.
- Confirmar `Assignment`.
- Cancelar viaje.
- Registrar intervencion manual.
- Activar fallback manual.
- Listar conversacion/mensajes si ya existen modelos.

Todo cambio critico debe generar `EventLog`.

## Fuera De Scope

- No crear UI completa.
- No duplicar logica en controllers.
- No confirmar decisiones sin actor operador.
- No implementar pricing definitivo.
- No implementar matching automatico.
- No mover logica a KAPSO.

## Output Esperado

- Endpoints admin/ops basicos.
- Requests/responses consistentes con `docs/19-api-design.md`.
- Uso de application services/domain services.
- Tests de endpoints criticos.
- Auth/role placeholder o baseline segun seguridad si aun no existe.

## Criterios De Aceptacion

- Controllers no contienen reglas de negocio.
- Confirmar assignment crea EventLog y trip planificado si corresponde.
- Cancelar viaje valida state machine y registra EventLog.
- Fallback manual registra evento y no cambia estados indebidamente.
- Tests pasan.

## Checklist Final

- [ ] Lei API/security/state docs.
- [ ] Implemente endpoints acotados.
- [ ] Use services existentes.
- [ ] Agregue tests.
- [ ] Verifique EventLog en mutaciones.
- [ ] No agregue UI completa.
- [ ] No duplique logica en controllers.

