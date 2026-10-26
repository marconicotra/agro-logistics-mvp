# Rank Carriers

## Nombre

`Rank Carriers`

## Objetivo

Ordenar carriers/ofertas o cargas por compatibilidad operativa para apoyar al productor, transportista u operador.

## Inputs

- `LivestockLoad`.
- Lista de `Carrier`.
- Lista de `Vehicle`.
- `Offer` disponibles.
- `CarrierRouteAvailability` o `CarrierSearchPreference`, cuando corresponda.
- Historial basico de `EventLog`.
- Flags de riesgo.

## Outputs

- Ranking de opciones.
- Motivos por opcion.
- Datos faltantes por opcion.
- Riesgos detectados.
- Nivel de confianza del ranking.

## Reglas

- Priorizar zona, capacidad y disponibilidad informada.
- Distinguir zona preferida de una ruta con ventana/capacidad concreta.
- Marcar si una coincidencia requiere parada o desvio aceptado.
- No asignar automaticamente.
- No descartar definitivamente una opcion fuera de criterios documentados; las excepciones requieren soporte.
- Marcar baja confianza si faltan datos de vehiculo o disponibilidad.
- Explicar los criterios usados.

## Casos Borde

- Carrier interesado sin vehiculo definido.
- Precio bueno pero disponibilidad ambigua.
- Carrier cercano pero con capacidad desconocida.
- Varias ofertas incompletas.
- Sin respuestas de carriers.

## Ejemplo Input/Output

Input:

```text
Carga Rauch -> Liniers, martes, 35 novillos. Carrier A disponible con precio. Carrier B cerca pero sin confirmar horario.
```

Output:

```text
1. Carrier A: disponibilidad y precio informados. Riesgo: capacidad no validada.
2. Carrier B: buena zona. Riesgo: horario no confirmado.
confidence: medium
nextDecisionActor: producer_or_carrier
```

## Que Agentes La Usan

- `Matching Agent`
- `Operations Dispatcher Agent`
