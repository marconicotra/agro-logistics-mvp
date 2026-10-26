# Skills De AGRO Logistics MVP

> **Indice legado:** las definiciones vigentes estan en [`skills/README.md`](skills/README.md) y en los archivos de `skills/`. Este archivo se conserva por compatibilidad con prompts anteriores; no es fuente canonica y no debe ampliarse en paralelo.

Una skill es una capacidad reutilizable que puede ser usada por distintos agentes AI. Debe ser independiente del agente que la invoca, especifica en su objetivo y testeable con entradas y salidas claras.

Las skills no deben tomar decisiones criticas por si mismas. Su funcion es asistir, estructurar informacion y reducir trabajo manual.

## Criterios Para Definir Una Skill

Una skill debe tener:

- Objetivo claro.
- Inputs definidos.
- Outputs definidos.
- Reglas basicas verificables.
- Comportamiento esperado cuando la informacion es incompleta.

## Skill: Extraccion De Datos De Carga

| Campo | Definicion |
| --- | --- |
| Objetivo | Extraer datos operativos desde mensajes de productor o comisionista. |
| Inputs | Texto o audio transcripto recibido por WhatsApp. |
| Outputs | Datos estructurados de carga y lista de campos detectados. |

Reglas basicas:

- Extraer solo informacion presente o claramente inferible del mensaje.
- No inventar origen, destino, fecha, cantidad de animales ni precio.
- Marcar como `pendiente` cualquier dato relevante no informado.
- Preservar el mensaje original como referencia.

Datos esperados cuando existan:

- Origen.
- Destino.
- Fecha o ventana estimada.
- Tipo de hacienda.
- Cantidad aproximada.
- Contacto responsable.
- Observaciones operativas.

## Skill: Deteccion De Datos Faltantes

| Campo | Definicion |
| --- | --- |
| Objetivo | Identificar que informacion falta para que el operador pueda crear o validar una carga. |
| Inputs | Datos estructurados de una carga parcial. |
| Outputs | Lista de datos faltantes y preguntas sugeridas. |

Reglas basicas:

- Diferenciar datos criticos de datos deseables.
- No bloquear una carga por datos deseables si el operador puede avanzar.
- Generar preguntas simples, una por dato faltante critico.
- Escalar al operador si la informacion es contradictoria.

Datos criticos iniciales:

- Origen.
- Destino.
- Fecha o ventana de carga.
- Tipo o categoria de hacienda.
- Cantidad aproximada.
- Contacto responsable.

## Skill: Normalizacion De Ubicacion

| Campo | Definicion |
| --- | --- |
| Objetivo | Convertir ubicaciones escritas de forma informal en referencias mas consistentes para la operacion. |
| Inputs | Texto de ubicacion, contexto de provincia o zona si existe. |
| Outputs | Ubicacion normalizada, nivel de confianza y dudas. |

Reglas basicas:

- Mantener el texto original.
- No reemplazar una ubicacion ambigua sin marcar baja confianza.
- Identificar provincia, localidad, establecimiento o referencia rural cuando sea posible.
- Pedir validacion humana si hay multiples interpretaciones razonables.

## Skill: Generacion De Resumen De Carga

| Campo | Definicion |
| --- | --- |
| Objetivo | Crear un resumen breve y claro de la carga para operador o transportista. |
| Inputs | Datos estructurados de la carga. |
| Outputs | Resumen operativo en lenguaje natural. |

Reglas basicas:

- Mostrar solo informacion validada o marcada como pendiente.
- Usar formato breve, legible en WhatsApp.
- Incluir origen, destino, fecha, hacienda y contacto operativo cuando existan.
- No incluir datos sensibles innecesarios.
- No presentar una carga incompleta como confirmada.

## Skill: Generacion De Alerta A Transportista

| Campo | Definicion |
| --- | --- |
| Objetivo | Generar un mensaje de oportunidad de carga para transportistas. |
| Inputs | Resumen de carga, condiciones conocidas y datos de contacto operativo. |
| Outputs | Mensaje listo para broadcast o envio individual. |

Reglas basicas:

- El mensaje debe ser claro y accionable.
- No prometer asignacion automatica.
- Pedir respuesta simple: disponible, interesado, precio estimado o consulta.
- Indicar que la confirmacion queda sujeta a validacion del operador.
- No compartir informacion privada del productor si no es necesaria.
