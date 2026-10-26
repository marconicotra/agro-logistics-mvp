# Sistema De Agentes

Este directorio define los agentes AI de AGRO Logistics MVP. Los agentes no reemplazan al operador humano: asisten captura, validacion, matching sugerido, comunicacion y auditoria.

## Principios

- Ningun agente confirma por interes unilateral del carrier. La aceptacion explicita del productor habilita `Assignment.CONFIRMED` y `Trip.PLANNED`; soporte resuelve excepciones.
- Ningun agente asigna transportistas automaticamente.
- Ningun agente fija precio final.
- Todo cambio relevante debe terminar en un `EventLog`.
- La aceptacion de una oferta por el productor es la decision comercial del flujo feliz; las excepciones y correcciones quedan en manos del `Operator`.
- Los agentes usan skills atomicas; no deben mezclar logica de canal, dominio y datos.
- WhatsApp es canal operativo mediante `ConversationSession` y `Message`, no dominio.

## Mapa De Agentes

| Agente | Responsabilidad principal | Humano requerido |
| --- | --- | --- |
| `Operations Dispatcher Agent` | Asistir al operador en validacion, coordinacion y decisiones operativas. | En datos faltantes, ambiguedades, cancelaciones y excepciones; no es paso obligatorio del match feliz. |
| `Producer Conversation Agent` | Conversar con productor y capturar datos de carga incompletos. | Cuando faltan datos criticos, hay ambiguedad o cambio sensible. |
| `Carrier Conversation Agent` | Guiar respuestas, busquedas por ruta, disponibilidades declaradas y alta documental de transportistas. | Aprobacion de homologacion, ambiguedad, precio sensible, excepciones y cambios criticos. |
| `Matching Agent` | Sugerir compatibilidad entre cargas, carriers y recorridos disponibles. | El productor acepta una oferta en el flujo feliz; soporte decide excepciones. |
| `Pricing Agent` | Estimar rango de precio orientativo. | Siempre para precio final. |
| `Data Quality Agent` | Detectar baja confianza, faltantes y transiciones dudosas. | Cuando hay flags criticos o estados invalidos. |
| `Admin Ops Agent` | Asistir excepciones, cancelaciones, reprocesos y errores. | Siempre para resolucion final. |

## Mapa Agent -> Skill

| Agente | Skills principales |
| --- | --- |
| `Operations Dispatcher Agent` | `Detect Missing Fields`, `Summarize Load`, `Rank Carriers`, `Estimate Price Range`, `Detect Risk`, `Validate State Transition`, `Create Event Log` |
| `Producer Conversation Agent` | `Extract Load Data`, `Detect Missing Fields`, `Normalize Location`, `Summarize Load`, `Create Event Log` |
| `Carrier Conversation Agent` | `Generate Carrier Alert`, `Extract Load Data`, `Detect Risk`, `Validate State Transition`, `Create Event Log` |
| `Matching Agent` | `Rank Carriers`, `Detect Risk`, `Estimate Price Range`, `Create Event Log` |
| `Pricing Agent` | `Estimate Price Range`, `Detect Risk`, `Create Event Log` |
| `Data Quality Agent` | `Detect Missing Fields`, `Normalize Location`, `Detect Risk`, `Validate State Transition`, `Create Event Log` |
| `Admin Ops Agent` | `Detect Risk`, `Validate State Transition`, `Summarize Load`, `Create Event Log` |

## Flujo De Interaccion

```text
Producer Conversation Agent
-> Extract Load Data
-> Normalize Location
-> Detect Missing Fields
-> Summarize Load
-> Data Quality Agent
-> Operations Dispatcher Agent
-> Generate Carrier Alert
-> Carrier Conversation Agent
-> Offer registrado
-> Matching Agent
-> Rank Carriers / Detect Risk / Estimate Price Range
-> Producer elige una oferta interesada
-> Backend confirma match, Assignment y Trip planificado
-> Create Event Log en cada cambio relevante
```

Flujos adicionales planificados para transportistas: solicitud de homologacion revisada por soporte; declaracion de `CarrierRouteAvailability`; busqueda por ruta; respuesta a sugerencias directas/parciales. Ninguno de estos flujos permite al agente aprobar documentos, confirmar un assignment o crear un `Trip` sin la decision de dominio correspondiente.

## Relacion Con Dominio

| Dominio | Como lo usan los agentes |
| --- | --- |
| `LivestockLoad` | Capturan, completan, validan, publican y reabren cargas, siempre bajo reglas de estado. |
| `Offer` | Clasifican respuestas de carriers como interes, precio, no disponibilidad o duda. |
| `Assignment` | El backend confirma tras aceptacion explicita del productor; soporte atiende excepciones. |
| `Trip` | El backend crea el viaje `PLANNED` tras el match; el avance, cancelacion o cierre conserva trazabilidad y soporte cuando corresponde. |
| `ConversationSession` | Mantienen contexto de conversacion por canal. |
| `Message` | Preservan contenido original y trazan extracciones. |
| `EventLog` | Registran cada accion relevante, sugerencia, cambio de estado o excepcion. |

## Reglas De Seguridad Operativa

- Si faltan datos criticos, marcar `missingCriticalFields` y pedir revision.
- Si una ubicacion es ambigua, marcar `hasAmbiguousLocation`.
- Si el agente no puede justificar una sugerencia con datos, debe decirlo.
- Si una accion cambia estado, usar `Validate State Transition` antes de proponerla.
- Si ocurre cancelacion, no resolver automaticamente: escalar a operador.
- Si nadie responde, registrar `NO_CARRIER_RESPONSE` y sugerir ampliar busqueda.

## Riesgos Del Diseno De Agentes

1. Los agentes pueden parecer mas seguros que los datos disponibles.
2. El operador puede delegar decisiones criticas por costumbre si la interfaz no marca limites.
3. Respuestas cortas de WhatsApp pueden clasificarse mal sin contexto.
4. Demasiados agentes pueden fragmentar responsabilidad operativa.
5. Event logs incompletos reducen auditabilidad y aprendizaje.

## Mejoras Futuras Posibles

1. Aprender preferencias por productor y carrier usando historial validado.
2. Mejorar ranking con cumplimiento historico e incidencias.
3. Incorporar plantillas de conversacion por zona o tipo de hacienda.
4. Detectar riesgo de cancelacion con senales historicas.
5. Generar reportes operativos semanales basados en eventos.

## Siguiente Paso Recomendado

Validar estos agentes y skills con un flujo real de carga incompleta, broadcast, oferta ambigua, cancelacion y reemplazo. Luego definir contratos de datos minimos para implementacion.
