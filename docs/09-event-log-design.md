# Diseno Del Event Log

Este documento define el sistema conceptual de auditoria para AGRO Logistics MVP.

No describe base de datos fisica, particiones, colas, APIs ni infraestructura. Su objetivo es definir que debe quedar registrado para reconstruir la operacion, medir el MVP y auditar decisiones.

## Principios

- Todo cambio relevante genera un evento.
- Los cambios de estado deben registrar estado anterior y nuevo.
- Cada evento debe indicar quien o que lo genero.
- Los eventos deben poder relacionarse con `LivestockLoad`, `Offer`, `Assignment`, `Trip`, `CarrierOnboarding`, `CarrierRouteAvailability`, `ConversationSession` y `Message`.
- Las metricas deben derivarse de eventos, no de mensajes sueltos ni memoria informal.
- El event log no reemplaza reglas de dominio ni soporte humano: documenta lo que ocurrio.

## Estructura Conceptual Del Evento

```json
{
  "eventId": "evt_...",
  "eventType": "LOAD_CREATED",
  "occurredAt": "ISO-8601 timestamp",
  "actorType": "Operator | Producer | Carrier | Bot | AI Agent | System",
  "actorId": "optional",
  "entityType": "LivestockLoad | Offer | Assignment | Trip | CarrierOnboarding | CarrierRouteAvailability | CarrierSearchPreference | Message | ConversationSession",
  "entityId": "required",
  "relatedEntityIds": {
    "loadId": "optional",
    "tripId": "optional",
    "offerId": "optional",
    "assignmentId": "optional",
    "conversationSessionId": "optional",
    "messageId": "optional"
  },
  "previousState": "optional",
  "newState": "optional",
  "summary": "human readable summary",
  "payload": {},
  "source": "whatsapp | operator_console | ai_agent | system",
  "correlationId": "optional"
}
```

## Campos Del Evento

| Campo | Descripcion |
| --- | --- |
| `eventId` | Identificador unico conceptual del evento. |
| `eventType` | Nombre tecnico del evento. Debe ser estable para auditoria y metricas. |
| `occurredAt` | Momento en que ocurrio o fue registrado el evento. |
| `actorType` | Tipo de actor que origina el evento. |
| `actorId` | Identificador del actor, si esta disponible. |
| `entityType` | Entidad principal afectada. |
| `entityId` | Identificador de la entidad principal. |
| `relatedEntityIds` | Entidades relacionadas que permiten reconstruir contexto. |
| `previousState` | Estado anterior cuando el evento cambia estado. |
| `newState` | Estado destino cuando el evento cambia estado. |
| `summary` | Descripcion breve para lectura humana. |
| `payload` | Datos relevantes del evento, sin fijar estructura fisica todavia. |
| `source` | Origen operativo o tecnico del evento. |
| `correlationId` | Identificador para agrupar eventos del mismo flujo o interaccion. |

## Tipos De Eventos

### Load

| Evento | Entidad principal | Cuando ocurre |
| --- | --- | --- |
| `LOAD_PREVIEW_PREPARED` | `ConversationSession` | Se preparan campos extraídos para mostrar al productor antes de guardar la carga. Incluye faltantes e indicadores de revisión, sin persistir una `ShipmentRequest`. |
| `LOAD_CREATED` | `LivestockLoad` | Se registra una nueva necesidad de traslado. |
| `LOAD_UPDATED` | `LivestockLoad` | Cambian datos de la carga. |
| `LOAD_INCOMPLETE` | `LivestockLoad` | Se detectan datos criticos faltantes. |
| `LOAD_SELF_PUBLISHED` | `LivestockLoad` | El productor confirma una carga con datos minimos y el backend la publica. |
| `LOAD_VALIDATED` | `LivestockLoad` | Soporte valida datos minimos en un caso excepcional. |
| `LOAD_PUBLISHED` | `LivestockLoad` | La carga queda publicada o enviada a transportistas. |
| `LOAD_MATCHING_STARTED` | `LivestockLoad` | La primera respuesta interesada de transportista inicia matching operativo. |
| `LOAD_REOPENED` | `LivestockLoad` | Una carga vuelve a revision por correccion critica o reproceso. |
| `LOAD_CANCELLED` | `LivestockLoad` | La necesidad se cancela. |
| `LOAD_CLOSED` | `LivestockLoad` | La carga queda cerrada operativamente. |

### Carrier Notification

| Evento | Entidad principal | Cuando ocurre |
| --- | --- | --- |
| `CARRIER_NOTIFIED` | `LivestockLoad` | Un transportista individual recibe la oportunidad. |
| `BROADCAST_SENT` | `LivestockLoad` | Se envia una oportunidad a un conjunto de transportistas. |
| `BROADCAST_EXPANDED` | `LivestockLoad` | El operador amplia la busqueda a mas transportistas. |
| `NO_CARRIER_RESPONSE` | `LivestockLoad` | No se reciben respuestas dentro de la ventana operativa definida. |

### Offer

| Evento | Entidad principal | Cuando ocurre |
| --- | --- | --- |
| `OFFER_RECEIVED` | `Offer` | Se registra una respuesta de transportista. |
| `OFFER_UPDATED` | `Offer` | El transportista agrega o corrige informacion. |
| `OFFER_SHORTLISTED` | `Offer` | El operador marca la oferta como candidata. |
| `OFFER_REJECTED` | `Offer` | El operador descarta la oferta. |
| `OFFER_CANCELLED` | `Offer` | El transportista retira interes o disponibilidad. |
| `OFFER_EXPIRED` | `Offer` | La oferta pierde vigencia operativa. |

### Matching / Assignment

| Evento | Entidad principal | Cuando ocurre |
| --- | --- | --- |
| `MATCH_PROPOSED` | `Assignment` | El sistema, agente AI u operador sugiere una opcion para evaluar. |
| `PRODUCER_OFFER_ACCEPTED` | `Assignment` | El productor acepta una oferta interesada. |
| `MARKETPLACE_MATCH_CONFIRMED` | `Assignment` | Se confirma el match por doble aceptacion. |
| `MATCH_CONFIRMED` | `Assignment` | El match queda confirmado por doble aceptacion o soporte. |
| `ASSIGNMENT_CREATED` | `Assignment` | Se crea una asignacion propuesta o pendiente de confirmacion. |
| `ASSIGNMENT_SELECTED` | `Assignment` | El operador selecciona una oferta para preparar assignment y trip planificado sin confirmar el viaje. |
| `ASSIGNMENT_CONFIRMED` | `Assignment` | La asignacion queda confirmada por productor o soporte. |
| `ASSIGNMENT_CANCELLED` | `Assignment` | La asignacion queda cancelada. |
| `ASSIGNMENT_REPLACED` | `Assignment` | Una asignacion cancelada es reemplazada por otra opcion. |

### Trip

| Evento | Entidad principal | Cuando ocurre |
| --- | --- | --- |
| `TRIP_CREATED` | `Trip` | Se crea un viaje desde una asignacion confirmada o desde una oferta seleccionada manualmente por operador. |
| `TRIP_REMINDER_SENT` | `Trip` | Se envia recordatorio previo. |
| `TRIP_STARTED` | `Trip` | Se registra inicio operativo del viaje. |
| `TRIP_LOADING` | `Trip` | Se registra que la carga esta en proceso. |
| `TRIP_IN_TRANSIT` | `Trip` | Se registra que el viaje esta en transito. |
| `TRIP_COMPLETED` | `Trip` | El operador cierra el viaje como completado. |
| `TRIP_CANCELLED` | `Trip` | El viaje queda cancelado. |
| `TRIP_INCIDENT_REPORTED` | `Trip` | Se reporta una incidencia. |

### Conversation / Message

| Evento | Entidad principal | Cuando ocurre |
| --- | --- | --- |
| `MESSAGE_RECEIVED` | `Message` | Entra un mensaje por WhatsApp u otro canal. |
| `MESSAGE_SENT` | `Message` | Se envia un mensaje desde bot, operador o sistema. |
| `DATA_EXTRACTED` | `Message` | Una skill extrae datos desde un mensaje. |
| `MISSING_DATA_DETECTED` | `LivestockLoad` | Una skill o el operador detecta informacion faltante. |
| `HUMAN_REVIEW_REQUESTED` | `LivestockLoad` | El flujo requiere intervencion del operador. |

### Homologacion y recorrido de transportista

| Evento sugerido | Entidad principal | Cuando ocurre |
| --- | --- | --- |
| `CARRIER_ONBOARDING_STARTED` | `CarrierOnboarding` | El transportista inicia el alta por WhatsApp o soporte. |
| `CARRIER_ONBOARDING_STARTED_FROM_WHATSAPP` | `CarrierOnboarding` | Se inicia la captura progresiva explicita; el payload guarda solo si se creo el perfil, no datos personales. |
| `CARRIER_ONBOARDING_FIELD_CAPTURED` | `CarrierOnboarding` | Se registra el nombre del campo capturado, nunca su valor. |
| `CARRIER_VEHICLE_CAPTURED_FROM_WHATSAPP` / `CARRIER_DRIVER_CAPTURED_FROM_WHATSAPP` | `Vehicle` / `Driver` | Se registra una unidad/conductor declarado y pendiente de revision. |
| `CARRIER_ONBOARDING_DATA_CAPTURED` | `CarrierOnboarding` | Se recibio la licencia esperada y sigue pendiente de revision humana. |
| `CARRIER_ONBOARDING_DRIVER_LICENSE_RECEIVED` | `Driver` | Se recibe licencia de un conductor mientras se continua la captura de la flota. |
| `CARRIER_ONBOARDING_READY_FOR_CONFIRMATION` | `CarrierOnboarding` | El resumen queda listo para confirmacion del transportista, completa o parcialmente. |
| `CARRIER_ONBOARDING_FIELD_CORRECTED` | `CarrierOnboarding` | El transportista corrige un campo; el evento identifica el campo, no conserva su valor. |
| `CARRIER_ONBOARDING_SUBMITTED` | `CarrierOnboarding` | El transportista envia datos para revision. |
| `CARRIER_DOCUMENT_RECEIVED` | `CarrierOnboarding` / `Document` | Se recibe un adjunto documental; no implica validacion. |
| `CARRIER_ONBOARDING_CORRECTION_REQUESTED` | `CarrierOnboarding` | Soporte pide completar o corregir datos/documentos. |
| `CARRIER_ONBOARDING_APPROVED` / `CARRIER_ONBOARDING_REJECTED` | `CarrierOnboarding` | Soporte decide y registra motivo/actor. |
| `ROUTE_AVAILABILITY_CREATED` / `UPDATED` | `CarrierRouteAvailability` | El transportista declara o corrige recorrido/capacidad. |
| `ROUTE_AVAILABILITY_PAUSED` / `CANCELLED` / `EXPIRED` | `CarrierRouteAvailability` | Cambia disponibilidad o vence segun politica acordada. |
| `ROUTE_MATCH_SUGGESTED` | `CarrierRouteAvailability` | Se propone una carga compatible, incluida alternativa de parada/desvio. |
| `PARTIAL_LOAD_ACCEPTED` / `DECLINED` | `CarrierRouteAvailability` | El transportista responde a una sugerencia parcial. |

Registrar eventos tecnicos solo cuando ocurran; estos nombres son propuestas y deben alinearse con enums/codigo antes de implementarse. No poner contenido completo de licencias, mensajes privados ni credenciales en el payload.

## Entidades Que Generan Eventos

| Entidad | Eventos tipicos |
| --- | --- |
| `LivestockLoad` | Creacion, actualizacion, validacion, publicacion, cancelacion y cierre. |
| `Offer` | Recepcion, aclaracion, shortlist, rechazo, vencimiento y cancelacion. |
| `Assignment` | Propuesta, creacion, confirmacion, cancelacion y reemplazo. |
| `Trip` | Creacion, recordatorio, inicio, carga, transito, incidencia, cancelacion y cierre. |
| `ConversationSession` | Inicio, cierre o vinculacion con entidades operativas. |
| `Message` | Recepcion, envio, extraccion de datos y relacion con entidades. |
| `CarrierOnboarding` | Inicio, envio, correcciones solicitadas, adjuntos recibidos y decision de soporte. |
| `CarrierRouteAvailability` | Creacion, cambios, pausa/cancelacion/vencimiento, sugerencias y respuestas a cargas parciales. |
| `CarrierSearchPreference` | Cambios a zonas/criterios de difusion. |

## Uso Para Debugging

El event log debe permitir responder preguntas operativas concretas:

- Que mensaje origino una carga.
- Que datos fueron extraidos y cuales quedaron faltantes.
- Quien publico la carga o si fue autopublicada por confirmacion del productor.
- A que transportistas se notifico.
- Que carrier respondio y que dijo.
- Por que una oferta fue descartada.
- Quien confirmo una asignacion o que doble aceptacion la origino.
- En que momento se cancelo o reporto una incidencia.

Para debugging, los eventos deben incluir `correlationId` cuando varios eventos pertenezcan a la misma conversacion o flujo.

## Uso Para Analytics

Las metricas iniciales deben poder derivarse de eventos:

| Metrica | Eventos base |
| --- | --- |
| Solicitudes recibidas | `MESSAGE_RECEIVED`, `LOAD_PREVIEW_PREPARED`, `LOAD_CREATED` |
| Cargas incompletas | `LOAD_INCOMPLETE`, `MISSING_DATA_DETECTED` |
| Cargas autopublicadas | `LOAD_SELF_PUBLISHED`, `BROADCAST_SENT` |
| Cargas publicadas por soporte | `LOAD_PUBLISHED`, `BROADCAST_SENT` |
| Transportistas notificados por carga | `CARRIER_NOTIFIED`, `BROADCAST_SENT` |
| Ofertas por carga | `OFFER_RECEIVED` |
| Cargas en matching | `LOAD_MATCHING_STARTED` |
| Cargas sin respuesta | `NO_CARRIER_RESPONSE` |
| Tiempo hasta confirmacion | `LOAD_CREATED`, `ASSIGNMENT_CONFIRMED` |
| Viajes completados | `TRIP_COMPLETED` |
| Cancelaciones | `LOAD_CANCELLED`, `OFFER_CANCELLED`, `ASSIGNMENT_CANCELLED`, `TRIP_CANCELLED` |
| Incidencias | `TRIP_INCIDENT_REPORTED` |

Funnel minimo:

```text
MESSAGE_RECEIVED / LOAD_CREATED
-> LOAD_SELF_PUBLISHED
-> OFFER_RECEIVED
-> PRODUCER_OFFER_ACCEPTED
-> ASSIGNMENT_CONFIRMED
-> TRIP_COMPLETED
```

## Uso Para Auditoria

El event log debe permitir reconstruir:

- Quien cambio una entidad.
- Cuando ocurrio el cambio.
- Cual era el estado anterior.
- Cual fue el estado nuevo.
- Que fuente origino el cambio.
- Que mensaje o conversacion dio contexto.
- Que decisiones fueron humanas y cuales fueron sugerencias del sistema o agentes AI.

Las decisiones criticas deben tener actor explicito. En el flujo feliz el actor es `Producer` o `Carrier`; en excepciones puede ser `Operator`.

- Publicar carga por confirmacion del productor.
- Registrar interes o rechazo del carrier.
- Aceptar oferta por productor.
- Confirmar asignacion por doble aceptacion.
- Cancelar o reemplazar asignacion.
- Cerrar viaje.

## Relacion Con Metricas

- Cada metrica debe poder explicarse con una consulta conceptual sobre eventos.
- Los eventos deben conservar suficiente contexto para agrupar por carga, transportista, operador y etapa.
- Cancelaciones e incidencias deben quedar medibles por entidad, actor y momento del flujo.
- Las respuestas ambiguas deben quedar visibles para medir cuanto trabajo manual generan.
- El tiempo entre eventos es la base para medir eficiencia operativa.

## Reglas De Calidad Del Event Log

- No registrar solo el estado final: registrar la transicion.
- No sobrescribir eventos historicos.
- No depender de texto libre cuando exista un `eventType` definido.
- No guardar decisiones criticas sin actor o regla de sistema identificable.
- No tratar eventos de AI Agent como validacion humana.
- No ocultar incertidumbre: faltantes y ambiguedades deben tener eventos propios.

## Riesgos Del Modelo Propuesto

1. Demasiados estados pueden generar carga operativa si soporte debe actualizarlos manualmente.
2. La separacion entre `Offer`, `Assignment` y `Trip` puede sentirse compleja al inicio, aunque evita mezclar interes, decision y ejecucion.
3. Los datos estimados vs confirmados pueden requerir disciplina operativa para no degradarse.
4. Si los eventos no se registran de forma consistente, analytics y auditoria pierden valor.
5. La ambiguedad de ubicaciones rurales puede producir estados incompletos frecuentes.

## Decisiones A Validar Con Negocio

1. Que datos son criticos para publicar una carga y cuales pueden quedar pendientes.
2. Que estados realmente necesita ver soporte en el dia a dia.
3. Cuando una oferta debe considerarse vencida o descartada.
4. Que informacion del productor puede compartirse con transportistas en el broadcast.
5. Que eventos son obligatorios para auditoria operativa desde el primer MVP.

## Siguiente Paso Recomendado

Validar eventos y metricas con operacion real. Luego definir el contrato minimo de datos para backend sin cambiar el alcance marketplace autogestionado del MVP.
