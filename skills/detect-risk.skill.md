# Detect Risk

## Nombre

`Detect Risk`

## Objetivo

Detectar riesgos operativos, de datos o de estado que requieren atencion del operador.

## Inputs

- Entidad del dominio.
- Estado actual.
- Eventos recientes.
- Mensajes relacionados.
- Flags de incertidumbre.

## Outputs

- Lista de riesgos.
- Severidad: baja, media o alta.
- Motivo.
- Accion recomendada.
- `requiresHumanReview`.

## Reglas

- Marcar alto riesgo si hay cancelacion, contradiccion o dato critico dudoso.
- Marcar riesgo medio si hay ambiguedad operativa.
- No resolver el riesgo automaticamente.
- Relacionar el riesgo con entidad y evento.
- Pedir intervencion humana si afecta confirmacion, precio, asignacion o viaje.

## Casos Borde

- Carrier dice "puede ser".
- Productor cambia fecha despues de publicar.
- Oferta tiene precio pero no disponibilidad.
- Viaje reporta incidencia.
- No hay respuestas luego de broadcast.

## Ejemplo Input/Output

Input:

```text
Offer: "puede ser a la tarde, despues te digo"
```

Output:

```text
risk: disponibilidad ambigua
severity: medium
requiresHumanReview: true
recommendedAction: pedir confirmacion o dejar en NEEDS_CLARIFICATION
```

## Que Agentes La Usan

- `Operations Dispatcher Agent`
- `Carrier Conversation Agent`
- `Matching Agent`
- `Pricing Agent`
- `Data Quality Agent`
- `Admin Ops Agent`

