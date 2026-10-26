# Generate Carrier Alert

## Nombre

`Generate Carrier Alert`

## Objetivo

Generar un mensaje claro de oportunidad de carga para transportistas.

## Inputs

- `LivestockLoad` validada o aprobada para broadcast.
- Resumen de carga.
- Condiciones conocidas.
- Datos que pueden compartirse.

## Outputs

- Mensaje de alerta para carrier.
- Campos incluidos.
- Campos omitidos por privacidad o incertidumbre.
- Recomendacion de respuesta esperada.

## Reglas

- No prometer asignacion.
- No cerrar precio.
- No compartir informacion privada innecesaria del productor.
- Pedir respuesta simple: disponible, precio estimado o consulta.
- Si hay datos pendientes, no ocultarlos.

## Casos Borde

- Carga con cantidad estimada.
- Fecha en ventana, no exacta.
- Broadcast ampliado por falta de respuestas.
- Transportista ya habia respondido antes.
- Datos privados que no deben compartirse.

## Ejemplo Input/Output

Input:

```text
LivestockLoad: Rauch -> Liniers, martes, 35 novillos aprox, validada por operador.
```

Output:

```text
Oportunidad de carga: Rauch -> Liniers, martes, 35 novillos aprox. Responder: disponible / precio estimado / consulta. Confirmacion sujeta a validacion del operador.
```

## Que Agentes La Usan

- `Carrier Conversation Agent`

