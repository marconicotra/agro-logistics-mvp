# Guía E2E con Playwright

Esta guía describe los recorridos reproducibles en el backoffice y en el canal WhatsApp simulado. La estrategia general está en `docs/20-testing-strategy.md`; esta guía agrega rutas, actores, datos de prueba y comprobaciones observables.

## Harness local instalado

Desde `frontend/`:

```bash
npm ci
npm run test:e2e
npx playwright show-report playwright-report
```

En un checkout nuevo, preparar primero el entorno Python según `backend/README.md` (`python -m venv .venv` y `pip install -e "[dev]"` desde la raíz). El runner espera `.venv/bin/python`.

`npm run test:e2e` crea una base SQLite nueva en `frontend/test-results/`, con datos ficticios, y levanta API `127.0.0.1:8004`, worker de avisos mock y Vite `127.0.0.1:5176`. No usa el `.env`, PostgreSQL, los servicios que puedan estar en `8002/8003/5175`, Kapso, OpenAI, Supabase, ni Google Maps. El endpoint de WhatsApp recibe webhooks firmados con una clave local de prueba; el cliente de extracción de cargas devuelve resultados deterministas. El teléfono, el transportista y las cargas son sintéticos. Cada ejecución conserva su base para diagnóstico; no se limpian escenarios automáticamente.

Playwright corre Chromium en escritorio y con viewport/emulación móvil. El informe HTML queda en `frontend/playwright-report/`; capturas, trazas, videos y bases aisladas quedan en `frontend/test-results/`. Ambas carpetas están ignoradas por Git. El informe de auditoría de esta ejecución está en `docs/28-playwright-audit-2026-10-26.md`.

El runner define `VITE_SHOW_QA_FIELDS=true` solo para mostrar el campo de etiquetado de escenario durante E2E. En el uso normal esos campos quedan ocultos.

## Antes de automatizar

1. Leer `AGENTS.md`, `docs/04-mvp-scope.md`, `docs/22-data-standardization.md` y `docs/26-auditoria-workflows-y-pantallas.md`.
2. Levantar frontend y backend local con proveedor WhatsApp mock. Confirmar salud del backend y que el frontend responde.
3. Usar una base de pruebas aislada y datos sintéticos. No usar contactos, CUIT, licencias, mensajes personales ni documentos reales.
4. Para backoffice, usar una sesión de prueba autorizada. Los headers locales de usuario/rol son solo desarrollo; nunca incluir `INTERNAL_API_KEY` ni otros secretos en el navegador.
5. Guardar `test_run_id` para los recorridos WhatsApp y usarlo en las consultas a datos si aplica. No borrar filas de otros escenarios.
6. Si se prueba Kapso real, limitarlo al Sandbox aprobado y al contacto allowlisted. Nunca usar el número conectado de producción.

## Contrato de automatización del navegador

- Navegar por rutas publicadas en `frontend/src/App.tsx`; no depender de orden visual ni clases CSS.
- Preferir `getByRole('heading'|'link'|'button'|'textbox'|'combobox', { name })`, `getByLabel()` y nombres accesibles.
- Cada flujo debe comprobar URL, título, estado visible y persistencia por la UI de detalle/API de prueba. No aceptar solo un toast como prueba de guardado.
- Usar datos únicos por ejecución (ej. sufijo corto de `test_run_id`) en nombres de localidad/carga cuando aplique. Nunca meter secretos en screenshots o trazas.
- Los diálogos `window.confirm` para borrar requieren aceptación explícita del test; no borrar entidades compartidas.
- La UI tiene paginación: recorrer páginas con los controles visibles, no suponer que el registro está en la primera.
- Esperar por estado de red/UI con locators; evitar sleeps fijos. Para mensajes de IA, validar contenido semántico y datos, no texto exacto probabilístico.

## E2E A — Productor crea una carga, transportista se interesa, productor acepta

### WhatsApp (mock de canal)

1. Iniciar escenario QA permitido y tomar su identificador.
2. Como productor, enviar un pedido sintético claro, por ejemplo: «Necesito llevar 30 novillos de Azul, Buenos Aires, a Liniers para el viernes». Ajustar día a una fecha futura del escenario.
3. Responder aclaraciones hasta ver resumen. Confirmar y guardar el identificador de la carga mostrado o recuperado en el backoffice.
4. Comprobar carga publicada, decisión de despacho y aviso outbound mock dirigido a un carrier elegible. El despacho no crea por sí solo una oferta de interés.
5. Cambiar a rol transportista dentro del mismo escenario; responder «Me interesa» al aviso relacionado con esa carga.
6. Verificar oferta `INTERESTED` con respuesta recibida, carga en búsqueda y que no existe todavía asignación/viaje confirmado.
7. Volver a productor; pedir interesados, elegir carga/oferta y confirmar explícitamente.
8. Verificar asignación confirmada, viaje planificado, carga asignada, avisos y eventos para las dos partes.
9. Cerrar escenario. Los datos quedan etiquetados, no se borran.

### Backoffice (navegador)

1. Abrir `/dashboard`; comprobar que los indicadores de seguimiento llevan a las listas correctas.
2. Abrir `/shipments`, buscar la carga por ID/ruta y entrar a `/shipments/:shipmentId`.
3. Comprobar datos, respuestas, transportista elegido, viaje e historial. Abrir `/trips`; seguir el viaje desde su acción de seguimiento.
4. Abrir `/conversations`, localizar los hilos por rol/escenario y comprobar mensajes en orden con dirección, fecha y emisor.
5. Abrir `/notifications` y comprobar el estado de los avisos sin validar ni capturar contenido o teléfono sensible.

## E2E B — datos incompletos y corrección

1. Enviar una solicitud sin cantidad/unidad, ruta o fecha suficiente; para granos probar cantidad sin unidad.
2. Comprobar que el bot pregunta el faltante y no publica antes de la confirmación completa.
3. Responder el dato faltante; revisar que la vista previa lo muestre correctamente y confirmar.
4. Enviar ubicación ambigua/homónima; confirmar que pide precisión o deriva a soporte, sin elegir localidad arbitrariamente.
5. Revisar evento, marca de revisión y conversación en `/conversations` y detalle de carga.

## E2E C — rechazo, duplicado y ambigüedad del transportista

1. Responder «No puedo» y verificar oferta declinada sin asignación.
2. Repetir el mismo evento idempotente y comprobar que no se duplica.
3. En otra carga, responder texto ambiguo («puede ser») y comprobar handoff/evento de revisión.

## E2E D — recorrido disponible

1. Como transportista, elegir informar recorrido; completar origen, destino, fecha futura, paradas, capacidad con unidad, carga y equipo.
2. Revisar resumen/confirmación y guardar. Comprobar disponibilidad separada de viajes.
3. En backoffice, abrir `/route-availabilities`, filtrar por el transportista/escenario y comprobar ruta, ventana, capacidad y estado. Registrar una disponibilidad queda como borrador y no crea viaje ni compromete capacidad.
4. Buscar una carga compatible. Comprobar que la consulta no crea oferta, asignación ni viaje ni reserva capacidad por sí sola.
5. No probar reglas de desvíos múltiples, vencimiento o varias cargas por recorrido mientras sigan pendientes en la bitácora.

## E2E E — alta y homologación

1. Como transportista, iniciar alta y completar datos ficticios; adjuntar un archivo de prueba sin datos personales.
2. Revisar resumen, editar un dato y confirmar.
3. Comprobar estado pendiente de revisión, datos/unidades/choferes/documento vinculados y eventos.
4. En backoffice abrir `/carriers`, ficha y pestañas de documentos, unidades, choferes e historial.
5. Verificar que tener archivo recibido no aprueba automáticamente. No asumir requisitos documentales no definidos.

## E2E F — seguimiento

1. Preparar viaje planificado con chofer y vehículo de QA habilitados según el modelo actual.
2. Abrir `/trips/:tripId/tracking`; confirmar WhatsApp/contacto del chofer y seguir transición permitida para iniciar controles.
3. Solicitar ubicación y responder desde el número/rol de prueba correspondiente.
4. Comprobar hora, punto informado y control, y que el estado no se da por completado solo por coordenadas.
5. Si mapas no tiene credenciales, verificar mensaje de indisponibilidad sin fallar el resto del seguimiento.

## Cobertura de pantallas

Recorrer las pantallas listadas en `docs/26-auditoria-workflows-y-pantallas.md`: Inicio, Conversaciones y detalle, Avisos, Cargas y detalle, Viajes y seguimiento, Recorridos, Productores y ficha, Transportistas/alta/ficha, estados públicos de productor/transportista, Números autorizados y Listas del sistema. Verificar carga, vacío, error, permisos y navegación donde corresponda.

## Fuera de automatización destructiva o real

- No enviar a chats fuera del Sandbox expresamente autorizado.
- No cambiar el webhook del número de producción, credenciales, Supabase ni permisos compartidos.
- No borrar en lote, limpiar base compartida ni cerrar escenarios ajenos.
- No probar pagos, GPS continuo, aprobación legal/documental automática ni optimización de ruta: no pertenecen al MVP.

## Bloqueos que hay que resolver antes de endurecer E2E

- Confirmar un esquema de autenticación de navegador seguro en entorno compartido.
- Acordar selectores accesibles estables donde falten nombres/labels; no agregar IDs solo para tests si el rol accesible ya sirve.
- Definir datos mínimos, documentos obligatorios/vigencias/retención y reglas de aprobación del transportista.
- Cerrar vencimiento de recorridos y desvío/paradas/capacidad para casos parciales.
- Definir proveedor/credenciales de mapas para pruebas que requieran ruta real.
