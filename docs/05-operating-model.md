# Modelo Operativo

Este documento describe el flujo marketplace WhatsApp-first del MVP de AGRO Logistics. El objetivo es que oferta y demanda se encuentren sin operador en el camino feliz, manteniendo soporte humano para excepciones.

## Principio Operativo

El MVP combina:

- WhatsApp como canal principal.
- Bot/agente para guiar conversaciones simples.
- Backend como source of truth de estados, reglas y eventos.
- Transportistas que responden oportunidades publicadas.
- Productor que acepta una oferta.
- Admin/soporte para casos puntuales.

La operacion es autogestionada con trazabilidad. Una ruta disponible es una declaracion de intencion/capacidad del carrier y no equivale a un viaje confirmado. Ningun viaje se confirma por interes unilateral: una oferta asociada a una carga requiere aceptacion explicita del productor segun el flujo de asignacion vigente.

## Flujo Feliz

| Paso | Accion | Responsable Principal | Resultado |
| --- | --- | --- | --- |
| 1 | Productor inicia conversacion | Productor / comisionista | Solicitud inicial recibida |
| 2 | Backend extrae y normaliza datos | Orquestador + OpenAI | Vista previa con campos faltantes y fecha canónica |
| 3 | Productor confirma | Productor | Carga registrada y publicada |
| 4 | Backend publica | Sistema | WhatsApp outbound a carriers elegibles |
| 5 | Transportistas responden | Transportistas | `TripOffer.INTERESTED`, `DECLINED`, consulta de informacion o soporte ante ambiguedad |
| 6 | Backend abre matching | Sistema | Carga pasa a `MATCHING` con primer interesado |
| 7 | Productor consulta interesados | Productor | Lista de ofertas comparables |
| 8 | Productor acepta oferta | Productor | `Assignment.CONFIRMED` + `Trip.PLANNED` |
| 9 | Ejecucion y soporte | Productor / transportista / soporte | Viaje planificado o excepcion registrada |

## Detalle Del Flujo

### 1. Productor Crea Carga

El productor escribe por WhatsApp en texto libre. El backend usa OpenAI para extraer campos candidatos, normaliza las fechas y presenta una vista previa. La vista previa no crea una carga. Al confirmar, el backend parsea y valida de nuevo antes de guardar/publicar. El telefono de WhatsApp identifica el contacto del productor.

Datos soportados en MVP:

- Hacienda: vacas, toros, novillos, terneros, terneras, vaquillonas.
- Granos: soja, maiz, trigo, girasol, sorgo, cebada.
- Cantidad y unidad cuando existan.
- Para hacienda, pesaje opcional por cabeza en kg, separado de la cantidad de animales.
- Origen, destino, fecha y observaciones como texto operativo.
- El teléfono entrante identifica al contacto; no se pide como un campo adicional.

Eventos principales:

- `MESSAGE_RECEIVED`
- `SHIPMENT_DRAFT_CREATED_FROM_CHAT`
- `LOAD_SELF_PUBLISHED`

### 2. Backend Publica A Transportistas

Al confirmar una carga con datos minimos, el backend la pasa a `PUBLISHED` y notifica a carriers registrados.

El mensaje mantiene opciones simples:

```text
1 Me interesa
2 No puedo
3 Mas info
```

Eventos principales:

- `BROADCAST_SENT`
- `CARRIER_NOTIFIED`
- `CARRIER_NOTIFICATION_SENT`

### 3. Transportista Responde

La respuesta del transportista no asigna el viaje. Solo registra su postura:

- `1` crea `TripOffer.INTERESTED`.
- `2` crea `TripOffer.DECLINED`.
- `3` devuelve mas informacion de la carga; una respuesta escrita ambigua deriva a soporte.

Con el primer interesado, la carga pasa de `PUBLISHED` a `MATCHING`.

Eventos principales:

- `CARRIER_INTERESTED`
- `CARRIER_DECLINED`
- `CARRIER_MORE_INFO_REQUESTED`
- `CARRIER_RESPONSE_AMBIGUOUS`
- `LOAD_MATCHING_STARTED`

### 4. Productor Acepta Una Oferta

El productor puede pedir “ver interesados” o “ver ofertas” y aceptar una opcion numerada.

Cuando acepta:

- Backend valida que la carga pertenezca al telefono del productor.
- Backend valida que la oferta sea `INTERESTED`.
- Backend evita duplicar assignments activos.
- Backend crea `Assignment.CONFIRMED`.
- Backend crea `Trip.PLANNED`.
- Backend cambia la carga a `ASSIGNED`.

Eventos principales:

- `PRODUCER_OFFER_ACCEPTED`
- `ASSIGNMENT_CREATED`
- `TRIP_CREATED`
- `MARKETPLACE_MATCH_CONFIRMED`
- `ASSIGNMENT_CONFIRMED`

## Rol De Admin / Soporte

El admin no es parte del flujo feliz. Interviene cuando:

- Falta informacion minima.
- Hay una respuesta ambigua.
- Hay cancelacion, reclamo o conflicto.
- Se requiere corregir datos.
- Hay que buscar una carga, viaje o evento para soporte.

Admin puede tener herramientas para observar, intervenir y corregir, pero no debe ser un cuello de botella para publicar o matchear cargas simples.

## Si Faltan Datos

Si faltan datos minimos para publicar:

1. El bot pregunta una cosa por vez.
2. Si no puede resolverlo, la carga queda marcada para soporte.
3. Admin puede corregir o completar.

No se debe presentar una carga incompleta como confirmada.

## Si Nadie Responde

Si no hay interesados:

1. La carga queda `PUBLISHED`.
2. El productor puede consultar estado.
3. Soporte puede ampliar alcance o contactar carriers manualmente.

## Si Hay Cancelacion

Una cancelacion debe registrarse y puede requerir soporte humano.

Pasos esperados:

1. Registrar quien cancela y cuando.
2. Registrar motivo si se conoce.
3. Marcar el viaje o assignment afectado.
4. Evaluar reemplazo o cierre de la carga.
5. Comunicar cambios a las partes afectadas.

## Transportista Informa Un Recorrido

La opcion conversacional recomendada es **“Informar viaje disponible”** o **“Publicar recorrido”**. Evitar “Crear viaje”: `Trip` representa la ejecucion operativa posterior a una asignacion.

Menu sugerido por rol: productor puede crear/ver sus cargas, ver interesados y consultar su viaje; transportista puede informar recorrido disponible, ver cargas recibidas, responder/interrogar una oportunidad, consultar oportunidades por ruta, completar homologacion y consultar su viaje. Ambos roles pueden ver su viaje cuando exista.

Al elegir **🛣️ Recorrido**, el bot pide origen, destino, fecha, paradas (o «sin paradas»), capacidad con unidad, tipo de carga y equipo. Interpreta dias de semana con la fecha del mensaje y presenta DD/MM/AAAA antes de confirmar; la disponibilidad por fecha se entiende para el dia completo de Argentina. Campos desconocidos no se inventan. La confirmacion crea una disponibilidad separada del viaje; si el transportista no esta aprobado queda como borrador para soporte. La disponibilidad puede pausarse, cancelarse o vencer desde el backoffice. La busqueda de cargas desde el chat y el compromiso de capacidad siguen pendientes.

Las zonas de interes del perfil sirven para difundir oportunidades futuras. No sustituyen una disponibilidad concreta con fechas y ruta. El transportista puede consultar una ruta y recibir cargas potencialmente compatibles sin activar una disponibilidad.

## Retorno Vacio Y Cargas Parciales

Para un regreso declarado vacio, el matching busca primero cargas sobre el corredor y la ventana temporal. Luego puede sugerir cargas cercanas a una parada o desvio que el carrier haya aceptado considerar. La propuesta debe exponer origen/destino de la carga, parada, desvio estimado si se puede calcular y capacidad consumida; nunca agregarla silenciosamente al plan.

El transportista decide si le interesa; luego se sigue el proceso normal de oferta y aceptacion del productor. Si ya hay una asignacion confirmada, cualquier carga adicional requiere validar capacidad residual, compatibilidad y efecto sobre la ruta antes de ofrecerla. Limites y reglas de multiples cargas quedan pendientes de producto/operacion.

## Homologacion Por WhatsApp Y Soporte

El transportista inicia una solicitud, completa los campos acordados en varios mensajes y adjunta archivos solicitados. La solicitud pasa a `PENDING_REVIEW`; soporte puede pedir correcciones, aprobar o rechazar con motivo y evento de auditoria. El menu debe mostrar el estado y los faltantes sin exponer documentos en mensajes de difusion. Los tipos documentales obligatorios, sus vigencias y criterios de aprobacion siguen pendientes.

## Backoffice De Conversaciones Y Productores

- Conversaciones: abrir un hilo en orden cronologico, diferenciando mensajes de la persona, mensajes salientes del agente/sistema y, cuando exista, entrega/error. Mostrar fecha/hora y contexto de rol/escenario con acceso restringido.
- Productores: buscar perfiles y consultar datos disponibles, ubicaciones, cargas, ofertas, asignaciones/viajes, eventos y conversaciones relacionadas. Marcar datos faltantes y no inferir un perfil que no se haya capturado.

## Registro De Eventos

Todo evento debe ayudar a reconstruir que paso, cuando paso y quien intervino.

Cada evento conserva:

- Tipo de evento.
- Fecha y hora.
- Carga, oferta, assignment o viaje asociado.
- Actor: productor, transportista, admin, bot/agente o sistema.
- Estado anterior y nuevo cuando aplique.
- Payload operativo minimo.
