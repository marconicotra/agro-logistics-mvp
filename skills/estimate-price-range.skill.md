# Estimate Price Range

## Nombre

`Estimate Price Range`

## Objetivo

Estimar un rango orientativo de precio para comparar ofertas y detectar valores fuera de rango.

## Inputs

- `LivestockLoad`.
- Origen y destino.
- Fecha o ventana.
- Tipo y cantidad de hacienda.
- `Offer.priceEstimate` si existe.
- Historial basico disponible.

## Outputs

- Rango estimado.
- Nivel de confianza.
- Supuestos usados.
- Alertas de insuficiencia de datos.

## Reglas

- No fijar precio final.
- No negociar.
- No aceptar ni rechazar ofertas por precio.
- Si faltan datos criticos, devolver baja confianza.
- Explicar supuestos simples de MVP.

## Casos Borde

- Origen o destino ambiguo.
- Cantidad aproximada.
- Fecha urgente.
- Solo existe una oferta.
- Oferta muy alta o muy baja sin historial suficiente.

## Ejemplo Input/Output

Input:

```text
Carga Rauch -> Liniers, martes, 35 novillos aprox. Oferta recibida: precio estimado informado por carrier.
```

Output:

```text
priceRange: orientativo
confidence: low-medium
assumptions: origen/destino no geocodificados, cantidad aproximada
operatorReviewRequired: true
```

## Que Agentes La Usan

- `Pricing Agent`
- `Matching Agent`
- `Operations Dispatcher Agent`

