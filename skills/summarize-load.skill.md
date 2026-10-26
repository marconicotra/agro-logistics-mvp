# Summarize Load

## Nombre

`Summarize Load`

## Objetivo

Generar un resumen operativo breve de una `LivestockLoad` para operador o transportista.

## Inputs

- `LivestockLoad`.
- Flags de validacion.
- Campos faltantes.
- Destinatario del resumen: operador o carrier.

## Outputs

- Resumen legible.
- Campos pendientes destacados.
- Nivel de confianza.
- Version apta para operador o carrier.

## Reglas

- No presentar una carga incompleta como confirmada.
- Mostrar si hay datos estimados o pendientes.
- No incluir informacion privada del productor si el resumen es para carrier.
- Usar lenguaje breve, compatible con WhatsApp.
- Incluir origen, destino, fecha, hacienda y cantidad cuando existan.

## Casos Borde

- Carga validada con cantidad estimada.
- Origen ambiguo.
- Fecha como ventana amplia.
- Productor solicita condiciones especiales.
- Resumen para carrier sin datos privados.

## Ejemplo Input/Output

Input:

```text
LivestockLoad validada parcialmente: Rauch -> Liniers, martes, 35 novillos estimado, contacto pendiente.
```

Output:

```text
Carga: Rauch -> Liniers. Ventana: martes. Hacienda: 35 novillos aprox. Pendiente: contacto operativo. Requiere revision antes de publicar.
```

## Que Agentes La Usan

- `Producer Conversation Agent`
- `Operations Dispatcher Agent`
- `Admin Ops Agent`

