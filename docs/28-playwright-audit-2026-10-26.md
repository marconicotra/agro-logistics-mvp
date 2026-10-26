# Auditoría funcional y UX/UI con Playwright — 2026-10-26

## Alcance y entorno

Se verificó el repositorio antes de instalar: el frontend usa npm y `frontend/package-lock.json`; ya tenía Vite y sus comandos de desarrollo/build, pero no tenía Playwright ni Vitest configurado en su `package.json`. Se agregó `@playwright/test` sin reemplazar scripts existentes. El build de producción del frontend pasó.

El harness usa bases SQLite nuevas en `frontend/test-results/`, API local `127.0.0.1:8004` y Vite `127.0.0.1:5176`. El worker entrega avisos mediante proveedor mock; WhatsApp entra por webhook local firmado, y la extracción de carga usa un adaptador determinista de QA. Se simularon datos sintéticos. No se usaron los servicios locales ya existentes en `8002/8003/5175`, PostgreSQL, el `.env`, Kapso, OpenAI, Supabase, Google Maps ni email. No se hicieron migraciones. Las bases, capturas, trazas y videos están en `frontend/test-results/`, ignorado por Git. Cada recorrido WhatsApp inicia y cierra su propio escenario; se preservan sus registros en la base de esa ejecución.

La primera corrida completa encontró problemas del harness, del layout y de la cobertura. Después de corregirlos, la suite completa pasó **8/8 casos** (4 en escritorio y 4 en mobile). Una corrida dirigida adicional volvió a pasar el inventario en ambos viewports después de ajustar la tabla. Se verificaron el despacho al transportista, su respuesta de interés, la aceptación explícita del productor y el viaje `PLANNED`. Los escenarios WhatsApp se cerraron y conservaron sus registros etiquetados.

La suite incluye Chromium de escritorio (1440 px) y Chromium con viewport/emulación de iPhone 13. Los screenshots son `fullPage`; el harness reemplaza los teléfonos sintéticos por `[número de prueba]` al capturar. Los videos y trazas se conservan al fallar. El informe HTML de Playwright queda en `frontend/playwright-report/`.

## Documentación leída y faltantes

Se leyeron `AGENTS.md`, `docs/plan-y-bitacora.md`, `docs/04-mvp-scope.md`, `docs/22-data-standardization.md`, `docs/26-auditoria-workflows-y-pantallas.md`, `docs/27-guia-playwright.md`, `docs/20-testing-strategy.md`, `docs/05-operating-model.md`, `docs/07-domain-model.md`, `docs/08-state-machine.md`, `docs/09-event-log-design.md`, `docs/12-whatsapp-agent-architecture.md`, `docs/14-technical-architecture.md`, `docs/21-security-privacy.md`, `docs/23-kapso-integration-strategy.md`, `docs/25-recorridos-y-seguimiento.md`, `DATA_CATALOG.md`, `LINEAGE.md`, `METRICS_DICTIONARY.md`, `README.md`, `backend/README.md` y `frontend/README.md`.

Se comprobó que no existen `docs/product/*`, `docs/evals/*`, `docs/runbooks/development.md` ni `docs/architecture/agent-boundaries.md`. Se usaron como equivalentes la auditoría y guía `docs/26`–`docs/27`, estrategia `docs/20`, bitácora, README raíz y README de backend/frontend, además de los documentos de alcance, dominio, arquitectura, seguridad, integración y datos enumerados arriba. No se crearon árboles paralelos de producto.

## Cobertura ejecutada

| Recorrido o pantalla | Escritorio | Mobile | Resultado observado |
| --- | --- | --- | --- |
| Inicio, conversaciones, avisos, cargas, viajes, recorridos, productores, transportistas, números autorizados y listas | Visitadas y capturadas | Visitadas y capturadas | Rutas, encabezados, errores de consola/solicitudes y ancho del documento revisados. `/carriers` ahora muestra columnas operativas en escritorio y fichas resumidas en mobile. |
| Estados públicos de productor y transportista | Visitados y capturados | Visitados y capturados | Encabezados y render verificados. No se autenticaron datos personales. |
| Alta de transportista en backoffice | Creación y búsqueda completadas | Creación y búsqueda completadas | El perfil queda pendiente y aparece en la búsqueda. |
| Recorrido desde backoffice | Guardado como borrador | Guardado como borrador | Se guardan ruta, paradas, fechas, capacidad y equipo. No se crea viaje ni se compromete capacidad. |
| WhatsApp: declarar recorrido, crear y confirmar carga | Completado | Completado | La carga queda `PUBLISHED`; se selecciona y notifica al transportista compatible del mismo escenario. |
| Interés, aceptación explícita y viaje planificado | Completado | Completado | El transportista responde “1”; el productor revisa interesados y confirma. La asignación se confirma y el viaje queda `PLANNED`. |
| Seguimiento de viaje con chofer/GPS | Pantalla visitada | Pantalla visitada | Se abrió el viaje planificado sin chofer. No se probaron controles GPS ni posiciones reales. |
| Alta WhatsApp, documentos pendientes y revisión humana | Pendiente | Pendiente | El alta desde backoffice no sustituye el recorrido conversacional ni la carga de documentos; no se simuló una aprobación automática. |
| Rechazo, corrección de datos, faltantes, duplicados, validaciones y permisos negativos | Pendiente | Pendiente | La suite inicial no cubre estos casos. |

El test de inventario recorre todas las rutas aunque detecte una anomalía para conservar las capturas. Verifica `pageerror`, solicitudes fallidas y desborde del documento; también envía Tab una vez, pero eso no alcanza para certificar foco visible/teclado de cada formulario. Los estados vacíos que aparecen con la base sintética se fotografiaron en las rutas visitadas; no se forzaron estados de error de cada endpoint.

## Hallazgos comprobados y cambios realizados

### Harness — Fechas sin zona horaria en SQLite alteraban la comparación

- **Ruta:** recorrido WhatsApp con base aislada SQLite.
- **Pasos:** declarar una disponibilidad y una carga para la misma fecha y probar el matching.
- **Esperado:** comparar ambos rangos como instantes equivalentes.
- **Observado:** SQLite descartaba la zona horaria y el adaptador leía los rangos con convenciones distintas. Se normalizó a UTC al guardar y leer esos campos en SQLite. PostgreSQL conserva su tipo con zona horaria.
- **Corrección/verificación:** `UTCDateTime` para ventanas de disponibilidad, carga y oferta; el flujo E2E volvió a pasar.

### Test — La oferta se registra después del interés del transportista

- **Ruta:** WhatsApp simulado y `/shipments/:id`.
- **Esperado según el MVP:** la carga se despacha al transportista compatible; una oferta de interés queda registrada cuando este responde; el productor decide si acepta.
- **Problema observado:** la aserción inicial esperaba una oferta antes de la respuesta del transportista. Eso confundía el despacho con la aceptación de interés.
- **Corrección/verificación:** ahora se verifica decisión de despacho y notificación antes de la respuesta, oferta `INTERESTED`/`RECEIVED` después de “1”, y viaje `PLANNED` después de la confirmación explícita del productor. El flujo pasó en desktop y mobile.

### UX/UI — Acciones mobile y tabla de transportistas

- **Rutas:** `/carriers/new`, `/route-availabilities` y `/carriers`.
- **Problema observado:** dos formularios no completaban el clic de guardado en mobile; la tabla de 13 columnas desbordaba o apretaba datos.
- **Corrección/verificación:** se acotó el ancho mínimo de contenido, los formularios guardan en ambos viewports, la tabla desktop prioriza nombre, teléfono, empresa, validación, alta y perfil; mobile presenta esos datos como fichas legibles. El inventario E2E pasó en ambos viewports y se inspeccionaron las capturas nuevas.

### Texto — QA y códigos visibles

- Los campos “Escenario QA” solo aparecen cuando el harness habilita `VITE_SHOW_QA_FIELDS`; no aparecen en el uso normal del backoffice.
- En la ficha se cambiaron encabezados técnicos y opciones de estado a español cotidiano; los datos faltantes del alta se muestran con etiquetas entendibles.

## Sugerencias UX/UI (sin fallo funcional comprobado)

- **Ficha `/carriers/:id`:** la captura `frontend/test-results/screenshots/desktop-chromium-carrier-created.png` sigue mostrando juntos los formularios para unidad, conductor y documentos. Propuesta: abrir cada formulario solo cuando se elige agregar o editar ese dato.
- **Navegación mobile:** el menú es una franja horizontal desplazable. La página no excede el ancho, pero no todas las opciones quedan a la vista al entrar; mantener visible la sección actual y mejorar el indicio de desplazamiento ayudaría a quien usa el teléfono.

## Diferencias de alcance: implementado, parcial y pendiente

- **Implementado y ejercitado:** pantallas de backoffice listadas; alta/búsqueda manual de transportista; disponibilidad borrador; despacho por recorrido en el escenario QA; interés del transportista; aceptación del productor; viaje planificado; aislamiento por base.
- **Parcial:** inventario de teclado (se verificó Tab, no foco de cada campo); estados vacíos (capturados donde aparecen, sin matriz exhaustiva de errores/cargas); alta conversacional/documental del transportista; seguimiento con chofer/GPS.
- **Pendiente:** rechazos, correcciones, duplicados, ambigüedades, permisos negativos, chofer y ubicación GPS; autenticación del backoffice para entorno compartido. No se infirió aprobación documental ni reserva automática por declarar un recorrido.

## Comandos y artefactos

```bash
cd frontend
npm ci
npm run test:e2e
npx playwright show-report playwright-report
```

Filtrar por viewport: `npm run test:e2e -- --project=desktop-chromium` o `npm run test:e2e -- --project=mobile-chromium`. Capturas: `frontend/test-results/screenshots/`. Contextos, trazas y videos por test: `frontend/test-results/results/`. Bases SQLite sintéticas: `frontend/test-results/agro-playwright-*.sqlite3`. No compartir bases/trazas sin revisar los datos sintéticos que contienen.

## Limitaciones

- No se usaron servicios externos, Kapso Sandbox, WhatsApp real, email real, IA real, mapas ni base compartida. No se validó la recepción real de proveedores.
- La mobile Chromium emula viewport/dispositivo; no sustituye pruebas táctiles en teléfono físico ni otros navegadores.
- Una disponibilidad y un transportista seed son suficientes para el flujo feliz esperado, pero no cubren colisiones, múltiples transportistas, equivalencias de topónimos ni cobertura de provincias.
- La suite actual es una primera base de regresión. Varias rutas y estados descritos en `docs/26` aún no tienen una aserción E2E completa.
- `npm install` informó 9 vulnerabilidades en dependencias (1 baja, 2 moderadas y 6 altas). No se ejecutó `npm audit fix` ni se cambiaron versiones por ese motivo.
- El backoffice local usa headers de rol de desarrollo y no es apto para publicar como consola humana compartida. La protección y autenticación requeridas siguen descritas en `docs/21-security-privacy.md`.
