# Operations

## Regla General

La operacion principal es autogestionada por WhatsApp. Kapso transporta mensajes, el backend conversa y decide usando OpenAI, y Postgres audita.

El admin no es un paso obligatorio del flujo feliz. Interviene solo para soporte, excepciones, correcciones, cancelaciones conflictivas o auditoria.

## Flujo Feliz

1. El productor crea una carga por WhatsApp.
2. El productor confirma el resumen.
3. El backend publica la carga a transportistas elegibles.
4. El transportista responde:
   - `1 Me interesa`
   - `2 No puedo`
   - `3 Mas info`
5. El productor consulta interesados y acepta una oferta.
6. El backend confirma el match y crea `Assignment CONFIRMED` + `Trip PLANNED`.

## Cuando Interviene Soporte

- faltan datos minimos
- ubicaciones ambiguas
- respuesta del transportista no es clara
- hay cambios importantes luego de publicar
- hay cancelacion
- hay conflicto entre partes
- hay sospecha de error operativo

## Publicacion De Carga

Cuando una carga tiene datos minimos y el productor confirma, el backend puede publicarla sin validacion previa del admin.

La alerta al transportista debe ser clara:

```text
Nueva carga disponible
cantidad y tipo
origen -> destino
fecha/hora
observaciones

1 Me interesa
2 No puedo
3 Mas info
```

## Respuestas De Transportistas

- `1`: interesado, el backend crea `TripOffer INTERESTED`.
- `2`: no puede, el backend crea `TripOffer DECLINED`.
- `3`: mas informacion, el backend pide soporte humano.

Una respuesta interesada no confirma viaje. Solo habilita al productor a elegir esa oferta.

## Aceptacion De Oferta

El productor elige una oferta interesada desde WhatsApp.

La aceptacion del productor confirma el match porque ya existen dos voluntades explicitas:

- carrier: `Me interesa`
- productor: `Elegir/Aceptar oferta`

Kapso no decide el match. Kapso llama al backend y muestra el resultado confirmado por la API.
