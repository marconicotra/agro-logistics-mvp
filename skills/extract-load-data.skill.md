# Extract Load Data

## Nombre

`Extract Load Data`

## Objetivo

Extraer datos de una necesidad de transporte desde mensajes de productor, comisionista o transportista, preservando incertidumbre y fuente.

## Inputs

- `Message.rawContent`
- `ConversationSession`
- Contexto previo de `LivestockLoad`, si existe.
- Actor esperado: `Producer`, `Carrier`, `Operator` o `Bot`.

## Outputs

- Campos candidatos para `LivestockLoad`.
- `sourceMessageId`.
- Nivel de confianza por campo.
- Campos no encontrados.
- Texto original preservado.

## Reglas

- Extraer solo informacion presente o claramente inferible.
- No inventar origen, destino, fecha, cantidad, tipo de hacienda/grano, unidad ni precio.
- Marcar cada campo como `unknown`, `estimated`, `provided`, `validated` o `corrected`.
- Si hay contradiccion con datos existentes, marcar `requiresHumanReview`.
- Si el mensaje es respuesta de carrier, extraer solo datos relevantes para `Offer`.

## Casos Borde

- Audio transcripto con frases incompletas.
- Ubicacion rural informal.
- "El martes" sin fecha exacta.
- Cantidad aproximada: "unos 30".
- Mensaje reenviado sin contexto.

## Ejemplo Input/Output

Input:

```text
Necesito jaula para el martes, sale de Rauch y va a Liniers, unos 35 novillos.
```

Output:

```text
origin: Rauch (provided)
destination: Liniers (provided)
dateWindow: martes (estimated)
quantityEstimate: 35 (estimated)
livestockType: novillos (provided)
missingFields: contacto responsable
sourceMessageId: message original
requiresHumanReview: true
```

## Que Agentes La Usan

- `Producer Conversation Agent`
- `Carrier Conversation Agent`
