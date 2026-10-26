# Estrategia Analitica MVP

Este documento define la estrategia analitica inicial de AGRO Logistics MVP. No disena warehouse fisico ni implementa dbt, pero deja preparada la separacion entre operacion, auditoria y analytics.

## Principios

- Analytics deriva de backend y `event_logs`, no de KAPSO.
- Dashboards no son fuente de verdad.
- Metricas deben poder auditarse hasta evento y entidad.
- Monetizacion inicial es estimada, no contable.
- La calidad de datos es un dashboard de producto, no una tarea secundaria.

## Eventos Minimos Para Analytics

- `MESSAGE_RECEIVED`
- `MESSAGE_SENT`
- `DATA_EXTRACTED`
- `MISSING_DATA_DETECTED`
- `HUMAN_REVIEW_REQUESTED`
- `LOAD_CREATED`
- `LOAD_UPDATED`
- `LOAD_INCOMPLETE`
- `LOAD_VALIDATED`
- `LOAD_PUBLISHED`
- `CARRIER_NOTIFIED`
- `BROADCAST_SENT`
- `NO_CARRIER_RESPONSE`
- `OFFER_RECEIVED`
- `OFFER_UPDATED`
- `OFFER_SHORTLISTED`
- `ASSIGNMENT_CREATED`
- `ASSIGNMENT_CONFIRMED`
- `ASSIGNMENT_CANCELLED`
- `TRIP_CREATED`
- `TRIP_COMPLETED`
- `TRIP_CANCELLED`
- `TRIP_INCIDENT_REPORTED`

## Dashboard Operativo

| Bloque | Pregunta | Fuentes |
| --- | --- | --- |
| Cargas abiertas | Que cargas requieren accion. | `shipment_requests`, `event_logs` |
| Cargas con datos faltantes | Que cargas no pueden avanzar. | `shipment_requests`, `risk_flags` |
| Viajes en riesgo | Que viajes tienen incidencia o riesgo. | `trips`, `risk_flags`, `event_logs` |
| Viajes confirmados | Que viajes estan planificados. | `assignments`, `trips` |
| Cancelaciones | Que se cancelo y por que. | `event_logs`, `trips`, `assignments` |

## Dashboard Supply

| Bloque | Pregunta | Fuentes |
| --- | --- | --- |
| Transportistas activos | Quienes responden o ejecutan viajes. | `carriers`, `trip_offers`, `trips` |
| Tasa de respuesta | Quienes responden a notificaciones. | `event_logs`, `trip_offers` |
| Zonas cubiertas | Donde hay supply activo. | `carriers`, `locations`, `event_logs` |
| Cancelaciones | Que carriers cancelan y en que etapa. | `event_logs`, `assignments`, `trips` |

## Dashboard Demand

| Bloque | Pregunta | Fuentes |
| --- | --- | --- |
| Productores activos | Quienes generan cargas. | `producers`, `shipment_requests` |
| Cargas por zona | Donde se origina demanda. | `shipment_requests`, `locations` |
| Recurrencia | Que productores repiten. | `shipment_requests` |
| Categorias mas transportadas | Que hacienda mueve el MVP. | `shipment_requests` |

## Dashboard Matching

| Bloque | Pregunta | Fuentes |
| --- | --- | --- |
| Cargas sin interesados | Donde falla supply. | `event_logs`, `trip_offers` |
| Tiempo hasta primer interesado | Velocidad de respuesta. | `event_logs` |
| Ofertas por carga | Profundidad de opciones. | `trip_offers` |
| Tasa de match | Cargas publicadas que logran assignment. | `event_logs`, `assignments` |

## Dashboard Monetizacion

| Bloque | Pregunta | Fuentes |
| --- | --- | --- |
| Comision estimada | Potencial de ingreso. | `payment_terms`, `trips` |
| Revenue estimado | Ingreso esperado no contable. | `payment_terms`, `trips` |
| Tarifa pactada | Valor operativo acordado o estimado. | `payment_terms`, `assignments` |

Advertencia: estas metricas no son confiables como finanzas formales al inicio.

## Dashboard Calidad

| Bloque | Pregunta | Fuentes |
| --- | --- | --- |
| Data completeness | Que porcentaje de cargas tiene datos minimos. | `shipment_requests` |
| AI extraction errors | Donde falla extraccion. | `event_logs`, `messages` |
| Handoff humano | Que casos requieren operador. | `event_logs`, `risk_flags` |
| Mensajes ambiguos | Que canal genera incertidumbre. | `messages`, `risk_flags` |

## Metricas Que NO Son Confiables Al Inicio

- Revenue real cobrado.
- Precio de mercado definitivo.
- Disponibilidad real de carriers que no respondieron.
- Cobertura geografica exacta.
- Capacidad real de vehiculos.
- Motivos de cancelacion si no se capturan consistentemente.
- Performance AI si las correcciones no se registran.

## Recomendaciones Para Futuro dbt

- Crear staging por tabla transaccional.
- Crear facts desde `event_logs`, no desde estados finales solamente.
- Definir tests de unicidad para ids e idempotency keys.
- Definir accepted values para estados y tipos de evento.
- Separar modelos operativos de modelos analiticos.
- Versionar definiciones de metricas con owners.

## Futuras Tablas Fact/Dim

| Modelo futuro | Tipo | Fuente |
| --- | --- | --- |
| `fct_shipment_funnel` | fact | `event_logs`, `shipment_requests` |
| `fct_carrier_response` | fact | `event_logs`, `trip_offers` |
| `fct_trip_operations` | fact | `trips`, `assignments`, `event_logs` |
| `fct_data_quality` | fact | `risk_flags`, `event_logs`, `messages` |
| `fct_estimated_revenue` | fact | `payment_terms`, `trips` |
| `dim_producer` | dim | `producers`, `users` |
| `dim_carrier` | dim | `carriers`, `vehicles` |
| `dim_location` | dim | `locations` |
| `dim_date` | dim | timestamps operativos |

## Estrategia MVP De Implementacion Analitica

1. Medir primero con tablas backend y `event_logs`.
2. Crear reportes simples para operador.
3. Revisar calidad de eventos semanalmente.
4. Evitar optimizar dashboards antes de estabilizar flujo operativo.
5. Preparar dbt/warehouse cuando el volumen o la complejidad lo justifique.

## Riesgos Del Modelo Analitico

1. Dashboards pueden dar falsa precision con datos incompletos.
2. Metricas economicas pueden confundirse con ingresos reales.
3. Sin eventos obligatorios, los funnels quedan incompletos.
4. Ubicaciones ambiguas distorsionan mapas de supply/demand.
5. Correcciones manuales no auditadas rompen confianza.

## Decisiones Pendientes Con Negocio

1. Umbral para considerar carga en riesgo.
2. Ventana para medir sin interesados.
3. Politica de revenue/comision estimada.
4. Zonas operativas canonicas.
5. Cadencia de revision de calidad de datos.

## Proximo Paso Recomendado

Definir un set de eventos obligatorios para operar los primeros dashboards. Luego probar metricas con operaciones reales antes de automatizar reporting.
