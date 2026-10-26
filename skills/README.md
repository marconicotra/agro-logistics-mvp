# Sistema De Skills

Las skills son capacidades atomicas, reutilizables, testeables e independientes del agente que las invoca.

Una skill no debe tomar decisiones criticas. Debe recibir inputs claros, producir outputs claros y declarar incertidumbre cuando no alcanza la informacion.

## Principios

- Una skill hace una sola cosa.
- Una skill puede ser usada por varios agentes.
- Una skill no reemplaza al operador humano.
- Una skill no debe inventar datos faltantes.
- Una skill debe conservar trazabilidad hacia mensajes y entidades.
- Una skill que detecta riesgo o inconsistencia debe pedir intervencion humana.

## Catalogo De Skills

| Skill | Objetivo |
| --- | --- |
| `Extract Load Data` | Extraer datos de carga desde mensajes. |
| `Detect Missing Fields` | Detectar datos criticos faltantes. |
| `Normalize Location` | Normalizar ubicaciones informales sin ocultar ambiguedad. |
| `Summarize Load` | Generar resumen operativo de una carga. |
| `Generate Carrier Alert` | Crear mensaje de oportunidad para carriers. |
| `Rank Carriers` | Ordenar carriers u ofertas por compatibilidad. |
| `Estimate Price Range` | Calcular rango orientativo, no precio final. |
| `Detect Risk` | Detectar riesgos operativos o de datos. |
| `Validate State Transition` | Validar transiciones contra maquinas de estado. |
| `Create Event Log` | Preparar eventos auditables. |

## Relacion Con Dominio

| Dominio | Skills relacionadas |
| --- | --- |
| `LivestockLoad` | `Extract Load Data`, `Detect Missing Fields`, `Normalize Location`, `Summarize Load`, `Detect Risk`, `Validate State Transition`, `Create Event Log` |
| `Offer` | `Generate Carrier Alert`, `Rank Carriers`, `Estimate Price Range`, `Detect Risk`, `Validate State Transition`, `Create Event Log` |
| `Assignment` | `Rank Carriers`, `Estimate Price Range`, `Detect Risk`, `Validate State Transition`, `Create Event Log` |
| `Trip` | `Detect Risk`, `Validate State Transition`, `Create Event Log` |
| `Message` | `Extract Load Data`, `Normalize Location`, `Create Event Log` |
| `EventLog` | `Create Event Log` |

## Flujo Tipico

```text
Mensaje productor
-> Extract Load Data
-> Normalize Location
-> Detect Missing Fields
-> Summarize Load
-> Create Event Log
-> Revision operador
-> Generate Carrier Alert
-> Respuesta carrier
-> Rank Carriers / Estimate Price Range / Detect Risk
-> Validate State Transition
-> Create Event Log
```

## Siguiente Paso Recomendado

Convertir cada skill en contrato de entrada/salida para pruebas con ejemplos reales de WhatsApp antes de implementar codigo.

