# API Design Conceptual

Este documento define endpoints conceptuales para el MVP. No incluye codigo ni contratos finales OpenAPI.

Reglas globales:

- Todo endpoint que cambia estado genera `EventLog`.
- Toda accion critica debe ser idempotente o transaccional.
- Todo webhook debe ser idempotente.
- API layer no contiene logica de negocio.
- KAPSO no cambia estados de dominio.
- El flujo feliz usa endpoints self-service por telefono de productor; admin queda para soporte.

## Endpoints Self-Service Marketplace

| Metodo | Path | Objetivo |
| --- | --- | --- |
| GET | `/api/v1/producer/shipments` | Listar cargas propias del productor por telefono normalizado. |
| GET | `/api/v1/producer/shipments/interested-offers` | Listar ofertas `INTERESTED` de cargas propias en matching. |
| POST | `/api/v1/shipments/{shipment_id}/offers/{trip_offer_id}/accept` | Productor acepta una oferta y confirma el match. |

Reglas importantes:

- El backend valida ownership por telefono del productor.
- Solo se acepta `TripOffer.response_type = INTERESTED`.
- La carga debe estar en `MATCHING`.
- Si ya existe assignment activo, el endpoint devuelve el existente y no duplica.
- La aceptacion crea `Assignment.CONFIRMED`, `Trip.PLANNED` y carga `ASSIGNED`.
- Eventos: `PRODUCER_OFFER_ACCEPTED`, `ASSIGNMENT_CREATED`, `TRIP_CREATED`, `MARKETPLACE_MATCH_CONFIRMED`, `ASSIGNMENT_CONFIRMED`.

## Backoffice De Conversaciones

Estos endpoints son de soporte/admin y requieren autenticacion de operador.

| Metodo | Path | Objetivo |
| --- | --- | --- |
| GET | `/api/v1/backoffice/conversations/{conversation_session_id}/messages` | Abrir hilo cronologico autenticado; incluye textos humanos/agente, etiquetas de rol/escenario y fallos de respuesta conocidos, sin payloads de medios. |

## Backoffice De Notificaciones

| Metodo | Path | Objetivo |
| --- | --- | --- |
| GET | `/api/v1/backoffice/notification-outbox` | Consultar cantidades por estado y pagina de envios pendientes/aceptados/fallidos; permite filtrar por `status`. |

La respuesta expone estado operativo, tipo de aviso, entidad relacionada, intentos y codigo de error acotado. No devuelve cuerpo, telefono, phone number ID ni message ID del proveedor. Requiere operador; no ofrece reenvio ni cambios de estado. La autenticacion humana compartida sigue pendiente de Supabase Auth.

## Backoffice De Homologacion De Transportistas

Estos endpoints son de soporte/admin y requieren autenticacion de operador.

| Metodo | Path | Objetivo |
| --- | --- | --- |
| GET | `/api/v1/backoffice/carriers` | Listar todos los transportistas con filtros de validacion y busqueda. |
| POST | `/api/v1/backoffice/carriers` | Crear transportista manualmente desde backoffice. |
| PATCH | `/api/v1/backoffice/carriers/{carrier_id}` | Editar datos generales del transportista. |
| GET | `/api/v1/backoffice/carrier-onboarding/pending` | Listar transportistas con homologacion pendiente o no aprobada. |
| GET | `/api/v1/backoffice/carriers/{carrier_id}/onboarding` | Ver detalle de carrier, vehiculos, documentos, onboarding y eventos. |
| GET | `/api/v1/backoffice/carriers/{carrier_id}/documents` | Listar documentos del carrier y sus conductores/unidades, identificando cada dueño. |
| POST | `/api/v1/backoffice/carriers/{carrier_id}/approve` | Aprobar homologacion del transportista. |
| POST | `/api/v1/backoffice/carriers/{carrier_id}/suspend` | Suspender carrier aprobado o en operacion con motivo. |
| POST | `/api/v1/backoffice/carriers/{carrier_id}/mark-in-review` | Volver a revision luego de cambios o subsanaciones. |
| POST | `/api/v1/backoffice/carriers/{carrier_id}/reject` | Rechazar homologacion con motivo. |
| POST | `/api/v1/backoffice/carriers/{carrier_id}/vehicles` | Crear vehiculo asociado al carrier. |
| PATCH | `/api/v1/backoffice/carriers/{carrier_id}/vehicles/{vehicle_id}` | Editar vehiculo asociado. |
| DELETE | `/api/v1/backoffice/carriers/{carrier_id}/vehicles/{vehicle_id}` | Desactivar vehiculo asociado. |
| POST | `/api/v1/backoffice/carriers/{carrier_id}/vehicles/{vehicle_id}/approve` | Aprobar la revision humana de una unidad con nota obligatoria. |
| GET | `/api/v1/backoffice/carriers/{carrier_id}/drivers` | Listar conductores asociados a un carrier. |
| POST | `/api/v1/backoffice/carriers/{carrier_id}/drivers` | Crear conductor pendiente de revision. |
| POST | `/api/v1/backoffice/carriers/{carrier_id}/drivers/{driver_id}/approve` | Aprobar conductor con categoria de licencia y nota obligatoria de revision. |
| POST | `/api/v1/backoffice/carriers/{carrier_id}/drivers/{driver_id}/reject` | Rechazar conductor con motivo. |
| POST | `/api/v1/backoffice/trips/{trip_id}/crew` | Asignar conductor y vehiculo del carrier al viaje planificado. |
| GET | `/api/v1/backoffice/carriers/{carrier_id}/documents/{document_id}/content` | Descargar un archivo local privado, previa autenticacion de operador y verificacion de pertenencia. |
| POST | `/api/v1/backoffice/carriers/{carrier_id}/documents` | Crear documento manual asociado al carrier, a un conductor suyo o a una unidad suya (`entity_type` + `entity_id`). |
| PATCH | `/api/v1/backoffice/carriers/{carrier_id}/documents/{document_id}` | Editar metadatos de un documento asociado; no permite cambiar su dueño. |
| POST | `/api/v1/backoffice/carriers/{carrier_id}/documents/{document_id}/approve` | Aprobar documento de transportista. |
| POST | `/api/v1/backoffice/carriers/{carrier_id}/documents/{document_id}/reject` | Rechazar documento de transportista con motivo. |
| GET | `/api/v1/backoffice/whatsapp-allowlist` | Listar numeros autorizados por telefono, ambiente y provider. |
| POST | `/api/v1/backoffice/whatsapp-allowlist` | Crear numero autorizado o bloqueado. |
| PATCH | `/api/v1/backoffice/whatsapp-allowlist/{contact_id}` | Editar numero autorizado. |
| POST | `/api/v1/backoffice/whatsapp-allowlist/{contact_id}/block` | Bloquear numero. |
| POST | `/api/v1/backoffice/whatsapp-allowlist/{contact_id}/reactivate` | Reactivar numero bloqueado o deshabilitado. |
| POST | `/api/v1/backoffice/whatsapp-allowlist/{contact_id}/disable` | Deshabilitar numero sin borrarlo. |

Reglas importantes:

- Aprobar carrier setea `is_validated=true` y `validation_status=APPROVED`.
- Suspender carrier fuerza `is_validated=false` y `validation_status=SUSPENDED`.
- Marcar en revision mueve el carrier a `validation_status=PENDING_REVIEW`.
- Rechazar carrier setea `is_validated=false`, `validation_status=REJECTED` y conserva motivo.
- No se aprueba carrier si faltan telefono, CUIT, vehiculo o documento adjunto.
- Los listados/detalles devuelven documentos de carrier, conductor y vehiculo bajo su entidad correspondiente, sin `external_uri` ni `storage_uri`; los archivos locales se descargan como adjunto privado, sin cache, con verificacion de pertenencia y ruta bajo `MEDIA_STORAGE_DIR`, y evento de acceso. No se sirven URLs externas.
- Los documentos recibidos por WhatsApp/KAPSO exponen metadatos de origen:
  `provider`, `provider_media_id`, `mime_type`, `file_name` y `uploaded_by_phone`.
- Cada conductor y unidad tiene revision independiente. Los cambios de datos operativos del vehiculo reinician su estado a `PENDING_REVIEW`.
- El inicio y el paso a transito requieren carrier aprobado y conductor/unidad asignados al viaje, activos y aprobados individualmente. El endpoint generico de edicion no puede cambiar estados de viaje.
- La nota de aprobacion registra la declaracion de revision humana, no constituye una matriz legal de documentos ni una validacion automatica.
- Asociar un archivo a Driver/Vehicle no aprueba la entidad. La carga de archivos desde WhatsApp, su asociacion a una solicitud abierta y las reglas de retencion siguen pendientes.
- Todo cambio registra `EventLog`.

La lectura del hilo requiere `require_operator_user`. Solo expone el cuerpo para mensajes de texto/interactivos; medios, URLs e IDs del proveedor quedan fuera. Un outbound guardado acredita aceptacion del proveedor, no entrega final; los errores conversacionales conocidos se muestran como avisos de sistema.

## Convenciones

- Paths versionados bajo `/api/v1`.
- Request examples son ilustrativos.
- IDs internos son backend-owned.
- IDs externos de KAPSO/WhatsApp se guardan como referencias.

## Health/Auth

| Metodo | Path | Objetivo |
| --- | --- | --- |
| GET | `/health` | Verificar disponibilidad basica. |

Request: ninguno.

Response:

```json
{ "status": "ok" }
```

Eventos generados: ninguno.

Reglas importantes: no exponer datos sensibles.

La autenticacion humana esta preparada para Supabase Auth, pero no se conecta a
un proyecto hasta configurarlo. El frontend inicia sesion por correo y envia
el access token; el backend verifica firma asimetrica mediante JWKS, issuer,
audience, emision y vencimiento. Identifica a la persona por `sub` y resuelve
`operator`/`admin` desde `operator_roles`, administrada por el servidor, con un
usuario bootstrap configurado fuera del cliente. No se aceptan roles de
`user_metadata` ni headers enviados por el navegador como identidad compartida.

Mientras tanto, los headers `x-operator-user-id` y `x-operator-role` solo se
aceptan en `APP_ENV=local`/desarrollo. En entornos compartidos, `INTERNAL_API_KEY`
es exclusivamente para la integracion backend y se convierte en un principal
fijo `service:agro-backend-client`; no representa a una persona ni permite
atribuirle acciones a un operador real. No incluir esa clave en el bundle web.
El backoffice humano compartido sigue cerrado hasta configurar Supabase Auth,
aplicar la migracion de roles y auditar lecturas sensibles. En desarrollo
local, la identidad sintetica solo esta habilitada bajo `APP_ENV=local`.

## Webhooks

| Metodo | Path | Objetivo |
| --- | --- | --- |
| POST | `/api/v1/webhooks/kapso` | Recibir evento KAPSO/WhatsApp. |

Request:

```json
{
  "provider": "kapso",
  "idempotency_key": "provider-event-key",
  "event_type": "message.received",
  "provider_message_id": "wamid...",
  "conversation_id": "kapso-conv-id",
  "workflow_execution_id": "optional",
  "phone_number": "+549...",
  "payload": {
    "type": "document",
    "caption": "dni frente",
    "document": {
      "id": "provider-media-id",
      "url": "https://provider.example/media/...",
      "mime_type": "application/pdf",
      "filename": "dni.pdf"
    }
  }
}
```

Response:

```json
{ "accepted": true, "deduplicated": false, "correlation_id": "corr_..." }
```

Eventos generados: `MESSAGE_RECEIVED`, eventos tecnicos de webhook, `DATA_EXTRACTED`
si aplica luego en job. Si el evento trae media, tambien puede registrar
`MEDIA_ASSET_RECEIVED`, `CARRIER_DOCUMENT_CREATED_FROM_MEDIA` o
`MEDIA_UNMATCHED_TO_CARRIER`. Si el evento trae una seleccion interactiva, registra
`INTERACTIVE_ACTION_SELECTED` y conserva el valor en `Message.normalized_content`.

Reglas importantes:

- Validar HMAC.
- Deduplicar por provider + idempotency_key.
- Encolar procesamiento async.
- Tolerar eventos batched y fuera de orden.
- Tratar media como entrada de canal: crear `MediaAsset`; crear un `Document` pendiente
  solo cuando la logica de conversacion resuelva un `carrier_id` activo para ese mensaje.
  No asociar documentos por coincidencia de telefono dentro del servicio de media.
- Normalizar respuestas interactivas desde shapes como `interactive.button_reply.id`,
  `button_reply.id` o `payload`. Texto libre sigue funcionando.

## Mensajes Interactivos / Quick Replies

El backend expresa opciones clickeables como acciones genericas, no como payloads
KAPSO:

```json
{
  "body": "¿Tenés empresa?",
  "actions": [
    { "id": "yes", "label": "Sí", "value": "yes", "kind": "quick_reply" },
    { "id": "no", "label": "No", "value": "no", "kind": "quick_reply" }
  ]
}
```

Fallback textual cuando el canal no soporta interactivos:

```text
¿Tenés empresa?

1. Sí
2. No

Respondé con el número o el texto de la opción.
```

Reglas importantes:

- El application layer usa `OutboundAction`; Kapso traduce solo si el flag lo permite.
- `KAPSO_INTERACTIVE_ENABLED=false` por default.
- Hasta 3 opciones pueden salir como botones directos si el provider declara soporte.
- La confirmacion/edicion de carga, las respuestas a nuevas cargas y la seleccion de oferta ofrecen botones directos cuando tienen hasta tres opciones.
- Los menus de productor y transportista ofrecen una lista interactiva con sus cinco opciones; no se fuerzan cinco botones en un mensaje que admite hasta tres.
- Las acciones enviadas quedan en `EventLog.payload.interactive_actions`, junto con rol y escenario QA cuando aplican.
- La respuesta del boton se resuelve contra el ultimo conjunto de acciones aceptado para esa conversacion, rol y escenario; los botones vencidos no se ejecutan.
- Si el provider no tiene botones habilitados, se conserva el fallback numerado/textual y se enruta con las mismas validaciones del dominio.
- Las listas interactivas admiten hasta diez opciones. Si estan deshabilitadas o el provider no las soporta, queda el fallback numerado/textual.

| Metodo | Path | Objetivo |
| --- | --- | --- |
| POST | `/api/v1/webhooks/normalize` | Normalizar evento externo para procesamiento interno. |

Request:

```json
{ "provider": "kapso", "raw_event_id": "evt_external" }
```

Response:

```json
{ "normalized": true, "message_id": "msg_...", "conversation_session_id": "cs_..." }
```

Eventos generados: `MESSAGE_RECEIVED` o evento tecnico de normalizacion.

Reglas importantes: no cambia dominio; solo canal/mensaje.

## Shipment Requests

| Metodo | Path | Objetivo |
| --- | --- | --- |
| POST | `/api/v1/shipment-requests/from-chat` | Preparar vista previa/candidato desde texto; el nombre de ruta es conceptual y no implica persistir una carga. |

Request:

```json
{
  "text": "Necesito mover novillos, todavia no defini fecha ni origen",
  "phone_number": "+5491112345678",
  "idempotency_key": "kapso-chat-..."
}
```

Response:

```json
{
  "preview": true,
  "cargo_category": "LIVESTOCK",
  "cargo_type": "novillos",
  "missing_fields": ["origin", "destination", "date", "quantity"]
}
```

Evento generado: `LOAD_PREVIEW_PREPARED`; no se crea una fila de carga hasta la confirmacion explicita del productor.

Para granos basicos, `cargo_category` es `GRAIN`, `cargo_type` puede ser `soja`, `maiz`, `trigo`, `girasol`, `sorgo` o `cebada`, y `quantity_unit` puede ser `TON`, `KG` o `TRUCKLOAD`.

Reglas importantes: el preview no publica ni persiste una carga y no crea ofertas/asignaciones. Tras la confirmacion del productor, el backend valida y crea/publica; soporte interviene ante faltantes criticos o excepciones.

| Metodo | Path | Objetivo |
| --- | --- | --- |
| POST | `/api/v1/shipment-requests` | Crear necesidad de transporte. |

Request:

```json
{
  "producer_id": "prod_...",
  "origin": "Rauch",
  "destination": "Liniers",
  "date_window": "martes",
  "cargo_category": "LIVESTOCK",
  "cargo_type": "novillos",
  "quantity_unit": "HEAD",
  "livestock_type": "novillos",
  "quantity_estimate": 35,
  "source_message_id": "msg_..."
}
```

Response:

```json
{
  "id": "sr_...",
  "status": "INCOMPLETE",
  "missing_critical_fields": ["origin", "destination", "date", "quantity"],
  "requires_human_review": false
}
```

Eventos generados: `LOAD_CREATED`, `LOAD_INCOMPLETE` si aplica.

Reglas importantes: puede nacer incompleta. En el flujo self-service, la publicacion ocurre por confirmacion del productor y reglas del backend.

| Metodo | Path | Objetivo |
| --- | --- | --- |
| GET | `/api/v1/shipment-requests/{id}` | Leer carga. |

Response:

```json
{ "id": "sr_...", "status": "PENDING_OPERATOR_REVIEW" }
```

Eventos generados: ninguno.

| Metodo | Path | Objetivo |
| --- | --- | --- |
| PATCH | `/api/v1/shipment-requests/{id}` | Actualizar datos de carga. |

Request:

```json
{ "quantity_estimate": 40, "change_reason": "producer correction" }
```

Response:

```json
{ "id": "sr_...", "status": "PENDING_OPERATOR_REVIEW" }
```

Eventos generados: `LOAD_UPDATED`, `LOAD_REOPENED` si el cambio es critico.

Reglas importantes: cambios de origen, destino, fecha o cantidad requieren evento y pueden requerir soporte.

| Metodo | Path | Objetivo |
| --- | --- | --- |
| POST | `/api/v1/shipment-requests/{id}/validate` | Validar carga por soporte/admin. |

Request:

```json
{ "operator_user_id": "user_...", "notes": "datos minimos revisados" }
```

Response:

```json
{ "id": "sr_...", "status": "VALIDATED" }
```

Eventos generados: `LOAD_VALIDATED`.

Reglas importantes: solo soporte/admin; no valida si faltan criticos sin override documentado.

| Metodo | Path | Objetivo |
| --- | --- | --- |
| POST | `/api/v1/shipment-requests/{id}/publish` | Publicar carga a carriers. |

Request:

```json
{ "operator_user_id": "user_...", "carrier_ids": ["car_1", "car_2"] }
```

Response:

```json
{ "id": "sr_...", "status": "PUBLISHED", "notifications_queued": 2 }
```

Eventos generados: `LOAD_PUBLISHED`, `BROADCAST_SENT`, `CARRIER_NOTIFIED`.

Reglas importantes: el flujo principal publica tras confirmacion del productor sin aprobacion manual de cada carga; este endpoint documenta publicacion administrativa/excepcional. El backend selecciona carriers aprobados y elegibles; KAPSO solo envia.

| Metodo | Path | Objetivo |
| --- | --- | --- |
| POST | `/api/v1/shipment-requests/{id}/cancel` | Cancelar necesidad. |

Request:

```json
{ "actor_user_id": "user_...", "reason": "producer cancelled" }
```

Response:

```json
{ "id": "sr_...", "status": "CANCELLED" }
```

Eventos generados: `LOAD_CANCELLED`.

Reglas importantes: si hay assignment/trip activo, escalar a operador.

## Trips

| Metodo | Path | Objetivo |
| --- | --- | --- |
| POST | `/api/v1/trips` | Crear trip desde assignment confirmado o desde seleccion manual previa. |

Request:

```json
{ "assignment_id": "asg_...", "operator_user_id": "user_..." }
```

Response:

```json
{ "id": "trip_...", "status": "PLANNED" }
```

Eventos generados: `TRIP_CREATED`.

Reglas importantes: no crear sin `Assignment.CONFIRMED` o seleccion manual de oferta por operador. `PLANNED` no confirma el viaje.

| Metodo | Path | Objetivo |
| --- | --- | --- |
| POST | `/api/v1/trips/{id}/confirm` | Confirmar datos operativos del viaje. |

Request:

```json
{ "operator_user_id": "user_...", "notes": "partes notificadas" }
```

Response:

```json
{ "id": "trip_...", "status": "PLANNED" }
```

Eventos generados: `TRIP_CREATED` si aun no existia, o evento de actualizacion operativa.

Reglas importantes: confirmacion final depende de operador.

| Metodo | Path | Objetivo |
| --- | --- | --- |
| POST | `/api/v1/trips/{id}/start` | Registrar inicio operativo. |

Request:

```json
{ "actor_user_id": "user_or_carrier", "source": "operator" }
```

Response:

```json
{ "id": "trip_...", "status": "LOADING_PENDING" }
```

Eventos generados: `TRIP_STARTED`.

| Metodo | Path | Objetivo |
| --- | --- | --- |
| POST | `/api/v1/trips/{id}/complete` | Completar/cerrar viaje. |

Request:

```json
{ "operator_user_id": "user_...", "closure_notes": "entrega confirmada" }
```

Response:

```json
{ "id": "trip_...", "status": "COMPLETED" }
```

Eventos generados: `TRIP_COMPLETED`, `LOAD_CLOSED`.

Reglas importantes: cierre por operador.

| Metodo | Path | Objetivo |
| --- | --- | --- |
| POST | `/api/v1/trips/{id}/cancel` | Cancelar viaje. |

Request:

```json
{ "operator_user_id": "user_...", "reason": "carrier cancelled" }
```

Response:

```json
{ "id": "trip_...", "status": "CANCELLED" }
```

Eventos generados: `TRIP_CANCELLED`.

| Metodo | Path | Objetivo |
| --- | --- | --- |
| POST | `/api/v1/trips/{id}/reschedule` | Reprogramar viaje. |

Request:

```json
{ "operator_user_id": "user_...", "new_date_window": "miercoles tarde", "reason": "weather" }
```

Response:

```json
{ "id": "trip_...", "status": "PLANNED", "requires_human_review": false }
```

Eventos generados: `TRIP_UPDATED`, posible `HUMAN_REVIEW_REQUESTED`.

Reglas importantes: reprogramacion es cambio critico y requiere operador.

## Offers

| Metodo | Path | Objetivo |
| --- | --- | --- |
| GET | `/api/v1/shipment-requests/{id}/offers` | Listar ofertas por carga. |

Response:

```json
{ "items": [{ "id": "off_...", "status": "INTERESTED" }] }
```

Eventos generados: ninguno.

| Metodo | Path | Objetivo |
| --- | --- | --- |
| POST | `/api/v1/shipment-requests/{id}/offers` | Registrar interes/oferta. |

Request:

```json
{ "carrier_id": "car_...", "response_type": "interested", "price_estimate": 1000, "source_message_id": "msg_..." }
```

Response:

```json
{ "id": "off_...", "status": "PRICE_PROVIDED", "requires_human_review": false }
```

Eventos generados: `OFFER_RECEIVED`.

Reglas importantes: offer no confirma assignment.

| Metodo | Path | Objetivo |
| --- | --- | --- |
| POST | `/api/v1/offers/{id}/reject` | Rechazar oferta. |

Request:

```json
{ "operator_user_id": "user_...", "reason": "not suitable" }
```

Response:

```json
{ "id": "off_...", "status": "REJECTED" }
```

Eventos generados: `OFFER_REJECTED`.

| Metodo | Path | Objetivo |
| --- | --- | --- |
| POST | `/api/v1/shipments/{shipment_id}/select-offer` | Seleccionar oferta para assignment y trip planificado. |

Request:

```json
{ "trip_offer_id": "off_...", "idempotency_key": "select_..." }
```

Response:

```json
{ "assignment_id": "asg_...", "assignment_status": "PROPOSED", "trip_id": "trip_...", "trip_status": "PLANNED" }
```

Eventos generados: `ASSIGNMENT_CREATED`, `ASSIGNMENT_SELECTED`, `TRIP_CREATED`.

Reglas importantes: solo operador; el shipment debe estar en `MATCHING`; seleccionar no confirma assignment ni cierra otras offers.

## Assignments

| Metodo | Path | Objetivo |
| --- | --- | --- |
| POST | `/api/v1/assignments` | Proponer assignment. |

Request:

```json
{ "shipment_request_id": "sr_...", "trip_offer_id": "off_...", "carrier_id": "car_...", "vehicle_id": "veh_..." }
```

Response:

```json
{ "id": "asg_...", "status": "PROPOSED" }
```

Eventos generados: `MATCH_PROPOSED`, `ASSIGNMENT_CREATED` si avanza a propuesta o pendiente.

| Metodo | Path | Objetivo |
| --- | --- | --- |
| POST | `/api/v1/assignments/{id}/confirm` | Confirmacion excepcional por soporte; el flujo feliz usa el endpoint de aceptacion de oferta por el productor. |

Request:

```json
{ "operator_user_id": "user_...", "confirmation_notes": "carrier and producer confirmed" }
```

Response:

```json
{ "id": "asg_...", "status": "CONFIRMED", "trip_id": "trip_..." }
```

Eventos generados: `ASSIGNMENT_CONFIRMED`, `TRIP_CREATED`.

Reglas importantes: solo operador para este endpoint excepcional; transaccional e idempotente. En el flujo feliz, la aceptacion del productor valida ownership y crea/retorna assignment y trip en una sola operacion.

| Metodo | Path | Objetivo |
| --- | --- | --- |
| POST | `/api/v1/assignments/{id}/cancel` | Cancelar assignment. |

Request:

```json
{ "operator_user_id": "user_...", "reason": "carrier unavailable" }
```

Response:

```json
{ "id": "asg_...", "status": "CANCELLED" }
```

Eventos generados: `ASSIGNMENT_CANCELLED`.

| Metodo | Path | Objetivo |
| --- | --- | --- |
| POST | `/api/v1/assignments/{id}/replace` | Reemplazar assignment. |

Request:

```json
{ "operator_user_id": "user_...", "replacement_offer_id": "off_2" }
```

Response:

```json
{ "old_assignment_id": "asg_...", "new_assignment_id": "asg_2", "status": "REPLACED" }
```

Eventos generados: `ASSIGNMENT_REPLACED`, `MATCH_PROPOSED`.

## Carriers

| Metodo | Path | Objetivo |
| --- | --- | --- |
| POST | `/api/v1/carriers` | Crear carrier. |
| GET | `/api/v1/carriers` | Listar carriers. |
| PATCH | `/api/v1/carriers/{id}` | Actualizar carrier. |
| POST | `/api/v1/carriers/{id}/vehicles` | Crear vehiculo. |
| GET | `/api/v1/carriers/{id}/vehicles` | Listar vehiculos. |
| POST | `/api/v1/carriers/{id}/availability` | Disponibilidad futura basica. |

Request ejemplo:

```json
{ "name": "Transportes X", "contact_phone": "+549...", "service_zone": "Buenos Aires" }
```

Response ejemplo:

```json
{ "id": "car_...", "is_validated": false }
```

Eventos generados: eventos de auditoria operativa cuando afecte coordinacion.

Reglas importantes: disponibilidad futura es nota operativa, no reserva automatica.

### Disponibilidad Y Consulta Por Ruta (contrato propuesto)

La disponibilidad actual tipo nota no es suficiente para los recorridos fechados y capacidad parcial del alcance. Antes de reemplazarla, definir endpoints/DTOs dedicados, por ejemplo:

| Metodo | Path propuesto | Objetivo |
| --- | --- | --- |
| POST | `/api/v1/carriers/{id}/route-availabilities` | Crear disponibilidad declarada por el carrier. |
| GET | `/api/v1/carriers/{id}/route-availabilities` | Listar disponibilidades propias con estado/expiracion. |
| PATCH | `/api/v1/carriers/{id}/route-availabilities/{availability_id}` | Corregir, pausar o cancelar disponibilidad propia. |
| POST | `/api/v1/carriers/route-search` | Consultar oportunidades por origen/destino/ventana. |
| PUT | `/api/v1/carriers/{id}/search-preferences` | Actualizar preferencias de difusion por zonas/criterios. |

Validar ownership, homologacion cuando aplique, capacidad/unidad, fechas y zonas canonicas. La busqueda devuelve sugerencias con motivo de compatibilidad y alternativas de parada/desvio identificadas; no crea ofertas, reservas, assignments ni trips por el solo hecho de buscar.

La normalizacion inicial de localidades usa el snapshot local versionado de
Georef (`data/catalogs/georef/localidades.csv`), excluye entidades anidadas y
no consulta la API durante una conversacion. Una coincidencia exacta unica se
canoniza; nombres homonimos requieren provincia/confirmacion. Establecimientos
y referencias rurales fuera del catalogo se conservan como texto declarado.
La persistencia de ID, version y procedencia se agrega en la migracion
`0011_georef_location_provenance` (pendiente de aplicacion).

### Homologacion Iniciada Por WhatsApp

La primera captura conversacional se inicia con una solicitud explicita de alta. El backend persiste el paso activo en `CarrierOnboarding.capture_context` y pregunta progresivamente nombre/razon social, email, empresa opcional, CUIT declarado, cantidad de unidades y datos de cada unidad y su conductor (nombre, telefono y licencia), uno por vez. El conductor puede declarar que usa el telefono de contacto del transportista. El transportista puede pausar la carga de flota y soporte completa los pendientes. Al terminar, recibe un resumen y puede confirmar o corregir campos del perfil, cada unidad y cada conductor; las correcciones validan formato y se auditan sin guardar valores personales en el payload. El flujo no reutiliza el telefono para deducir el rol en modo QA: los comandos de rol productor/operador no pueden iniciar ni continuar esta captura.

Durante el paso `driver_license_upload`, el adjunto se asocia al `Driver` indicado por el onboarding abierto y debe pertenecer al mismo Carrier. En otros pasos, o si no se valida esa relacion, no se crea un documento de homologacion. La licencia y los datos declarados quedan pendientes de revision humana; recibirlos no aprueba Carrier, Driver o Vehicle ni habilita operaciones. La captura actual registra una unidad y un conductor por solicitud; el inventario adicional y la politica documental siguen pendientes de definicion.

La API no debe exponer URLs publicas ni aprobar automaticamente por presencia de un documento. Soporte conserva endpoints de revision existentes para pedir correcciones/aprobar/rechazar y genera eventos auditables. La migracion `0008_carrier_onboarding_capture_context` agrega el contexto persistente y requiere aplicacion coordinada antes de desplegar esta version SQL.

## Producers

| Metodo | Path | Objetivo |
| --- | --- | --- |
| POST | `/api/v1/producers` | Crear productor/comisionista. |
| GET | `/api/v1/producers` | Listar productores. |
| PATCH | `/api/v1/producers/{id}` | Actualizar productor. |

Request ejemplo:

```json
{ "name": "Productor X", "contact_phone": "+549..." }
```

Response ejemplo:

```json
{ "id": "prod_...", "is_validated": false }
```

Eventos generados: auditoria si cambia dato sensible.

### Productores En Backoffice

Los endpoints administrativos de productores deben requerir autenticacion y permisos de soporte. Contrato conceptual pendiente de implementar:

| Metodo | Path propuesto | Objetivo |
| --- | --- | --- |
| GET | `/api/v1/backoffice/producers` | Buscar/listar productores con filtros y paginacion. |
| GET | `/api/v1/backoffice/producers/{id}` | Ver perfil y resumen de cargas, ofertas, assignments/trips, eventos y conversaciones vinculadas. |

La respuesta muestra solo campos persistidos, indica faltantes y aplica minimizacion por rol. Evitar respuestas con mensajes/documentos completos cuando una referencia o resumen sea suficiente.

### Conversaciones En Backoffice

Contrato conceptual pendiente: listar hilos y cargar mensajes por cursor/fecha en orden cronologico, con actor/emisor (persona, agente, operador o sistema), direccion, timestamp, contenido autorizado y estado del provider cuando exista. Las respuestas del agente deben estar guardadas como mensajes salientes relacionados al hilo para que la interfaz no tenga que reconstruirlas desde logs.

La consulta debe filtrar por permisos y escenario QA; no mezclar historiales de pruebas cerradas en una conversacion productiva. El endpoint de envio manual, si se habilita, debe auditar operador, accion y resultado, con idempotencia y confirmaciones apropiadas.

## Messages

| Metodo | Path | Objetivo |
| --- | --- | --- |
| GET | `/api/v1/conversations/{id}/messages` | Listar conversacion. |
| POST | `/api/v1/conversations/{id}/messages` | Enviar mensaje. |

Request ejemplo:

```json
{ "body": "Necesitamos confirmar origen.", "send_as": "operator" }
```

Response ejemplo:

```json
{ "message_id": "msg_...", "status": "queued" }
```

Eventos generados: `MESSAGE_SENT`.

Reglas importantes: outbound usa adapter; no prometer confirmaciones sin operador.

## Admin/Ops

| Metodo | Path | Objetivo |
| --- | --- | --- |
| GET | `/api/v1/admin/ops/pending-shipments` | Cargas pendientes. |
| GET | `/api/v1/admin/ops/incomplete-shipments` | Cargas con datos faltantes. |
| GET | `/api/v1/admin/ops/risky-trips` | Viajes en riesgo. |
| POST | `/api/v1/admin/ops/fallback` | Activar fallback manual. |

Request fallback:

```json
{ "entity_type": "shipment_request", "entity_id": "sr_...", "reason": "ambiguous location" }
```

Response:

```json
{ "handoff_required": true, "status": "queued_for_operator" }
```

Eventos generados: `HUMAN_REVIEW_REQUESTED` y eventos de riesgo si aplica.

Reglas importantes: admin/ops asiste decision humana; no saltea domain services.

## Decisiones Tecnicas Tomadas

1. API REST conceptual para MVP.
2. Endpoints de accion para transiciones criticas.
3. Webhooks separados de procesamiento de dominio.
4. KAPSO tratado como provider externo.
5. EventLog como efecto obligatorio de mutaciones.

## Riesgos Tecnicos

1. Endpoints de accion pueden duplicar logica si no usan application services comunes.
2. Request examples pueden parecer contrato final antes de validar.
3. Auth admin insuficiente aumenta riesgo operativo.
4. Webhook sync puede degradar si no hay queue.
5. Falta de idempotency keys puede duplicar eventos.

## Que Implementar Primero

1. Webhook KAPSO idempotente.
2. Shipment request create/validate/publish.
3. Offer registration y assignment confirmation con EventLog transaccional.

## Contratos de backoffice incorporados

- `GET/POST /api/v1/backoffice/route-availabilities`, `PATCH /{id}/status` y `POST /route-availabilities/match` permiten a un operador registrar disponibilidad declarada, activarla/cerrarla/cancelarla y consultar coincidencias explicables por tramo. El match es una consulta de apoyo: no crea oferta ni compromete disponibilidad. La pantalla `Disponibilidad` consume estos endpoints. La captura WhatsApp guiada persiste contexto en `conversation_sessions.route_availability_capture`, crea la entidad tras confirmacion y etiqueta el escenario QA; requiere las migraciones hasta `0015_route_availability_capture`.
- Listar o buscar también transiciona una disponibilidad activa con `window_end` vencido a `EXPIRED` y registra el evento. Las fechas declaradas sin hora se guardan hasta el final del día en `America/Argentina/Buenos_Aires`. La captura WhatsApp no dispara ofertas ni busca cargas automáticamente.
- La alta/edicion de documentos de transportista acepta `valid_from`, `expires_at` y `supersedes_document_id`. La referencia de renovacion debe apuntar a un documento existente de la misma persona/unidad/transportista; los registros anteriores se conservan. La migracion `0013_document_validity` es aditiva y todavia no se aplico a una base compartida.
- En modo no productivo, CORS acepta puertos de desarrollo solo para `localhost`/`127.0.0.1`, además de los puertos Vite configurados. Producción no habilita esta regla.

- `GET /api/v1/backoffice/producers?search=&limit=&offset=` lista los perfiles persistidos y sus conteos operativos; `GET /api/v1/backoffice/producers/{producer_id}` devuelve cargas, ofertas, viajes, conversaciones y eventos relacionados. No crea perfiles inferidos.
- `GET /api/v1/backoffice/notification-outbox?status=&limit=&offset=` expone solo estado y metadatos operativos, sin cuerpo, telefono, phone number ID ni message ID del proveedor.
- `POST /api/v1/backoffice/notification-outbox/{outbox_id}/reconcile` requiere rol admin y una referencia de evidencia. `resolution=ACCEPTED` registra que el operador verifico aceptacion; `resolution=RETRY_NOT_SENT` permite otro intento solo tras verificar que el proveedor no acepto el mensaje. La decision queda auditada y no equivale a entrega/lectura.
- La conciliacion solo esta habilitada para la identidad admin de desarrollo local hasta integrar JWT Supabase y roles administrados por servidor. No enviar `INTERNAL_API_KEY` al navegador.
