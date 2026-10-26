# Normalize Location

## Nombre

`Normalize Location`

## Objetivo

Normalizar ubicaciones informales para mejorar consistencia operativa sin ocultar ambiguedad.

## Inputs

- Texto de ubicacion.
- Contexto de provincia, zona o productor si existe.
- Mensaje fuente.

## Outputs

- Ubicacion normalizada candidata.
- Texto original.
- Nivel de confianza.
- `hasAmbiguousLocation`.
- Dudas o alternativas.

## Reglas

- Mantener siempre el texto original.
- No reemplazar una ubicacion ambigua como si fuera validada.
- Identificar localidad, provincia, establecimiento o referencia rural cuando sea posible.
- Marcar baja confianza si hay multiples interpretaciones.
- Pedir validacion humana cuando la ubicacion afecte publicacion o viaje.

## Casos Borde

- Localidades con nombres repetidos.
- Establecimientos conocidos solo por apodo.
- Referencias como "campo de Perez".
- Destinos comerciales abreviados.
- Mensaje sin provincia.

## Ejemplo Input/Output

Input:

```text
Sale del campo cerca de Rauch, va a Liniers.
```

Output:

```text
origin.original: campo cerca de Rauch
origin.normalizedCandidate: Rauch
origin.confidence: medium
origin.hasAmbiguousLocation: true
destination.original: Liniers
destination.normalizedCandidate: Liniers
destination.confidence: medium
requiresHumanReview: true
```

## Que Agentes La Usan

- `Producer Conversation Agent`
- `Data Quality Agent`

