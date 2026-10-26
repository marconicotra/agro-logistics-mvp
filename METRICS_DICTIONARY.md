# Metrics Dictionary MVP

Todas las metricas deben derivarse de tablas backend y, cuando sea posible, de `event_logs`. Las metricas economicas son estimadas y no representan pagos dentro de la app.

## Operacion

| Metrica | Definicion | Formula | Granularidad | Fuente | Owner | Advertencias |
| --- | --- | --- | --- | --- | --- | --- |
| Cargas creadas | Nuevas necesidades registradas. | count `LOAD_CREATED` o `shipment_requests.created_at` | dia, zona, productor | `event_logs`, `shipment_requests` | Ops | Duplicados afectan si falla idempotencia. |
| Cargas validadas | Cargas revisadas por operador. | count `LOAD_VALIDATED` | dia, operador | `event_logs` | Ops | Solo confiable si validacion genera evento. |
| Cargas publicadas | Cargas enviadas a carriers. | count `LOAD_PUBLISHED` | dia, zona | `event_logs` | Ops | No equivale a match. |
| Cargas con datos faltantes | Cargas con faltantes criticos. | count `LOAD_INCOMPLETE` o `missing_critical_fields` no vacio | dia, campo | `event_logs`, `shipment_requests` | Data | JSON puede requerir normalizacion futura. |
| Cargas con intervencion humana | Cargas con handoff/revision. | count distinct load con `HUMAN_REVIEW_REQUESTED` | dia, motivo | `event_logs`, `risk_flags` | Ops | Requiere disciplina de eventos. |
| Tiempo de validacion | Tiempo entre creacion y validacion. | `LOAD_VALIDATED.occurred_at - LOAD_CREATED.occurred_at` | carga, dia | `event_logs` | Ops | Outliers por datos incompletos. |
| Tiempo hasta primer interesado | Tiempo hasta primera oferta. | first `OFFER_RECEIVED` - `LOAD_PUBLISHED` | carga, zona | `event_logs` | Ops | Si se registra oferta manual tarde, distorsiona. |
| Viajes confirmados | Assignments confirmados con trip creado. | count `ASSIGNMENT_CONFIRMED` o `TRIP_CREATED` | dia, carrier | `event_logs`, `trips` | Ops | Confirmado no significa completado. |
| Viajes completados | Viajes cerrados como completados. | count `TRIP_COMPLETED` | dia, carrier | `event_logs`, `trips` | Ops | Depende del cierre por operador. |
| Viajes cancelados | Viajes cancelados. | count `TRIP_CANCELLED` | dia, carrier, motivo | `event_logs`, `trips` | Ops | Motivo puede faltar. |

## Supply

| Metrica | Definicion | Formula | Granularidad | Fuente | Owner | Advertencias |
| --- | --- | --- | --- | --- | --- | --- |
| Transportistas activos | Carriers con respuesta o viaje en periodo. | count distinct carrier con `OFFER_RECEIVED` o `TRIP_CREATED` | semana, zona | `event_logs`, `trip_offers`, `trips` | Supply | No mide disponibilidad real total. |
| Transportistas notificados | Carriers contactados por carga. | count `CARRIER_NOTIFIED` | carga, dia | `event_logs` | Supply | Broadcast agregado puede ocultar individuo si no se registra. |
| Tasa de respuesta | Proporcion de notificados que responden. | carriers con `OFFER_RECEIVED` / carriers con `CARRIER_NOTIFIED` | carga, zona | `event_logs` | Supply | Requiere notificacion individual. |
| Tasa de aceptacion | Ofertas que avanzan a assignment confirmado. | assignments confirmados / offers recibidas | periodo, carrier | `trip_offers`, `assignments` | Supply | No todas las offers son equivalentes. |
| Tasa de cancelacion por transportista | Cancelaciones asociadas a carrier. | carrier cancellations / assignments confirmados | carrier, mes | `event_logs`, `assignments` | Supply | Distinguir causa real con operador. |
| Zonas cubiertas | Zonas con carriers activos o notificados. | count distinct service_zone/location | semana | `carriers`, `event_logs` | Supply | Zona declarada puede ser imprecisa. |
| Disponibilidades activas | Recorridos declarados aun vigentes. | count `CarrierRouteAvailability` ACTIVE | semana, corredor | `carrier_route_availabilities` | Supply | No equivale a vehiculos homologados o capacidad reservada. |
| Sugerencias parciales aceptadas | Alternativas de carga cercana aceptadas por carrier. | accepted partial suggestions / partial suggestions sent | corredor, periodo | `event_logs`, route availability | Supply | Medir solo cuando se defina el evento y la aceptacion. |

## Demand

| Metrica | Definicion | Formula | Granularidad | Fuente | Owner | Advertencias |
| --- | --- | --- | --- | --- | --- | --- |
| Productores activos | Productores con carga creada. | count distinct producer con `LOAD_CREATED` | semana, zona | `shipment_requests`, `event_logs` | Demand | Productor/comisionista puede duplicarse por telefono. |
| Productores recurrentes | Productores con mas de una carga en periodo. | count producers con cargas > 1 | mes | `shipment_requests` | Demand | Requiere identidad consolidada. |
| Cargas por zona | Cargas por origen/destino. | count shipment_requests group by location | dia, zona | `shipment_requests`, `locations` | Demand | Baja confianza de location afecta. |
| Cargas por categoria de hacienda | Demanda por tipo. | count group by `livestock_type` | semana | `shipment_requests` | Demand | Texto libre requiere normalizacion futura. |

## Matching

| Metrica | Definicion | Formula | Granularidad | Fuente | Owner | Advertencias |
| --- | --- | --- | --- | --- | --- | --- |
| Ofertas por carga | Cantidad de offers por carga. | count trip_offers / shipment_request | carga, zona | `trip_offers` | Ops | Incluye consultas y no disponibles si no se filtra. |
| Cargas sin interesados | Cargas publicadas sin offer. | count `NO_CARRIER_RESPONSE` o published sin offers | dia, zona | `event_logs`, `trip_offers` | Ops | Requiere ventana de espera definida. |
| Tasa de match | Cargas publicadas con assignment confirmado. | assignments confirmados / cargas publicadas | semana, zona | `event_logs`, `assignments` | Ops | Puede estar sesgada por cargas canceladas. |
| Tiempo hasta match | Tiempo de publicacion a confirmacion. | `ASSIGNMENT_CONFIRMED` - `LOAD_PUBLISHED` | carga, dia | `event_logs` | Ops | Depende de eventos completos. |
| Tasa de fallback manual | Casos con intervencion humana por matching. | cargas con handoff matching / cargas publicadas | semana | `event_logs`, `risk_flags` | Ops | Requiere clasificar motivo de handoff. |

## Monetizacion

| Metrica | Definicion | Formula | Granularidad | Fuente | Owner | Advertencias |
| --- | --- | --- | --- | --- | --- | --- |
| Tarifa pactada estimada | Monto acordado o estimado para viaje. | sum agreed_amount o amount_estimate | viaje, mes | `payment_terms` | Finance/Ops | No representa pago cobrado. |
| Comision estimada | Comision esperada. | sum `commission_estimate` | viaje, mes | `payment_terms` | Finance/Ops | Requiere politica comercial validada. |
| Revenue estimado | Ingreso estimado por viajes comisionables. | sum commission_estimate de trips completados | mes | `payment_terms`, `trips` | Finance/Ops | No es revenue contable. |
| Viajes comisionables | Viajes con condiciones economicas. | count trips completed con payment_terms | mes | `trips`, `payment_terms` | Finance/Ops | Puede faltar data economica. |

## Calidad De Datos

| Metrica | Definicion | Formula | Granularidad | Fuente | Owner | Advertencias |
| --- | --- | --- | --- | --- | --- | --- |
| Campos faltantes por carga | Cantidad de faltantes criticos. | count campos en `missing_critical_fields` | carga, campo | `shipment_requests` | Data | Mejor normalizar si crece. |
| Mensajes ambiguos | Mensajes marcados ambiguos. | count risk/message ambiguity | dia, canal | `risk_flags`, `messages`, `event_logs` | Data | Depende de clasificacion AI/operador. |
| Cargas con baja confianza | Cargas con confidence baja o flags. | count shipment_requests con low confidence | dia, zona | `shipment_requests`, `risk_flags` | Data | Umbrales deben validarse. |
| Errores de extraccion AI | Extracciones fallidas o corregidas. | count `DATA_EXTRACTED` con error/correccion | dia, skill | `event_logs` | Data/AI | Requiere payload consistente. |

## Riesgos Del Modelo De Metricas

1. Eventos faltantes rompen calculos de tiempo.
2. Identidades duplicadas distorsionan productores/carriers activos.
3. Revenue estimado puede confundirse con contabilidad.
4. Ubicaciones sin normalizar afectan zonas.
5. Mensajes ambiguos dependen de criterios de clasificacion.

## Decisiones Pendientes Con Negocio

1. Definir ventana para considerar "sin interesados".
2. Definir politica de comision estimada.
3. Definir categorias de hacienda normalizadas.
4. Definir zona operacional canonica.
5. Definir eventos obligatorios para cada KPI.

## Proximo Paso Recomendado

Validar metricas con 10 operaciones reales o simuladas y marcar cuales son confiables desde MVP dia 1.
