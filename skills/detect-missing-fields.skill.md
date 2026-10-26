# Detect Missing Fields

## Nombre

`Detect Missing Fields`

## Objetivo

Identificar datos faltantes o insuficientes para avanzar una `LivestockLoad`, `Offer`, `Assignment` o `Trip`.

## Inputs

- Entidad del dominio.
- Estado actual.
- Campos disponibles.
- Reglas de datos criticos.

## Outputs

- Lista de faltantes criticos.
- Lista de faltantes deseables.
- `missingCriticalFields`.
- Preguntas sugeridas.
- Recomendacion de revision humana.

## Reglas

- Para `LivestockLoad`, datos criticos iniciales: origen, destino, fecha o ventana, tipo de hacienda, cantidad aproximada y contacto responsable.
- Diferenciar faltante critico de deseable.
- No bloquear por datos deseables si el operador puede avanzar.
- Si falta un dato critico, marcar `requiresHumanReview`.
- Las preguntas deben ser cortas y una por dato critico.

## Casos Borde

- Fecha relativa sin dia calendario.
- Origen conocido pero establecimiento no identificado.
- Cantidad expresada como rango.
- Contacto responsable distinto del remitente.
- Oferta con interes pero sin disponibilidad.

## Ejemplo Input/Output

Input:

```text
LivestockLoad: origin=Rauch, destination=Liniers, dateWindow=unknown, livestockType=novillos, quantityEstimate=35, contact=unknown
```

Output:

```text
missingCriticalFields: dateWindow, contact
questions:
- Para que fecha o ventana necesitas cargar?
- Quien queda como contacto operativo?
requiresHumanReview: true
```

## Que Agentes La Usan

- `Producer Conversation Agent`
- `Operations Dispatcher Agent`
- `Data Quality Agent`

