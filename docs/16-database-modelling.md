# Modelo Logico Relacional

Este documento define el modelo logico relacional de AGRO Logistics MVP. No incluye SQL, migraciones ni detalles de motor.

Los nombres de tablas usan convencion relacional. El mapeo con dominio canonico es:

- `shipment_requests` = `LivestockLoad`
- `trip_offers` = `Offer`
- `assignments` = `Assignment`
- `trips` = `Trip`
- `messages` = `Message`
- `media_assets` = `MediaAsset`
- `event_logs` = `EventLog`

## Convenciones

- Tipos sugeridos: orientativos, no fisicos.
- `nullable`: indica si el dato puede faltar en MVP.
- Timestamps comunes: `created_at`, `updated_at`, `deleted_at`.
- Todas las tablas operativas deben soportar trazabilidad hacia `event_logs` cuando aplique.

## Estado De Implementacion

Existe una migracion inicial Alembic que materializa estas tablas como modelo SQLAlchemy. La implementacion usa IDs string con prefijos de dominio (`sr_`, `trip_`, `evt_`, etc.) para conservar compatibilidad con los modelos actuales del dominio.

La migracion inicial vive en:

- `migrations/versions/0001_initial.py`

Regla operativa: no usar tablas SQL directamente para cambiar estados. Las mutaciones criticas deben pasar por application/domain services para preservar state machine y `EventLog`.

## `users`

Descripcion: identidad base de actores humanos internos o externos.

| Campo | Tipo sugerido | Nullable |
| --- | --- | --- |
| `id` | uuid | no |
| `display_name` | text | no |
| `phone_number` | text | si |
| `role` | enum | no |
| `status` | enum | no |
| `notes` | text | si |
| `created_at` | timestamp | no |
| `updated_at` | timestamp | no |
| `deleted_at` | timestamp | si |

Relaciones:

- 1 a 0/1 con `producers`.
- 1 a 0/1 con `carriers`.
- 1 a muchos con `messages` como sender.
- 1 a muchos con `event_logs` como actor.

Indices sugeridos:

- `phone_number`
- `role`
- `status`

Reglas de negocio:

- Un usuario no define por si solo si es productor o carrier validado.
- Cambios de rol o estado relevantes deben generar evento.

Notas analytics:

- Base para usuarios activos, handoff humano y actividad por rol.

## `producers`

Descripcion: productor o comisionista que origina necesidades de transporte.

| Campo | Tipo sugerido | Nullable |
| --- | --- | --- |
| `id` | uuid | no |
| `user_id` | uuid | si |
| `name` | text | no |
| `contact_phone` | text | si |
| `usual_location_id` | uuid | si |
| `trust_notes` | text | si |
| `is_validated` | boolean | no |
| `validated_at` | timestamp | si |
| `created_at` | timestamp | no |
| `updated_at` | timestamp | no |
| `deleted_at` | timestamp | si |

Relaciones:

- Muchos a 1 con `users`.
- 1 a muchos con `shipment_requests`.
- Muchos a 1 opcional con `locations`.

Indices sugeridos:

- `user_id`
- `contact_phone`
- `is_validated`

Reglas de negocio:

- Puede iniciar cargas incompletas.
- Datos privados no deben exponerse innecesariamente a carriers.

Notas analytics:

- Productores activos, recurrentes y cargas por productor.

## `carriers`

Descripcion: transportista que recibe oportunidades y responde disponibilidad, consulta o precio.

| Campo | Tipo sugerido | Nullable |
| --- | --- | --- |
| `id` | uuid | no |
| `user_id` | uuid | si |
| `name` | text | no |
| `contact_phone` | text | si |
| `service_zone` | text | si |
| `trust_notes` | text | si |
| `availability_notes` | text | si |
| `is_validated` | boolean | no |
| `created_at` | timestamp | no |
| `updated_at` | timestamp | no |
| `deleted_at` | timestamp | si |

Relaciones:

- Muchos a 1 con `users`.
- 1 a muchos con `vehicles`.
- 1 a muchos con `trip_offers`.
- 1 a muchos con `assignments`.

Indices sugeridos:

- `user_id`
- `contact_phone`
- `service_zone`
- `is_validated`

Reglas de negocio:

- Responder interesado no implica asignacion.
- Seleccion final requiere operador.

Notas analytics:

- Supply activo, tasa de respuesta, cancelaciones por carrier.

## `vehicles`

Descripcion: unidad de transporte asociada a carrier.

| Campo | Tipo sugerido | Nullable |
| --- | --- | --- |
| `id` | uuid | no |
| `carrier_id` | uuid | no |
| `vehicle_type` | text | si |
| `capacity_estimate` | numeric | si |
| `plate` | text | si |
| `status` | enum | no |
| `validation_flags` | json | si |
| `created_at` | timestamp | no |
| `updated_at` | timestamp | no |
| `deleted_at` | timestamp | si |

Relaciones:

- Muchos a 1 con `carriers`.
- 1 a muchos opcional con `trip_offers`.
- 1 a muchos opcional con `assignments` y `trips`.

Indices sugeridos:

- `carrier_id`
- `status`
- `plate`

Reglas de negocio:

- Capacidad puede ser estimada.
- Cambios de vehiculo confirmado requieren evento.

Notas analytics:

- Cobertura potencial y disponibilidad por tipo de unidad.

## `locations`

Descripcion: ubicacion original, normalizada o validada para origen/destino.

| Campo | Tipo sugerido | Nullable |
| --- | --- | --- |
| `id` | uuid | no |
| `original_text` | text | no |
| `normalized_name` | text | si |
| `province` | text | si |
| `locality` | text | si |
| `rural_reference` | text | si |
| `confidence` | enum | no |
| `is_validated` | boolean | no |
| `created_at` | timestamp | no |
| `updated_at` | timestamp | no |

Relaciones:

- Referenciada por `shipment_requests` como origen/destino.
- Puede ser referencia usual de `producers`.

Indices sugeridos:

- `normalized_name`
- `province`
- `locality`
- `confidence`

Reglas de negocio:

- Nunca reemplazar texto original.
- Ubicacion ambigua requiere soporte humano.

Notas analytics:

- Cargas por zona, zonas cubiertas y calidad de ubicacion.

## `shipment_requests`

Descripcion: necesidad de transporte agropecuario. Puede ser hacienda o granos; es carga/necesidad, no ejecucion.

| Campo | Tipo sugerido | Nullable |
| --- | --- | --- |
| `id` | uuid | no |
| `producer_id` | uuid | si |
| `producer_phone_number` | text | si |
| `origin_location_id` | uuid | si |
| `destination_location_id` | uuid | si |
| `cargo_category` | text | si |
| `cargo_type` | text | si |
| `quantity_unit` | text | si |
| `date_window_start` | timestamp | si |
| `date_window_end` | timestamp | si |
| `livestock_type` | text | si |
| `quantity_estimate` | numeric | si |
| `status` | enum | no |
| `field_confidence` | json | si |
| `missing_critical_fields` | json | si |
| `requires_human_review` | boolean | no |
| `has_ambiguous_location` | boolean | no |
| `has_estimated_values` | boolean | no |
| `source_message_id` | uuid | si |
| `validated_by_user_id` | uuid | si |
| `validated_at` | timestamp | si |
| `created_at` | timestamp | no |
| `updated_at` | timestamp | no |
| `deleted_at` | timestamp | si |

Relaciones:

- Muchos a 1 con `producers`.
- Muchos a 1 con `locations` para origen y destino.
- 1 a muchos con `trip_offers`.
- 1 a 0/1 assignment confirmado activo.
- 1 a 0/1 `trips` en MVP.
- Muchos a 1 opcional con `messages` como fuente.

Indices sugeridos:

- `status`
- `producer_id`
- `producer_phone_number`
- `origin_location_id`
- `destination_location_id`
- `date_window_start`
- `requires_human_review`

Reglas de negocio:

- Puede existir incompleta.
- Puede autopublicarse si el productor confirma y hay datos minimos de tipo y cantidad.
- No se publica si faltan datos minimos para entender la carga.
- Cambios de origen, destino, fecha o cantidad requieren evento.

Notas analytics:

- Funnel de demanda, cargas por zona, data completeness, tiempo hasta publicacion y tiempo hasta primer interesado.

## `trip_offers`

Descripcion: interes, disponibilidad, consulta o precio estimado de carrier. Es `Offer`, no assignment.

| Campo | Tipo sugerido | Nullable |
| --- | --- | --- |
| `id` | uuid | no |
| `shipment_request_id` | uuid | no |
| `carrier_id` | uuid | no |
| `vehicle_id` | uuid | si |
| `source_message_id` | uuid | si |
| `response_type` | enum | no |
| `status` | enum | no |
| `price_estimate` | numeric | si |
| `availability_window_start` | timestamp | si |
| `availability_window_end` | timestamp | si |
| `confidence` | enum | no |
| `requires_human_review` | boolean | no |
| `created_at` | timestamp | no |
| `updated_at` | timestamp | no |
| `deleted_at` | timestamp | si |

Relaciones:

- Muchos a 1 con `shipment_requests`.
- Muchos a 1 con `carriers`.
- Muchos a 1 opcional con `vehicles`.
- Muchos a 1 opcional con `messages`.
- 1 a 0/1 con `assignments`.

Indices sugeridos:

- `shipment_request_id`
- `carrier_id`
- `status`
- `response_type`
- `created_at`

Reglas de negocio:

- No confirma viaje.
- Precio informado no es precio final.
- Respuesta ambigua requiere revision.

Notas analytics:

- Ofertas por carga, tiempo hasta primer interesado, tasa de respuesta.

## `assignments`

Descripcion: match entre una necesidad y un carrier. En el flujo feliz queda confirmado por doble aceptacion: carrier interesado y productor acepta oferta.

| Campo | Tipo sugerido | Nullable |
| --- | --- | --- |
| `id` | uuid | no |
| `shipment_request_id` | uuid | no |
| `trip_offer_id` | uuid | si |
| `carrier_id` | uuid | no |
| `vehicle_id` | uuid | si |
| `status` | enum | no |
| `selected_by_user_id` | uuid | no |
| `confirmed_by_user_id` | uuid | si |
| `confirmed_at` | timestamp | si |
| `confirmation_notes` | text | si |
| `requires_human_review` | boolean | no |
| `created_at` | timestamp | no |
| `updated_at` | timestamp | no |
| `deleted_at` | timestamp | si |

Relaciones:

- Muchos a 1 con `shipment_requests`.
- Muchos a 1 opcional con `trip_offers`.
- Muchos a 1 con `carriers`.
- Muchos a 1 opcional con `vehicles`.
- 1 a 0/1 con `trips`.

Indices sugeridos:

- `shipment_request_id`
- `carrier_id`
- `status`
- `confirmed_at`

Reglas de negocio:

- El flujo feliz confirma por doble aceptacion.
- Soporte puede intervenir en excepciones.
- No debe haber mas de un assignment confirmado activo por carga.
- Cancelaciones y reemplazos requieren evento.

Notas analytics:

- Tasa de match, tiempo hasta match, fallback manual.

## `trips`

Descripcion: ejecucion logistica derivada de un assignment confirmado.

| Campo | Tipo sugerido | Nullable |
| --- | --- | --- |
| `id` | uuid | no |
| `shipment_request_id` | uuid | no |
| `assignment_id` | uuid | no |
| `carrier_id` | uuid | no |
| `vehicle_id` | uuid | si |
| `status` | enum | no |
| `planned_start_at` | timestamp | si |
| `planned_end_at` | timestamp | si |
| `started_at` | timestamp | si |
| `completed_at` | timestamp | si |
| `cancelled_at` | timestamp | si |
| `incident_notes` | text | si |
| `closure_notes` | text | si |
| `created_at` | timestamp | no |
| `updated_at` | timestamp | no |
| `deleted_at` | timestamp | si |

Relaciones:

- Muchos a 1 con `shipment_requests`.
- 1 a 1 con `assignments` en MVP.
- Muchos a 1 con `carriers`.
- Muchos a 1 opcional con `vehicles`.

Indices sugeridos:

- `status`
- `assignment_id`
- `carrier_id`
- `planned_start_at`
- `completed_at`

Reglas de negocio:

- No existe trip activo sin assignment confirmado.
- No requiere GPS en tiempo real.
- Cierre y cancelacion requieren operador.

Notas analytics:

- Viajes confirmados, completados, cancelados, comisionables.

## `conversation_sessions`

Descripcion: conversacion operativa por canal.

| Campo | Tipo sugerido | Nullable |
| --- | --- | --- |
| `id` | uuid | no |
| `channel` | enum | no |
| `external_conversation_id` | text | si |
| `workflow_execution_id` | text | si |
| `participant_phone` | text | si |
| `participant_user_id` | uuid | si |
| `status` | enum | no |
| `started_at` | timestamp | no |
| `last_message_at` | timestamp | si |
| `created_at` | timestamp | no |
| `updated_at` | timestamp | no |

Relaciones:

- 1 a muchos con `messages`.
- Puede vincularse a entidades via `event_logs` o referencias en mensajes.

Indices sugeridos:

- `channel`
- `external_conversation_id`
- `participant_phone`
- `last_message_at`

Reglas de negocio:

- IDs de KAPSO son externos, no dominio.
- Conversacion no cambia estado de negocio por si sola.

Notas analytics:

- Volumen conversacional, handoff y tiempos de respuesta.

## `messages`

Descripcion: mensaje individual entrante o saliente.

| Campo | Tipo sugerido | Nullable |
| --- | --- | --- |
| `id` | uuid | no |
| `conversation_session_id` | uuid | no |
| `provider` | text | no |
| `provider_message_id` | text | si |
| `idempotency_key` | text | si |
| `direction` | enum | no |
| `sender_type` | enum | no |
| `sender_id` | uuid | si |
| `media_asset_id` | uuid | si |
| `raw_content` | text | si |
| `normalized_content` | text | si |
| `message_type` | enum | no |
| `received_at` | timestamp | si |
| `sent_at` | timestamp | si |
| `correlation_id` | text | si |
| `created_at` | timestamp | no |

Relaciones:

- Muchos a 1 con `conversation_sessions`.
- 0/1 a 1 con `media_assets` para mensajes con archivo.
- Puede ser fuente de `shipment_requests` y `trip_offers`.
- 1 a muchos con `event_logs`.

Indices sugeridos:

- `conversation_session_id`
- `provider_message_id`
- `idempotency_key`
- `direction`
- `created_at`

Reglas de negocio:

- Preservar contenido original usado para extraccion.
- Duplicados no crean nuevas entidades.

Notas analytics:

- Mensajes ambiguos, tiempos de respuesta, errores de extraccion AI.

## `media_assets`

Descripcion: referencia tecnica a media entrante desde un proveedor de canal. Permite
trazar archivos recibidos por WhatsApp/KAPSO sin mezclar reglas del canal con el
documento operativo revisado por soporte.

| Campo | Tipo sugerido | Nullable |
| --- | --- | --- |
| `id` | uuid | no |
| `message_id` | uuid | si |
| `provider` | text | no |
| `provider_media_id` | text | si |
| `media_type` | enum | no |
| `mime_type` | text | si |
| `file_name` | text | si |
| `external_url` | text | si |
| `storage_uri` | text | si |
| `sha256` | text | si |
| `status` | enum | no |
| `error_message` | text | si |
| `created_at` | timestamp | no |
| `updated_at` | timestamp | no |

Relaciones:

- Muchos a 0/1 con `messages`.
- Puede originar un registro en `documents` si corresponde a documentacion operativa.

Indices sugeridos:

- `message_id`
- `provider_media_id`

Reglas de negocio:

- No confirma ni rechaza homologaciones por si mismo.
- Si no se puede asociar a carrier, debe quedar trazado para intervencion humana.

## `event_logs`

Descripcion: auditoria append-only conceptual de eventos operativos.

| Campo | Tipo sugerido | Nullable |
| --- | --- | --- |
| `id` | uuid | no |
| `event_type` | text | no |
| `occurred_at` | timestamp | no |
| `actor_type` | enum | no |
| `actor_id` | uuid | si |
| `entity_type` | text | no |
| `entity_id` | uuid | no |
| `related_entity_ids` | json | si |
| `previous_state` | text | si |
| `new_state` | text | si |
| `summary` | text | no |
| `payload` | json | si |
| `source` | text | no |
| `correlation_id` | text | si |
| `idempotency_key` | text | si |
| `created_at` | timestamp | no |

Relaciones:

- Referencia cualquier entidad por `entity_type` + `entity_id`.
- Relaciona contexto por `related_entity_ids`.

Indices sugeridos:

- `event_type`
- `entity_type`, `entity_id`
- `occurred_at`
- `correlation_id`
- `idempotency_key`

Reglas de negocio:

- No sobrescribir eventos historicos.
- Cambios de estado deben guardar estado anterior y nuevo.
- Confirmaciones criticas deben tener actor operador.

Notas analytics:

- Fuente principal para funnel, tiempos, auditoria y reconstruccion.

## `documents`

Descripcion: referencias documentales u operativas asociadas a entidades. No implica gestion documental avanzada.

| Campo | Tipo sugerido | Nullable |
| --- | --- | --- |
| `id` | uuid | no |
| `entity_type` | text | no |
| `entity_id` | uuid | no |
| `document_type` | text | no |
| `external_uri` | text | si |
| `provider` | text | si |
| `provider_media_id` | text | si |
| `mime_type` | text | si |
| `file_name` | text | si |
| `storage_uri` | text | si |
| `uploaded_by_phone` | text | si |
| `status` | enum | no |
| `notes` | text | si |
| `created_at` | timestamp | no |
| `updated_at` | timestamp | no |

Relaciones:

- Referencia `shipment_requests`, `trips`, `carriers` u otras entidades por tipo/id.

Indices sugeridos:

- `entity_type`, `entity_id`
- `document_type`
- `status`

Reglas de negocio:

- No bloquear MVP por documentacion salvo decision operativa.
- Datos sensibles deben tener acceso controlado.

Notas analytics:

- Completeness documental futura; no KPI central inicial.

## `payment_terms`

Descripcion: condiciones economicas pactadas o estimadas. No representa pagos dentro de la app.

| Campo | Tipo sugerido | Nullable |
| --- | --- | --- |
| `id` | uuid | no |
| `shipment_request_id` | uuid | si |
| `assignment_id` | uuid | si |
| `trip_id` | uuid | si |
| `amount_estimate` | numeric | si |
| `agreed_amount` | numeric | si |
| `commission_estimate` | numeric | si |
| `currency` | text | no |
| `confidence` | enum | no |
| `source` | enum | no |
| `notes` | text | si |
| `created_at` | timestamp | no |
| `updated_at` | timestamp | no |

Relaciones:

- Puede vincularse a carga, assignment o trip.

Indices sugeridos:

- `shipment_request_id`
- `assignment_id`
- `trip_id`
- `confidence`

Reglas de negocio:

- No implica pago in-app.
- Precio final requiere operador.

Notas analytics:

- Revenue estimado, comision estimada, viajes comisionables.

## `risk_flags`

Descripcion: riesgos operativos, de datos o estado asociados a entidades.

| Campo | Tipo sugerido | Nullable |
| --- | --- | --- |
| `id` | uuid | no |
| `entity_type` | text | no |
| `entity_id` | uuid | no |
| `risk_type` | text | no |
| `severity` | enum | no |
| `status` | enum | no |
| `reason` | text | no |
| `created_by` | enum | no |
| `resolved_by_user_id` | uuid | si |
| `resolved_at` | timestamp | si |
| `created_at` | timestamp | no |
| `updated_at` | timestamp | no |

Relaciones:

- Referencia cualquier entidad operacional.
- Puede derivar de `messages` o `event_logs`.

Indices sugeridos:

- `entity_type`, `entity_id`
- `risk_type`
- `severity`
- `status`

Reglas de negocio:

- Riesgo no resuelve operacion.
- Riesgos altos requieren operador.

Notas analytics:

- Viajes en riesgo, cargas con baja confianza, fallback humano.

## Extensiones Conceptuales Pendientes De Alcance

Las siguientes entidades refinan el dominio propuesto, pero no son tablas implementadas ni instrucciones de migracion. Definir constraints, ownership, indices y estrategia transaccional antes de crear esquema.

### `carrier_route_availabilities`

Una fila/version representa la declaracion de un transportista para una ruta/ventana y capacidad libre. Conceptualmente relaciona carrier, localidades de origen/destino, periodo, cantidad/unidad, equipo/categorias compatibles, paradas/corredor, desvio aceptable, estado y vencimiento. Conservar valores originales, canonicalizacion y actor fuente.

### `carrier_search_preferences`

Preferencias de zonas/corredores y criterios de difusion asociadas al carrier. No deben confundirse con disponibilidad fechada ni usarse para reservar capacidad.

### Documentos y mensajes

La entidad `documents` existente debe asociarse a carrier/vehiculo y solicitud de homologacion con tipo, metadata segura, estado de revision, vigencia cuando aplique y referencia privada al archivo. Revisar si el esquema actual permite el ciclo de vida completo antes de extenderlo. Los mensajes requieren actor/direccion/estado suficiente para mostrar el hilo humano/agente del backoffice; verificar contrato real antes de proponer cambios fisicos.

### Productores y consultas de backoffice

La ficha de Productor es una vista agregada sobre `producers`, `shipment_requests`, `trip_offers`, `assignments`, `trips`, `messages` y `event_logs`; no implica duplicar esas relaciones en una nueva tabla.

## Riesgos Del Modelo De Datos

1. Tablas genericas como `documents` y `risk_flags` pueden volverse ambiguas si no se documentan tipos.
2. `payment_terms` puede confundirse con pagos reales si no se mantiene el limite MVP.
3. `field_confidence` en JSON puede dificultar analytics si no se normaliza en el futuro.
4. Event logs incompletos impiden reconstruir estado.
5. Ubicaciones rurales mal normalizadas degradan supply/demand analytics.

## Decisiones Pendientes Con Negocio

1. Lista final de estados visibles para operador.
2. Campos criticos por tipo de carga.
3. Politica de vencimiento de ofertas.
4. Que condiciones economicas registrar en MVP.
5. Nivel minimo de detalle de vehiculos.

## Proximo Paso Recomendado

Convertir este modelo logico en contratos de entidades y eventos. Recien despues definir migraciones y constraints fisicas.
