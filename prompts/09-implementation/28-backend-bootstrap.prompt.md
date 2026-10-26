# Prompt 28 - Backend Bootstrap

## Contexto

Estamos construyendo AGRO Logistics MVP. Este es el primer prompt de implementacion de codigo.

Backend es la unica fuente de verdad. KAPSO es canal/adaptador. No implementar dominio todavia.

## Docs Que Debes Leer Antes

- `README.md`
- `AGENTS.md`
- `docs/04-mvp-scope.md`
- `docs/14-technical-architecture.md`
- `docs/20-testing-strategy.md`
- `docs/21-security-privacy.md`

## Objetivo

Crear la estructura base del backend con el stack recomendado por la arquitectura tecnica.

## Scope

Implementar:

- Estructura de carpetas del backend.
- Configuracion base.
- Entorno local documentado.
- Dependencias iniciales.
- Health endpoint.
- Settings/config.
- Logging basico estructurado.
- Estructura inicial para tests.
- Test minimo de health.

Usar el stack recomendado:

- Backend: FastAPI.
- DB futura: PostgreSQL.
- ORM futuro: SQLAlchemy 2.x o SQLModel.
- Tests: pytest o equivalente del stack.

## Fuera De Scope

- No implementar logica de negocio.
- No implementar modelos de dominio.
- No integrar KAPSO todavia.
- No crear endpoints de dominio.
- No crear migraciones.
- No implementar AI layer.
- No implementar admin API.

## Output Esperado

- Proyecto backend ejecutable localmente.
- Health endpoint funcionando.
- Config centralizada para env vars.
- Logging basico.
- Tests iniciales corriendo.
- README o nota minima de como correr localmente si el repo no lo tiene.

## Criterios De Aceptacion

- `GET /health` responde estado ok.
- Tests pasan localmente.
- No hay secretos commiteados.
- No hay logica de dominio en el bootstrap.
- La estructura permite agregar capas: API, application services, domain, repositories, adapters, jobs.
- El diff no toca documentos de negocio salvo nota minima necesaria para correr.

## Checklist Final

- [ ] Lei los docs requeridos.
- [ ] Use FastAPI salvo razon documentada.
- [ ] Agregue health endpoint.
- [ ] Agregue config/settings.
- [ ] Agregue logging basico.
- [ ] Agregue estructura de tests.
- [ ] Corri tests.
- [ ] No implemente dominio ni KAPSO.

