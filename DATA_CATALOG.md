# Data Catalog Inicial

Este catalogo define los datos principales del MVP. Es conceptual y debe evolucionar junto con el dominio.

Sensibilidad permitida:

- `publica`
- `interna`
- `personal`
- `ubicacion`
- `sensible_operativa`

## Catalogo

| Tabla | Campo | Descripcion negocio | Tipo sugerido | Fuente | Owner | Sensibilidad | Uso analitico |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `users` | `id` | Identidad interna del usuario. | uuid | Backend | Backend | interna | Conteo usuarios por rol. |
| `users` | `display_name` | Nombre visible. | text | Operador/WhatsApp | Backend | personal | Segmentacion operacional. |
| `users` | `phone_number` | Telefono de contacto. | text | WhatsApp/KAPSO | Backend | personal | Resolucion de identidad. |
| `users` | `role` | Rol operativo. | enum | Backend | Backend | interna | Actividad por rol. |
| `producers` | `id` | Identidad del productor/comisionista. | uuid | Backend | Backend | interna | Productores activos. |
| `producers` | `name` | Nombre operativo. | text | Operador | Backend | personal | Demand recurrente. |
| `producers` | `contact_phone` | Telefono operativo. | text | WhatsApp/Operador | Backend | personal | Contactabilidad. |
| `producers` | `usual_location_id` | Zona frecuente. | uuid | Operador/AI | Backend | ubicacion | Cargas por zona. |
| `carriers` | `id` | Identidad del transportista. | uuid | Backend | Backend | interna | Supply activo. |
| `carriers` | `name` | Nombre del carrier. | text | Operador | Backend | personal | Respuesta por carrier. |
| `carriers` | `contact_phone` | Telefono de carrier. | text | WhatsApp/Operador | Backend | personal | Notificaciones. |
| `carriers` | `service_zone` | Zona declarada de operacion. | text | Operador/Carrier | Backend | ubicacion | Zonas cubiertas. |
| `carriers` | `tax_id` | CUIT declarado para homologacion. | text | Carrier/Operador | Backend | sensible_operativa | Estado de homologacion. |
| `carriers` | `email` | Email de contacto. | text | Carrier/Operador | Backend | personal | Contactabilidad de soporte. |
| `vehicles` | `id` | Identidad de unidad. | uuid | Backend | Backend | interna | Capacidad supply. |
| `vehicles` | `carrier_id` | Carrier propietario u operador. | uuid | Backend | Backend | interna | Vehiculos por carrier. |
| `vehicles` | `capacity_estimate` | Capacidad aproximada. | numeric | Carrier/Operador | Backend | sensible_operativa | Compatibilidad. |
| `vehicles` | `status` | Disponibilidad conocida. | enum | Carrier/Operador | Backend | interna | Supply disponible. |
| `vehicles` | `plate` | Patente declarada de unidad. | text | Carrier/Operador | Backend | sensible_operativa | Identificacion/revision de vehiculo. |
| `vehicles` | `vehicle_type` | Tipo de camion/configuracion. | enum/text | Carrier/Operador | Backend | sensible_operativa | Compatibilidad de transporte. |
| `vehicles` | `body_type` | Carroceria o configuracion de carga. | enum/text | Carrier/Operador | Backend | sensible_operativa | Compatibilidad de transporte. |
| `carrier_search_preferences` | `service_area` | Zona/corredor donde desea recibir oportunidades. | reference | Carrier | Backend | ubicacion | Difusion por preferencia, no disponibilidad fechada. |
| `carrier_route_availabilities` | `route_window` | Ruta y ventana declaradas por el carrier. | structured | Carrier | Backend | ubicacion | Busqueda de oportunidades por ruta. |
| `carrier_route_availabilities` | `free_capacity` | Capacidad disponible declarada y unidad. | numeric + enum | Carrier/Operador | Backend | sensible_operativa | Compatibilidad/capacidad residual. |
| `carrier_route_availabilities` | `detour_limits` | Desvio/paradas que acepta considerar. | structured | Carrier | Backend | ubicacion | Sugerencias de cargas parciales. |
| `locations` | `id` | Identidad de ubicacion. | uuid | Backend | Backend | ubicacion | Dim location futura. |
| `locations` | `original_text` | Texto original de ubicacion. | text | Message | Backend | ubicacion | Calidad de normalizacion. |
| `locations` | `normalized_name` | Nombre normalizado candidato. | text | AI/Operador | Backend | ubicacion | Cargas por zona. |
| `locations` | `confidence` | Confianza de normalizacion. | enum | AI/Operador | Backend | interna | Calidad de datos. |
| `shipment_requests` | `id` | Necesidad de transporte (`LivestockLoad`). | uuid | Backend | Backend | interna | Funnel de cargas. |
| `shipment_requests` | `producer_id` | Productor que solicita. | uuid | Backend | Backend | personal | Demand por productor. |
| `shipment_requests` | `origin_location_id` | Origen de carga. | uuid | AI/Operador | Backend | ubicacion | Cargas por origen. |
| `shipment_requests` | `destination_location_id` | Destino. | uuid | AI/Operador | Backend | ubicacion | Cargas por destino. |
| `shipment_requests` | `date_window_start` | Inicio ventana operativa. | timestamp | Usuario/Operador | Backend | interna | Planificacion. |
| `shipment_requests` | `livestock_type` | Categoria de hacienda. | text | Usuario/AI | Backend | interna | Cargas por categoria. |
| `shipment_requests` | `quantity_estimate` | Cantidad aproximada. | numeric | Usuario/AI | Backend | sensible_operativa | Demanda y pricing estimado. |
| `shipment_requests` | `status` | Estado de carga. | enum | Domain Services | Backend | interna | Funnel operativo. |
| `shipment_requests` | `missing_critical_fields` | Faltantes criticos. | json | AI/Data Quality | Backend | interna | Completeness. |
| `shipment_requests` | `requires_human_review` | Requiere operador. | boolean | AI/Backend | Backend | interna | Handoff rate. |
| `trip_offers` | `id` | Oferta/interes de carrier (`Offer`). | uuid | Backend | Backend | interna | Ofertas por carga. |
| `trip_offers` | `shipment_request_id` | Carga asociada. | uuid | Backend | Backend | interna | Matching funnel. |
| `trip_offers` | `carrier_id` | Carrier que responde. | uuid | Backend | Backend | personal | Response rate. |
| `trip_offers` | `response_type` | Tipo de respuesta. | enum | AI/Operador | Backend | interna | Tasa de respuesta. |
| `trip_offers` | `price_estimate` | Precio informado estimado. | numeric | Carrier | Backend | sensible_operativa | Monetizacion estimada. |
| `trip_offers` | `status` | Estado de oferta. | enum | Domain Services | Backend | interna | Tasa de aceptacion. |
| `assignments` | `id` | Asignacion operativa. | uuid | Backend | Backend | interna | Match confirmado. |
| `assignments` | `shipment_request_id` | Carga asignada. | uuid | Backend | Backend | interna | Match rate. |
| `assignments` | `carrier_id` | Carrier elegido. | uuid | Operador | Backend | personal | Carrier performance. |
| `assignments` | `status` | Estado de asignacion. | enum | Domain Services | Backend | interna | Confirmaciones/cancelaciones. |
| `assignments` | `confirmed_by_user_id` | Operador que confirma. | uuid | Operador | Backend | interna | Auditoria. |
| `trips` | `id` | Ejecucion logistica. | uuid | Backend | Backend | interna | Viajes confirmados. |
| `trips` | `assignment_id` | Assignment origen. | uuid | Backend | Backend | interna | Lineage de viaje. |
| `trips` | `status` | Estado de viaje. | enum | Domain Services | Backend | interna | Viajes completados/cancelados. |
| `trips` | `started_at` | Inicio operativo. | timestamp | Operador/Carrier | Backend | interna | Lead time operativo. |
| `trips` | `completed_at` | Cierre operativo. | timestamp | Operador | Backend | interna | Completion rate. |
| `conversation_sessions` | `id` | Conversacion backend. | uuid | Backend | Backend | interna | Volumen conversacional. |
| `conversation_sessions` | `channel` | Canal usado. | enum | KAPSO/Provider | Backend | interna | Mix de canal. |
| `conversation_sessions` | `external_conversation_id` | ID externo KAPSO/provider. | text | KAPSO | Backend | interna | Debugging canal. |
| `messages` | `id` | Mensaje backend. | uuid | Backend | Backend | interna | Volumen mensajes. |
| `messages` | `provider_message_id` | ID externo del mensaje. | text | KAPSO/WhatsApp | Backend | interna | Idempotencia/debugging. |
| `messages` | `raw_content` | Contenido original. | text | WhatsApp/KAPSO | Backend | sensible_operativa | Auditoria/extraccion. |
| `messages` | `direction` | Entrante o saliente. | enum | Backend | Backend | interna | Tiempos de respuesta. |
| `event_logs` | `id` | Evento auditable. | uuid | Backend | Backend | interna | Fuente de metricas. |
| `event_logs` | `event_type` | Tipo de evento. | text | Backend | Backend | interna | KPIs/funnel. |
| `event_logs` | `occurred_at` | Momento del evento. | timestamp | Backend/Provider | Backend | interna | Tiempos entre etapas. |
| `event_logs` | `actor_type` | Actor que origina. | enum | Backend | Backend | interna | Auditoria. |
| `event_logs` | `entity_type` | Entidad afectada. | text | Backend | Backend | interna | Lineage. |
| `event_logs` | `correlation_id` | Correlacion del flujo. | text | Backend | Backend | interna | Reconstruccion. |
| `payment_terms` | `amount_estimate` | Tarifa estimada. | numeric | Carrier/Operador | Backend | sensible_operativa | Revenue estimado. |
| `payment_terms` | `commission_estimate` | Comision estimada. | numeric | Operador | Backend | sensible_operativa | Monetizacion. |
| `risk_flags` | `risk_type` | Tipo de riesgo. | text | AI/Operador | Backend | interna | Calidad/riesgo. |
| `risk_flags` | `severity` | Severidad. | enum | AI/Operador | Backend | interna | Priorizacion operativa. |

## Glosario De Negocio

| Termino | Definicion |
| --- | --- |
| Carga | Necesidad de transportar hacienda o granos; en datos `shipment_requests`, dominio `LivestockLoad`. |
| Viaje | Ejecucion logistica confirmada; en datos `trips`, dominio `Trip`. |
| Oferta | Respuesta/interes del transportista; en datos `trip_offers`, dominio `Offer`. |
| Asignacion | Decision validada por operador de elegir carrier/vehicle; en datos `assignments`. |
| Transportista | Actor que ofrece disponibilidad de camion; `carrier`. |
| Productor | Actor que origina la necesidad de transporte; incluye comisionista en MVP. |
| Estado | Valor controlado por maquina de estados del dominio. |
| Evento | Registro auditable de algo ocurrido; `event_logs`. |
| Idempotencia | Garantia de no procesar dos veces el mismo evento externo. |
| Correlacion | Agrupacion de eventos y mensajes de un mismo flujo operativo. |
