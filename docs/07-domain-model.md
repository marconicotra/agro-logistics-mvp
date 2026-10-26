# Modelo De Dominio Central

Este documento define el modelo conceptual central de AGRO Logistics MVP. No describe base de datos fisica, APIs ni arquitectura tecnica.

El dominio debe separar claramente:

- `ShipmentRequest` / `Load`: la necesidad de traslado agropecuario.
- `Offer`: el interes o respuesta de un transportista.
- `Assignment`: el match entre carga y transportista, confirmado por doble aceptacion o propuesto por soporte.
- `Trip`: la ejecucion operativa del viaje.
- `CarrierRouteAvailability`: ruta/ventana y capacidad que el transportista declara disponibles; no es un `Trip` ni una asignacion.
- `CarrierSearchPreference`: zonas y criterios para recibir oportunidades; no afirma disponibilidad para una fecha concreta.

WhatsApp es un canal de conversacion, no una regla de negocio. Por eso vive en `ConversationSession` y `Message`, no dentro de `ShipmentRequest`, `Offer`, `Assignment` o `Trip`.

## Reglas Generales Del Dominio

- El sistema es self-service en el flujo feliz: productor publica, carrier expresa interes y productor acepta una oferta.
- El admin/soporte resuelve excepciones, cancelaciones conflictivas, correcciones y auditoria.
- Todo cambio relevante debe registrar un evento en `EventLog`.
- Los datos extraidos desde mensajes deben conservar referencia al mensaje original.
- Los datos incompletos no deben ocultarse: deben marcarse como pendientes o dudosos.
- No se debe asumir precio, disponibilidad, cantidad, ubicacion exacta ni condiciones del viaje si no fueron informadas.
- Carrier interesado no confirma viaje; productor debe aceptar la oferta para crear el match.
- La consulta conversacional del productor debe seleccionar una carga antes de elegir una oferta cuando tenga varias; la confirmacion final debe mostrar el transportista exacto y quedar asociada a los IDs de esa carga y oferta, nunca a una posicion que pueda cambiar.

## Manejo De Incertidumbre

Los datos criticos pueden tener estado de confianza:

| Estado | Significado |
| --- | --- |
| `unknown` | El dato no fue informado o no pudo inferirse. |
| `estimated` | El dato es aproximado o fue expresado de forma informal. |
| `provided` | El dato fue informado por un actor, pero no validado. |
| `validated` | El dato fue revisado y aceptado por el operador. |
| `corrected` | El dato fue modificado luego de una revision o nueva informacion. |

Flags conceptuales recomendados:

| Flag | Uso |
| --- | --- |
| `isValidated` | Indica que la entidad o dato fue revisado por operador. |
| `missingCriticalFields` | Indica que faltan datos criticos para avanzar. |
| `requiresHumanReview` | Indica que el operador debe intervenir antes de continuar. |
| `hasAmbiguousLocation` | Indica que una ubicacion puede tener multiples interpretaciones. |
| `hasEstimatedValues` | Indica que existen datos aproximados. |

### Normalizacion geografica

Las localidades se comparan contra el snapshot versionado local de Georef en
`data/catalogs/georef/localidades.csv`. Solo una coincidencia unica se guarda
con nombre, provincia, ID Georef, version/checksum del catalogo y procedencia
`GEOREF`. Un homonimo queda sin ID canonico y marca la carga para aclaracion o
revision. Establecimientos, parajes y referencias rurales que no figuren en
Georef se conservan como texto declarado (`USER_DECLARED`); nunca se reemplazan
por una localidad cercana.

## Entidades

### Catalogos De Dominio

`GeographicCatalogEntry` mantiene provincias, partidos/departamentos y localidades en una jerarquía, preservando IDs de Georef cuando existan y alias editables. `CargoCategory` y `CargoType` mantienen categorías, tipos y alias activos que consulta el backend al interpretar nuevas solicitudes. Estos catálogos no modifican en forma retroactiva los textos o las ubicaciones originales guardadas en cargas históricas.

## `User`

### Descripcion

Identidad base para actores humanos internos o externos. Representa a una persona o cuenta operativa que interactua con el sistema.

### Campos Principales

| Campo | Descripcion |
| --- | --- |
| `userId` | Identificador conceptual del usuario. |
| `displayName` | Nombre visible. |
| `phoneNumber` | Telefono principal, cuando aplique. |
| `role` | Rol operativo: `Producer`, `Carrier`, `Operator` u otro rol interno futuro. |
| `status` | Estado operativo del usuario: activo, inactivo o bloqueado. |
| `createdAt` | Fecha de alta. |
| `notes` | Observaciones internas. |

### Relaciones

- Puede estar asociado a un `Producer`, `Carrier` u operador interno.
- Puede generar `Message`.
- Puede ser actor en `EventLog`.

### Reglas De Negocio

- Un `User` no define por si solo reglas de transporte.
- Un mismo telefono puede requerir revision humana si parece representar a mas de un actor.
- Cambios de rol o estado deben registrarse como eventos si afectan la operacion.

## `Producer`

### Descripcion

Productor o comisionista que origina una necesidad de transporte agropecuario, inicialmente hacienda o granos.

### Campos Principales

| Campo | Descripcion |
| --- | --- |
| `producerId` | Identificador conceptual del productor o comisionista. |
| `userId` | Referencia al `User` asociado, si existe. |
| `name` | Nombre comercial o personal. |
| `contactPhone` | Telefono operativo. |
| `usualLocations` | Establecimientos, zonas o referencias frecuentes. |
| `trustNotes` | Observaciones internas de confianza o historial. |
| `isValidated` | Indica si fue revisado por operador. |

### Relaciones

- Puede originar muchas `LivestockLoad`.
- Puede participar en `ConversationSession`.
- Puede recibir o enviar `Message`.
- Puede aparecer como actor relacionado en `EventLog`.

### Reglas De Negocio

- Un productor puede iniciar una carga con datos incompletos.
- El backend valida datos criticos antes de publicar; pide aclaracion al productor y deriva a operador ante ambiguedad o excepcion. No exige revision manual para cada carga completa.
- No se debe compartir informacion privada del productor con transportistas si no es necesaria para coordinar.

## `Carrier`

### Descripcion

Cuenta operativa que puede representar a una persona transportista o a una empresa y recibir oportunidades de carga. El canal/persona de contacto no sustituye a la entidad transportista.

### Campos Principales

| Campo | Descripcion |
| --- | --- |
| `carrierId` | Identificador conceptual del transportista. |
| `carrierKind` | `PERSON` para un transportista independiente o `COMPANY` para una empresa/flota. |
| `userId` | Referencia al `User` que actua como contacto principal, si existe. No es la identidad del carrier. |
| `name` | Nombre de la persona transportista o de la empresa. |
| `contactPhone` | Telefono WhatsApp operativo del contacto principal. |
| `email` | Email de contacto, si fue informado. |
| `serviceZones` | Zonas donde suele operar. |
| `trustNotes` | Historial cualitativo y observaciones internas. |
| `availabilityNotes` | Comentarios de disponibilidad conocidos. |
| `isValidated` | Indica si fue revisado por operador. |

### Relaciones

- Puede tener uno o mas `Vehicle`.
- Puede tener uno o mas `Driver`; en el caso `PERSON`, el perfil puede tener un unico conductor que es la misma persona.
- Puede generar muchos `Offer`.
- Puede ser parte de un `Assignment`.
- Puede ejecutar un `Trip` si el match fue confirmado por doble aceptacion o soporte.

### Reglas De Negocio

- Responder interesado no equivale a quedar asignado.
- Precio o disponibilidad informados por el carrier son datos provistos, no confirmacion final.
- La asignacion requiere doble aceptacion: carrier interesado y productor aceptando una oferta.
- Solo carriers aprobados participan del matching que requiera homologacion; excepciones operativas deben quedar explicitas y auditadas.
- En el MVP, el estado `APPROVED` es requisito para difusion y matching; un operador puede habilitar una excepcion solo mediante una regla explicita y auditada.
- `serviceZones` describe interes habitual y no sustituye una disponibilidad por ruta/fecha.
- La elegibilidad de un `Carrier` aprobado permite recibir oportunidades; no significa que cualquier conductor o vehiculo de su flota ya este listo para ejecutar un viaje.

### Homologacion MVP

El backend soporta un flujo de homologacion administrado por soporte. `Carrier.isValidated`
se mantiene por compatibilidad, pero el estado operativo se expresa con
`validationStatus`.

Estados soportados:

- `DRAFT`
- `WAITING_DATA`
- `WAITING_DOCUMENTS`
- `PENDING_REVIEW`
- `APPROVED`
- `REJECTED`
- `SUSPENDED`

Datos minimos para aprobar un transportista:

- Telefono operativo.
- CUIT.
- Al menos un vehiculo asociado.
- Al menos un documento adjunto con `externalUri` o `storageUri`.

Reglas:

- `isValidated = true` debe corresponder a `validationStatus = APPROVED`.
- Un transportista existente con `isValidated = true` se trata como aprobado.
- Soporte puede aprobar o rechazar la homologacion desde backoffice.
- Todo cambio de homologacion debe registrar `EventLog`.

El producto propone capturar por WhatsApp email, empresa opcional, CUIT, flota, patentes y licencia, ademas del contacto. La licencia pertenece a la persona `Driver`, no al vehiculo ni a la empresa; los datos/documentos del vehiculo pertenecen a cada `Vehicle`. La lista de documentos obligatorios, vigencias y criterios de validacion sigue pendiente de definicion operativa/legal.

## `CarrierSearchPreference`

Preferencias relativamente estables con las que un carrier delimita donde quiere recibir oportunidades. Puede incluir zonas/corredores preferidos y tipos de carga/equipo aceptados una vez que se aprueben los catalogos.

Regla: una preferencia habilita difusion o filtrado, pero nunca se interpreta como un compromiso de disponibilidad para una fecha.

## `CarrierRouteAvailability`

Declaracion del carrier sobre una ruta concreta o prevista y capacidad que cree tener disponible para una ventana temporal.

Campos conceptuales: carrier, origen, destino, ventana, capacidad y unidad informadas, categorias de carga aceptadas, vehiculo/equipo si se conoce, paradas/corredor opcionales, desvio maximo que acepta, estado, expiracion y fuente de cada dato. Se conserva el texto original y la validacion; ninguna unidad o parada se infiere.

Reglas:

- Se crea y actualiza por declaracion explicita del transportista; puede quedar incompleta mientras se piden campos necesarios para buscar.
- No crea `Offer`, `Assignment` ni `Trip` por si sola.
- Cargas parciales o desvio son sugerencias. La capacidad se reserva solo mediante una operacion de dominio posterior definida y confirmada; no sobreasignar por inferencia.
- La disponibilidad se puede pausar/cancelar y debe expirar segun una politica pendiente de definir.

## `CarrierOnboarding`

### Descripcion

Proceso de revision de datos y documentacion de un transportista.

### Campos Principales

| Campo | Descripcion |
| --- | --- |
| `onboardingId` | Identificador del proceso. |
| `carrierId` | Transportista asociado. |
| `status` | `DRAFT`, `WAITING_DATA`, `WAITING_DOCUMENTS`, `PENDING_REVIEW`, `APPROVED` o `REJECTED`. |
| `requiredFields` | Datos minimos esperados para homologar. |
| `missingFields` | Datos aun faltantes. |
| `companyName` | Empresa opcional declarada. |
| `fleetSummary` | Cantidad y tipos de camiones declarados, relacionados a sus `Vehicle`. |
| `driverIds` | Conductores asociados al proceso de homologacion. |
| `submittedData` | Referencias a CUIT, email y datos de flota capturados; no implica validacion. |
| `documentIds` | Documentos/adjuntos relacionados, con acceso privado. |
| `submittedAt` | Fecha en que quedo listo para revision. |
| `reviewedByUserId` | Operador que reviso. |
| `reviewedAt` | Fecha de revision. |
| `rejectionReason` | Motivo de rechazo, si aplica. |
| `captureContext` | Paso conversacional activo y referencias internas al conductor/unidad actuales; estado de reanudacion, no prueba de validacion. |

### Reglas De Negocio

- Debe poder existir un proceso activo por transportista.
- La captura por WhatsApp puede crear el borrador y guardar datos declarados por pasos; `captureContext` no debe contener el archivo, credenciales ni el texto crudo de mensajes.
- Un documento entrante solo se vincula al Driver/Vehicle que espera el paso activo y cuya pertenencia al Carrier se valida. La captura nunca aprueba por si sola ninguna entidad.
- No se aprueba si faltan datos minimos.
- Aprobar actualiza `Carrier.isValidated`, `Carrier.validationStatus` y fechas de revision.
- Rechazar conserva el historial y motivo.

## `Vehicle`

### Descripcion

Unidad de transporte ofrecida por un `Carrier`. En el MVP se modela de forma conceptual y operativa, sin detalles tecnicos exhaustivos.

### Campos Principales

| Campo | Descripcion |
| --- | --- |
| `vehicleId` | Identificador conceptual del vehiculo. |
| `carrierId` | Transportista propietario u operador. |
| `vehicleType` | Tipo de unidad o configuracion conocida. |
| `bodyType` | Carroceria/configuracion declarada, pendiente de catalogo canonico. |
| `capacityEstimate` | Capacidad aproximada si se conoce. |
| `plate` | Patente si fue informada y validada. |
| `status` | Disponible, no disponible o desconocido. |
| `validationStatus` | `PENDING_REVIEW`, `APPROVED` o `REJECTED`, independiente del estado operativo. |
| `reviewedByUserId` / `reviewedAt` | Operador y fecha de la ultima revision. |
| `validationFlags` | Flags de datos pendientes o dudosos. |

### Relaciones

- Pertenece a un `Carrier`.
- Puede ser mencionado en un `Offer`.
- Puede quedar asociado a un `Assignment` y luego a un `Trip`.

### Reglas De Negocio

- La capacidad puede ser estimada hasta validacion del operador.
- No debe asignarse un vehiculo si la informacion critica es dudosa para la carga.
- La unidad se aprueba por separado del Carrier; editar datos relevantes reinicia su estado a `PENDING_REVIEW`.
- El viaje no puede iniciar si la unidad asignada no esta activa y aprobada.

## `Driver`

### Descripcion

Persona que conduce un vehiculo en un `Trip`. Puede ser el mismo transportista independiente o uno de varios conductores asociados a una empresa/flota. La licencia se asocia a esta persona.

### Campos Principales

| Campo | Descripcion |
| --- | --- |
| `driverId` | Identificador conceptual del conductor. |
| `carrierId` | Transportista/empresa al que esta asociado en el MVP. |
| `userId` | Referencia a su identidad de contacto/cuenta, si opera por WhatsApp. |
| `name` | Nombre declarado del conductor. |
| `phone` | Telefono de contacto, si fue informado. |
| `licenseCategory` | Categoria declarada de licencia; catalogo y vencimientos pendientes. |
| `status` | Estado operativo del conductor, por separado de la revision. |
| `validationStatus` | `PENDING_REVIEW`, `APPROVED` o `REJECTED`, con operador/fecha. |
| `licenseDocumentIds` | Referencias privadas a documentos de licencia asociados a la persona. |

### Reglas De Negocio

- Un `Carrier` puede tener varios `Driver`; para un transportista independiente puede existir un unico conductor correspondiente a la misma persona.
- La cuenta/telefono que conversa con AGRO puede ser un contacto administrativo y no necesariamente el conductor asignado al viaje.
- Antes de iniciar un `Trip` deben estar identificados el conductor y el vehiculo que lo ejecutan, y cumplirse los requisitos de revision acordados para ambos.
- En la implementacion inicial, soporte registra una nota obligatoria al aprobar conductor o unidad. La nota audita la revision declarada; no determina ni reemplaza la matriz legal pendiente.
- La licencia no se considera valida por el solo hecho de recibir una imagen; soporte debe revisar con criterios pendientes de definir.

## `ShipmentRequest` / `Load`

### Descripcion

Necesidad de traslado agropecuario. En el MVP puede representar hacienda o granos basicos desde un origen hacia un destino en una fecha o ventana determinada.

No representa la ejecucion del viaje. La ejecucion corresponde a `Trip`.

### Campos Principales

| Campo | Descripcion |
| --- | --- |
| `loadId` | Identificador conceptual de la carga. |
| `producerId` | Productor o comisionista que origina la necesidad. |
| `origin` | Origen informado, estimado o validado. |
| `destination` | Destino informado, estimado o validado. |
| `dateWindow` | Fecha o ventana estimada de carga. |
| `cargoCategory` | Categoria de carga: `LIVESTOCK` o `GRAIN`. |
| `cargoType` | Tipo especifico: vacas, novillos, soja, maiz, trigo, etc. |
| `quantityUnit` | Unidad estimada: cabezas, toneladas, kilos o camiones. |
| `livestockType` | Tipo o categoria de hacienda, mantenido por compatibilidad. |
| `quantityEstimate` | Cantidad aproximada o validada. |
| `weightPerHeadKg` | Pesaje declarado en kg por animal; opcional y separado de la cantidad de cabezas. |
| `operationalNotes` | Observaciones relevantes. |
| `status` | Estado de la maquina de `LivestockLoad`. |
| `fieldConfidence` | Estado de confianza por dato critico. |
| `isValidated` | Validacion general por operador. |
| `missingCriticalFields` | Lista o marca de datos criticos faltantes. |
| `requiresHumanReview` | Indica necesidad de revision humana. |
| `hasAmbiguousLocation` | Marca ubicaciones ambiguas. |
| `sourceMessageId` | Mensaje original desde el cual se extrajo informacion. |

### Relaciones

- Pertenece a un `Producer`.
- Puede nacer desde una `ConversationSession` y uno o mas `Message`.
- Puede recibir muchos `Offer`.
- Puede tener cero o un `Assignment` activo.
- Puede originar cero o un `Trip` confirmado en el MVP.
- Genera multiples `EventLog`.

### Reglas De Negocio

- Puede existir incompleta.
- Puede nacer como `DRAFT` desde chat y autopublicarse si el productor confirma y existen datos minimos.
- No debe publicarse si faltan datos minimos para entender tipo y cantidad de carga.
- Una carga incompleta puede avanzar a soporte, no a confirmacion automatica.
- La publicacion a transportistas puede ser self-service en el flujo feliz.
- Cambios criticos de origen, destino, fecha o cantidad requieren revision humana.

## `Offer`

### Descripcion

Interes, disponibilidad, precio estimado, no disponibilidad o consulta de un `Carrier` frente a una `LivestockLoad`.

No confirma viaje y no asigna transportista.

### Campos Principales

| Campo | Descripcion |
| --- | --- |
| `offerId` | Identificador conceptual de la oferta o respuesta. |
| `loadId` | Carga a la que responde. |
| `carrierId` | Transportista que responde. |
| `vehicleId` | Vehiculo mencionado, si existe. |
| `responseType` | Interesado, no disponible, consulta, precio informado u otro tipo operativo. |
| `priceEstimate` | Precio estimado informado, si existe. |
| `availabilityWindow` | Ventana de disponibilidad informada. |
| `messageId` | Mensaje que origino la oferta. |
| `status` | Estado de la maquina de `Offer`. |
| `requiresHumanReview` | Marca respuestas ambiguas o sensibles. |
| `confidence` | Confianza en la clasificacion de la respuesta. |

### Relaciones

- Pertenece a una `LivestockLoad`.
- Pertenece a un `Carrier`.
- Puede referenciar un `Vehicle`.
- Puede ser usada para proponer un `Assignment`.
- Genera `EventLog`.

### Reglas De Negocio

- Una oferta puede ser ambigua y requerir aclaracion.
- Una oferta con precio informado no define precio final.
- Una oferta shortlistada no equivale a asignacion.
- El productor puede aceptar explicitamente una oferta `INTERESTED` de su carga; el backend valida ownership/estado y crea el `Assignment` confirmado. Soporte propone o corrige una asignacion solo en excepciones.

## `Assignment`

### Descripcion

Decision operativa de seleccionar un `Carrier` y, cuando corresponda, un `Vehicle` para una `LivestockLoad`.

En el flujo feliz representa la decision explicita del productor sobre una oferta interesada. En excepciones, soporte puede crear una propuesta que requiere confirmacion segun las reglas operativas.

### Campos Principales

| Campo | Descripcion |
| --- | --- |
| `assignmentId` | Identificador conceptual de la asignacion. |
| `loadId` | Carga asignada. |
| `offerId` | Oferta que motivo la asignacion, si existe. |
| `carrierId` | Transportista seleccionado. |
| `vehicleId` | Vehiculo seleccionado, si existe. |
| `selectedByUserId` | Actor que eligio/proceso la opcion: productor en el flujo feliz u operador en excepciones. |
| `status` | Estado de la maquina de `Assignment`. |
| `confirmationNotes` | Condiciones acordadas y notas operativas. |
| `requiresHumanReview` | Marca conflictos o datos pendientes. |

### Relaciones

- Pertenece a una `LivestockLoad`.
- Puede derivar de una `Offer`.
- Vincula un `Carrier` y opcionalmente un `Vehicle`.
- Puede originar un `Trip` cuando queda confirmada.
- Genera `EventLog`.

### Reglas De Negocio

- Nunca nace por el interes unilateral del transportista. En el flujo feliz el productor confirma explicitamente y el backend registra el cambio de manera transaccional e idempotente; en excepciones interviene soporte.
- Una carga no deberia tener mas de un `Assignment` confirmado activo.
- Si se cancela, el operador puede buscar reemplazo y crear o marcar un nuevo proceso de asignacion.
- Cambios de carrier o vehiculo despues de confirmar requieren evento.

## `Trip`

### Descripcion

Ejecucion operativa de una carga ya confirmada. Representa el viaje coordinado con productor y transportista.

No debe existir como viaje activo sin `Assignment` confirmado.

### Campos Principales

| Campo | Descripcion |
| --- | --- |
| `tripId` | Identificador conceptual del viaje. |
| `loadId` | Carga que se ejecuta. |
| `assignmentId` | Asignacion confirmada que origina el viaje. |
| `carrierId` | Transportista confirmado. |
| `vehicleId` | Vehiculo confirmado, si existe. |
| `driverId` | Conductor que ejecutara el viaje, identificado antes del inicio operativo. |
| `plannedDateWindow` | Ventana operativa acordada. |
| `status` | Estado de la maquina de `Trip`. |
| `incidentNotes` | Incidencias registradas. |
| `closureNotes` | Observaciones de cierre. |
| `requiresHumanReview` | Marca incidencias o conflictos. |

### Relaciones

- Depende de una `LivestockLoad`.
- Depende de un `Assignment` confirmado.
- Se ejecuta por un `Carrier`.
- Puede referenciar un `Vehicle`.
- Genera `EventLog`.

### Reglas De Negocio

- Nace despues de confirmacion manual.
- No requiere GPS en tiempo real para el MVP.
- Estados de ejecucion pueden basarse en confirmaciones manuales o mensajes operativos.
- Incidencias y cancelaciones requieren intervencion humana.
- El cierre lo realiza el operador cuando tiene confirmacion suficiente.

## `ConversationSession`

### Descripcion

Conversacion operativa por un canal. En el MVP el canal principal es WhatsApp, pero la entidad debe permitir que el dominio no dependa del canal.

### Campos Principales

| Campo | Descripcion |
| --- | --- |
| `conversationSessionId` | Identificador conceptual de la conversacion. |
| `channel` | Canal: inicialmente `whatsapp`. |
| `participantUserIds` | Usuarios participantes conocidos. |
| `relatedEntityIds` | Cargas, ofertas, assignments o trips relacionados. |
| `status` | Abierta, pausada o cerrada. |
| `startedAt` | Inicio de la conversacion. |
| `lastMessageAt` | Ultima actividad conocida. |

### Relaciones

- Contiene muchos `Message`.
- Puede estar vinculada a `LivestockLoad`, `Offer`, `Assignment` o `Trip`.
- Genera eventos de conversacion y mensajes.

### Reglas De Negocio

- La conversacion puede incluir informacion incompleta o informal.
- Una conversacion no define por si sola el estado de una carga o viaje.
- La interpretacion de mensajes relevantes debe generar eventos y, si corresponde, revision humana.

## `Message`

### Descripcion

Mensaje individual entrante o saliente dentro de una `ConversationSession`.

Puede ser texto, audio transcripto u otro contenido operativo simple.

### Campos Principales

| Campo | Descripcion |
| --- | --- |
| `messageId` | Identificador conceptual del mensaje. |
| `conversationSessionId` | Conversacion a la que pertenece. |
| `direction` | Entrante o saliente. |
| `senderType` | Productor, transportista, operador, bot, agente AI o sistema. |
| `senderId` | Actor identificado si existe. |
| `mediaAssetId` | Archivo recibido asociado, si el mensaje trae media. |
| `rawContent` | Contenido original o transcripcion. |
| `normalizedContent` | Version normalizada si una skill la produce. |
| `receivedAt` | Fecha de recepcion o envio. |
| `deliveryStatus` | Estado de entrega conocido del proveedor, si existe; no altera contenido ni estado de dominio. |
| `relatedEntityIds` | Entidades asociadas. |

### Relaciones

- Pertenece a una `ConversationSession`.
- Puede originar o actualizar `LivestockLoad`, `Offer`, `Assignment` o `Trip`.
- Puede ser referencia de extracciones hechas por skills.
- Genera `EventLog`.

### Reglas De Negocio

- El contenido original debe preservarse cuando sea usado para extraer datos.
- Un mensaje ambiguo no debe producir decisiones criticas automaticamente.
- Mensajes operativos importantes deben quedar vinculados a la entidad correspondiente.
- Si el mensaje proviene de un boton/quick reply, `normalizedContent` puede conservar
  el valor canonico seleccionado y `relatedEntityIds` puede incluir `interactiveActionId`.
- Las opciones enviadas no son regla de negocio: se auditan en `EventLog` y el dominio
  procesa la decision resultante.

## `MediaAsset`

### Descripcion

Referencia tecnica a un archivo recibido por un canal, inicialmente WhatsApp/KAPSO.
No reemplaza a `Document`: `MediaAsset` conserva metadatos del canal y `Document`
representa la pieza revisable por soporte cuando el archivo corresponde a un
transportista u otra entidad operativa.

### Campos Principales

| Campo | Descripcion |
| --- | --- |
| `mediaAssetId` | Identificador interno del archivo recibido. |
| `messageId` | Mensaje que trajo el archivo. |
| `provider` | Canal/proveedor de origen, por ejemplo `kapso`. |
| `providerMediaId` | ID externo del archivo en el proveedor. |
| `mediaType` | `document`, `image`, `audio`, `video` o `unknown`. |
| `mimeType` | MIME informado por el proveedor. |
| `fileName` | Nombre de archivo informado, si existe. |
| `externalUrl` | URL temporal o externa informada por el proveedor. |
| `storageUri` | Ubicacion local/futura si el archivo fue descargado. |
| `status` | `RECEIVED`, `DOWNLOADED`, `PROCESSED` o `FAILED`. |
| `transcriptionStatus` | `NOT_REQUIRED`, `PENDING`, `SUCCEEDED`, `FAILED` o `SKIPPED` para audio. |
| `transcriptionText` | Texto transcripto cuando el media es audio y STT fue exitoso. |
| `transcriptionProvider` | Proveedor de STT usado, por ejemplo `openai`. |
| `transcriptionModel` | Modelo de STT usado para la transcripcion. |
| `transcriptionError` | Motivo tecnico del fallo o skip de la transcripcion. |
| `transcribedAt` | Fecha/hora de la transcripcion exitosa. |

### Reglas De Negocio

- La recepcion de media registra `MEDIA_ASSET_RECEIVED`.
- Si el media es audio y STT esta habilitado, el backend puede descargarlo, transcribirlo y usar el texto resultante como entrada conversacional.
- La transcripcion debe registrar eventos auditables de inicio, exito, fallo o skip.
- Si se puede asociar a un transportista por telefono, se crea un `Document` pendiente.
- Si no hay transportista asociado, se registra evento y queda para revision humana.
- La descarga binaria es opcional; el MVP puede operar con referencia externa.

## `EventLog`

### Descripcion

Registro auditable de acciones, cambios de estado, decisiones, mensajes relevantes y eventos operativos.

Es la base para historial, debugging, analytics y auditoria.

### Campos Principales

| Campo | Descripcion |
| --- | --- |
| `eventId` | Identificador conceptual del evento. |
| `eventType` | Tipo tecnico del evento. |
| `occurredAt` | Fecha y hora del evento. |
| `actorType` | Tipo de actor que origina el evento. |
| `actorId` | Identificador del actor si existe. |
| `entityType` | Entidad principal afectada. |
| `entityId` | Identificador de la entidad principal. |
| `relatedEntityIds` | Entidades relacionadas. |
| `previousState` | Estado anterior si aplica. |
| `newState` | Estado nuevo si aplica. |
| `summary` | Resumen legible. |
| `payload` | Datos relevantes del evento, sin definir almacenamiento fisico. |
| `source` | Canal o sistema origen. |

### Relaciones

- Puede vincularse a cualquier entidad del dominio.
- Debe referenciar entidad principal y, cuando aplique, entidades relacionadas.

### Reglas De Negocio

- Todo cambio relevante debe tener evento.
- Los eventos deben permitir reconstruir que paso, cuando paso y quien intervino.
- Los cambios de estado deben guardar estado anterior y nuevo.
- Las metricas operativas deben derivarse de eventos, no de memoria informal.

## Riesgos Del Modelo Propuesto

### Disponibilidad declarada por recorrido (implementacion inicial)

`RouteAvailability` es una declaracion separada de `ShipmentRequest`, `TripOffer` y `Trip`. Conserva origen, destino, paradas intermedias en orden, ventana temporal, capacidad y unidad declaradas, tipos de carga/equipo, escenario QA y estado. Solo compara segmentos formados por localidades declaradas y en orden. La coincidencia no calcula desvio ni crea una oferta, asignacion o viaje.

Una disponibilidad activa pasa a `EXPIRED` cuando vence su `window_end` y se consulta listado o matching en el backoffice; el cambio queda en el log de eventos.

La comparacion de capacidad solo acepta unidades iguales o conversion exacta KG/TON; no convierte cabezas ni camiones. Si faltan datos, la coincidencia indica que deben confirmarse. El alta de backoffice comienza en `DRAFT`; operador puede activarla, cerrarla o cancelarla. El compromiso atomico con una asignacion, la captura por WhatsApp, las preferencias de zona y la auditoria de cada transicion siguen pendientes.

La migracion `0012_route_availabilities` crea la persistencia SQL, pero no se aplico a ninguna base compartida. Las altas y transiciones de backoffice escriben eventos de auditoria con actor y estado anterior/nuevo dentro de la transaccion; el compromiso con asignacion sigue sin implementarse.

Los documentos guardan fechas declaradas de vigencia y referencia al documento anterior renovado. El gate de inicio rechaza documentos aprobados vencidos o cuya vigencia aun no comenzo, cuando esas fechas fueron informadas. La ausencia de fecha no se interpreta como vigencia indefinida ni como vencimiento automatico; falta definir una matriz QA obligatoria por tipo de titular/documento.

1. Demasiados estados pueden generar carga operativa si el operador debe actualizarlos manualmente.
2. La separacion entre `Offer`, `Assignment` y `Trip` puede sentirse compleja al inicio, aunque evita mezclar interes, decision y ejecucion.
3. Los datos estimados vs confirmados pueden requerir disciplina operativa para no degradarse.
4. Si los eventos no se registran de forma consistente, analytics y auditoria pierden valor.
5. La ambiguedad de ubicaciones rurales puede producir estados incompletos frecuentes.

## Decisiones A Validar Con Negocio

1. Que datos son criticos para publicar una carga y cuales pueden quedar pendientes.
2. Que estados realmente necesita ver el operador en el dia a dia.
3. Cuando una oferta debe considerarse vencida o descartada.
4. Que informacion del productor puede compartirse con transportistas en el broadcast.
5. Que eventos son obligatorios para auditoria operativa desde el primer MVP.

## Siguiente Paso Recomendado

Validar este modelo con un operador que coordine cargas reales. Ajustar solo los estados y campos que afecten decisiones operativas antes de pasar a diseno backend.

## Recorridos y seguimiento — ampliación 2026-10-25

Las preferencias habituales no acreditan disponibilidad. Comparar nodos geográficos canónicos y ordenados, sin eliminar la provincia ni resolver homónimos por inferencia. El viaje en IN_TRANSIT habilita tres controles (salida/mitad/llegada) vinculados al chofer y al escenario, independientes de los estados de entrega. Una posición informada no constituye prueba GPS continua ni cambia el estado del viaje. Los datos propios de ubicación y la geometría temporal del proveedor se tratan por separado.
