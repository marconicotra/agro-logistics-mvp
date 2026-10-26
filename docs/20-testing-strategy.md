# Testing Strategy MVP

Este documento define la estrategia de testing para AGRO Logistics MVP. No incluye codigo ni tooling obligatorio.

Objetivo: probar reglas de dominio, integraciones conversacionales, idempotencia, event log, agentes y casos reales de operacion.

## Principios

- Probar dominio sin KAPSO.
- Probar KAPSO como adapter.
- Toda transicion critica debe tener tests.
- Todo endpoint mutante debe probar EventLog.
- Todo webhook debe probar idempotencia.
- AI tests validan comportamiento esperado, no perfeccion absoluta.

## Unit Tests

| Area | Que probar | Casos clave |
| --- | --- | --- |
| Domain services | Reglas de `shipment_requests`, `trip_offers`, `assignments`, `trips`. | Publicacion self-service con datos minimos; no trip sin doble aceptacion. |
| State transitions | Validacion contra maquinas de estado. | Validar `DRAFT -> PUBLISHED`, `PUBLISHED -> MATCHING`, `MATCHING -> ASSIGNED`. |
| Pricing range | Rango estimado y confianza. | Datos incompletos devuelven baja confianza. |
| Matching ranking | Ordenamiento simple por zona, capacidad, disponibilidad. | Ranking explica faltantes y no asigna. |
| Missing fields | Deteccion de criticos. | Origen/destino/fecha/tipo/cantidad; el telefono entrante identifica el contacto. |
| Risk flags | Riesgos operativos. | Ambiguedad, cancelacion, oferta tarde, cambio horario. |

## Integration Tests

| Area | Que probar | Resultado esperado |
| --- | --- | --- |
| Webhook inbound | HMAC, payload, batch, enqueue. | Evento aceptado una vez. |
| Idempotencia | Mismo webhook repetido. | No duplica `messages`, `trip_offers` ni `event_logs`. |
| Event log | Mutaciones de dominio. | Cada cambio genera evento correcto. |
| DB repositories | Persistencia y consultas. | Estados y relaciones consistentes. |
| Queue/jobs | Procesamiento async. | Retry seguro y DLQ ante error permanente. |
| Provider adapters | KAPSO outbound/inbound normalizado. | IDs externos mapeados, no usados como dominio. |

## Agent / Prompt Tests

| Skill/Agente | Que probar | Criterio |
| --- | --- | --- |
| Extraction accuracy | Extraer origen, destino, fecha, cantidad, tipo. | No inventa datos faltantes. |
| Missing fields | Detectar faltantes criticos. | Preguntas simples y correctas. |
| Summarization | Resumen para operador/carrier. | No oculta incertidumbre. |
| Carrier alert generation | Mensaje de oportunidad. | No promete asignacion ni precio final. |
| Ambiguous messages | "si", "puede ser", "lo veo". | Marca baja confianza o handoff. |
| Risk detection | Cancelacion, cambio de horario, ubicacion ambigua. | `requiresHumanReview = true`. |
| Conversation backoffice | Entrante humano, respuesta del agente, operador y estados outbound. | Orden cronologico y emisor/direccion correctos; acceso restringido. |

## E2E Tests

| Escenario | Flujo esperado |
| --- | --- |
| Productor crea carga | Webhook -> Message -> ShipmentRequest PUBLISHED -> outbound -> EventLog. |
| Transportista se interesa | Broadcast -> Carrier response -> TripOffer INTERESTED -> MATCHING. |
| Productor acepta oferta | Interested offer -> Assignment CONFIRMED -> Trip PLANNED -> ASSIGNED. |
| Viaje se completa | Trip started -> completed -> ShipmentRequest closed. |
| Cancelacion | Mensaje cancelacion -> risk flag -> operador -> estado cancelado -> EventLog. |
| Nadie responde | Published -> no offers -> `NO_CARRIER_RESPONSE` -> fallback manual. |
| Alta de transportista | WhatsApp captura perfil/vehiculos/adjuntos -> pendiente de revision -> operador aprueba/rechaza/pide correccion con evento. |
| Disponibilidad de recorrido | Carrier declara ruta/ventana/capacidad -> consulta por ruta -> sugerencias sin crear `Trip` ni reservar capacidad al buscar. |
| Retorno parcial | Ruta sin carga de regreso -> alternativa directa/cercana -> carrier acepta/rechaza explicitamente; nunca modifica recorrido silenciosamente. |
| Backoffice de mensajes/productores | Hilo ordena mensajes humanos y del agente; ficha productor relaciona cargas/ofertas/viajes/eventos y respeta permisos. |

## Casos Borde Obligatorios

- Mensaje duplicado.
- Webhook fuera de orden.
- Datos incompletos.
- Transportista responde tarde.
- Cambio de horario.
- Cancelacion posterior a assignment.
- AI no entiende mensaje.
- KAPSO caido.
- Queue caida.
- Evento sin `idempotency_key`.
- Ubicacion con multiples interpretaciones.

## Test Data

Usar fixtures realistas:

- Mensajes cortos de WhatsApp.
- Audios transcriptos con ambiguedad.
- Productor con carga incompleta.
- Carrier con respuesta "puede ser".
- Cancelacion sin motivo.
- Oferta con precio pero sin disponibilidad.

## Acceptance Criteria MVP

- 100% de transiciones criticas cubiertas.
- Webhooks duplicados no duplican entidades.
- Todas las mutaciones relevantes generan EventLog.
- E2E principal productor -> carrier -> productor acepta -> trip pasa.
- AI failures degradan a humano, no bloquean dominio.

## Decisiones Tecnicas Tomadas

1. Priorizar tests de dominio antes que UI/admin.
2. Tratar AI como componente probabilistico con golden cases.
3. Probar adapters con contratos, no contra logica de negocio.
4. Incluir DLQ/retry en integration tests.
5. E2E centrado en operacion real, no happy path solamente.

## Riesgos Tecnicos

1. Tests de AI fragiles si esperan texto exacto.
2. E2E dependientes de proveedores externos.
3. Fixtures poco realistas pueden ocultar errores de campo.
4. Idempotencia no probada bajo concurrencia.
5. EventLog testeado superficialmente puede perder valor auditivo.

## Que Implementar Primero

1. Unit tests de state machine y domain services.
2. Integration tests de webhook idempotente + EventLog.
3. E2E minimo de carga publicada, oferta recibida y assignment confirmado.

## Recorridos y seguimiento

Ver `docs/25-recorridos-y-seguimiento.md`. Las pruebas de concurrencia PostgreSQL son opt-in mediante `AGRO_QA_POSTGRES_URL`, validan host loopback y nombre de base descartable. Nunca usar una URL de producción ni credenciales del proyecto para esos tests. El resto de la suite usa mocks, HTTP simulado y bases temporales. Se conservan pruebas históricas de difusión explícita con su feature flag deshabilitado; el comportamiento nuevo dirigido se verifica habilitado.
