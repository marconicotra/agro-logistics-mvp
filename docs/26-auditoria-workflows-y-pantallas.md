# Auditoría de pantallas y recorridos

Fecha de auditoría: 2026-10-26. Fuente: rutas de `frontend/src/App.tsx`, pantallas de `frontend/src/pages/`, API y servicios de `backend/app/`. El estado describe lo que hace el código revisado; el alcance se rige por `docs/04-mvp-scope.md`.

## Reglas para leer esta auditoría

- **Implementado:** hay pantalla/flujo y acciones conectadas al backend.
- **Parcial:** existe una parte usable, pero el flujo depende de soporte, credenciales/proveedor o decisiones pendientes.
- **Pendiente:** está en el alcance o la bitácora, pero no se encontró un recorrido completo implementado.
- Una disponibilidad de recorrido no es un viaje. Un transportista interesado no confirma un viaje: el productor acepta explícitamente la oferta.
- Las pantallas de estado de productor/transportista son rutas públicas sin `AuthGate`; las demás pantallas de gestión sí pasan por `AuthGate`. No habilitar el backoffice humano en entornos compartidos sin roles verificados en servidor.

## Mapa del backoffice

| Pantalla | Ruta | Para qué sirve | Estado / límites |
| --- | --- | --- | --- |
| Inicio | `/dashboard` | Ver chats, avisos, altas, cargas y viajes que requieren atención; abrir listas desde cada indicador. | Implementado. Los indicadores secundarios están plegados. |
| Conversaciones | `/conversations` | Revisar chats abiertos, filtrar los que requieren operador o ubicaciones por confirmar y abrir un hilo. | Implementado; lista paginada. |
| Conversación | `/conversations/:conversationId` | Leer mensajes entrantes y salientes en orden, con fecha, emisor y estado disponible; cargar mensajes anteriores. | Implementado. No es una consola para responder libremente al chat. |
| Avisos | `/notifications` | Revisar mensajes salientes y estado de envío/reintento/error. | Implementado; no mostrar número ni contenido sensible. Reintentos dependen de la acción expuesta en pantalla. |
| Cargas sin transportista | `/shipments` | Ver cargas sin asignación activa; abrir detalle, editar, registrar interés manual o asignar transportista desde soporte. | Implementado. Acciones manuales son excepciones; no reemplazan aceptación del productor en flujo normal. |
| Detalle de carga | `/shipments/:shipmentId` | Ver datos, alertas/faltantes, respuestas, transportista elegido, viaje, historial y eventos; ejecutar acciones de operador disponibles. | Implementado. Eliminar es acción administrativa sensible y requiere confirmación del navegador. |
| Viajes | `/trips` | Filtrar por estado, editar, consultar la carga asociada, borrar y abrir seguimiento. | Implementado. Cambios de estado deben respetar la máquina de estados y el registro de eventos. |
| Seguimiento | `/trips/:tripId/tracking` | Confirmar contacto del chofer, pedir ubicación, calcular ruta orientativa, confirmar accesos y ver puntos/controles. | Implementado parcialmente según credenciales de mapas y estado del viaje. No es GPS continuo ni prueba de entrega. |
| Recorridos | `/route-availabilities` | Registrar recorrido, fechas, paradas, capacidad/equipo; activarlo/cerrarlo/cancelarlo y buscar coincidencias. | Implementado parcialmente. La búsqueda no crea oferta ni viaje; no completar datos omitidos por inferencia. |
| Productores | `/producers` | Buscar productores y abrir ficha. | Implementado; muestra datos disponibles, no un perfil supuesto. |
| Ficha de productor | `/producers/:producerId` | Consultar perfil y actividad vinculada: cargas, conversaciones, viajes y eventos. | Implementado con los datos existentes. |
| Transportistas | `/carriers` | Buscar por nombre, teléfono, empresa, CUIT o patente; filtrar estado y abrir ficha o alta manual. | Implementado. Alta/homologación aún tiene decisiones documentales pendientes. |
| Alta manual | `/carriers/new` | Cargar transportista desde soporte. | Implementado; no equivale a aprobación documental automática. |
| Ficha de transportista | `/carriers/:carrierId` | Revisar perfil, homologación, unidades, choferes, documentos y eventos; administrar estados según permisos. | Implementado parcialmente. Requisitos documentales/vigencias y retención siguen pendientes. |
| Estado del productor | `/producer-status` | Consultar operaciones con el teléfono usado en WhatsApp. | Implementado, ruta pública. Revisar autenticación/privacidad antes de exponer fuera del entorno controlado. |
| Estado del transportista | `/carrier-status` y `/carrier-status/:carrierId` | Consultar viajes actuales e historial; buscar transportista cuando no hay ID en la ruta. | Implementado, ruta pública. El acceso por ID requiere evaluación de autorización antes de exposición compartida. |
| Números autorizados | `/whatsapp-allowlist` | Administrar números de prueba autorizados por entorno. | Implementado para administración. Mantener allowlist cerrada; no usar número personal en producción. |
| Listas del sistema | `/catalogs` | Mantener provincias, partidos/departamentos, localidades, categorías, tipos y alias. | Implementado. Cambios de catálogo afectan nuevas interpretaciones; no reescriben ubicaciones históricas. |

La navegación lateral incluye Inicio, Conversaciones, Avisos, Cargas, Viajes, Recorridos, Productores, Transportistas, Números autorizados y Listas del sistema. El seguimiento se abre desde Viajes; las fichas desde sus listas.

## Recorridos de WhatsApp

WhatsApp es el canal; el backend valida identidad, permisos, estados, datos y eventos. Los mensajes pueden aparecer como botones/listas cuando el proveedor lo permite; siempre debe funcionar el texto alternativo.

### Productor: crear y publicar una carga — implementado

1. Iniciar el chat y pedir el menú («hola»/«menú») o escribir directamente el pedido.
2. Describir tipo de carga, cantidad y unidad cuando corresponda, origen, destino y fecha. El teléfono entrante identifica el contacto.
3. El backend extrae candidatos, normaliza localidades/fecha y pregunta faltantes o ambigüedades. Para granos no inventar unidad; para hacienda separar cabezas de kg por cabeza.
4. Mostrar resumen y pedir **Confirmar** o **Editar**. La vista previa aún no crea carga.
5. Confirmar: guardar, publicar si cumple mínimos y avisar a transportistas elegibles. Revisar evento y conversación en backoffice.
6. Editar: pedir qué dato cambia; volver a revisar el resumen antes de confirmar.

### Transportista: responder a una carga — implementado

1. Recibir aviso de oportunidad.
2. Responder `1` / «Me interesa», `2` / «No puedo» o `3` / «Más info» (o acción equivalente).
3. Backend registra oferta y evento. El primer interesado puede poner la carga en `MATCHING`.
4. Un texto ambiguo se deriva a soporte. Un interés repetido no debe duplicar la oferta.
5. El interés no asigna el viaje.

### Productor: elegir oferta y confirmar — implementado

1. Pedir «ver mis cargas» o «ver interesados».
2. Elegir carga; revisar ofertas vigentes y el transportista asociado.
3. Elegir una oferta y revisar la confirmación solicitada.
4. Confirmar explícitamente. Backend valida dueño, vigencia y estado; registra `Assignment.CONFIRMED`, crea `Trip.PLANNED` y cambia la carga a `ASSIGNED`.
5. Ambas partes reciben aviso. Revisar carga, viaje, chat y eventos en backoffice.

### Consultar cargas/viajes — implementado

El productor puede pedir sus cargas, interesados, viaje/estado. El resultado se limita al teléfono del productor. Si no hay registros, se informa; si falla el servicio, se deriva a soporte.

### Alta de transportista por WhatsApp — parcial

1. El transportista inicia alta y responde nombre/razón social, email (puede indicar que no tiene), empresa opcional, CUIT, cantidad de unidades, patente, equipo/carrocería, conductor, teléfono, categoría de licencia y adjunto.
2. Puede completar varias unidades/conductores, ver resumen, editar y confirmar.
3. Se guardan datos declarados y archivos; el perfil queda pendiente de revisión. No afirmar que está homologado ni habilitado hasta aprobación de soporte.
4. Soporte revisa perfil, unidades, conductores y documentos en la ficha; puede aplicar estados administrativos disponibles.
5. El conjunto obligatorio de documentos, vigencias, retención y reglas finales de aprobación está pendiente. Playwright debe verificar captura y estado pendiente; no asumir aprobación automática por archivo recibido.

### Audio, adjuntos y ayuda — parcial

- El webhook recibe texto y medios; el audio puede pasar por transcripción antes de entrar al mismo flujo conversacional. La transcripción es una entrada declarada, no una confirmación de dominio: aplicar las mismas preguntas, validaciones y confirmación que al texto. Si no se puede procesar el medio, pedir que lo reenvíen o derivar a soporte.
- Las imágenes/archivos del alta se asocian a la revisión del transportista/conductor. La recepción del archivo no decide aprobación.
- Saludo/«menú» muestra acciones disponibles por rol. Los mensajes interactivos tienen alternativa textual; una opción vieja o inválida debe volver a pedir opciones actuales.
- «Soporte» o una respuesta ambigua, conflicto, reclamo o falta de datos deriva a revisión humana. No resolver una cancelación conflictiva automáticamente.

### Transportista: recorrido disponible y preferencias — parcial

- Recorrido concreto: elegir «Recorrido», informar origen, destino, fecha, paradas o «sin paradas», capacidad con unidad, carga y equipo; revisar y guardar. La fecha sin horario cubre el día argentino. Se cancela con «cancelar». El recorrido no crea `Trip`.
- Preferencias habituales son otra función: expresan corredores de interés, no capacidad disponible para fecha cierta.
- Las preferencias de ruta se pueden consultar/administrar desde la ficha del transportista. No son una disponibilidad concreta y no deben prometer un camión para una fecha.
- Búsqueda por ruta, sugerencias parciales/de retorno y compromiso de capacidad dependen de las etapas marcadas en `docs/plan-y-bitacora.md`; no modelar el resultado de búsqueda como asignación.

### Viaje: seguimiento por WhatsApp — implementado parcialmente

Con chofer confirmado y viaje en estado válido, el sistema puede pedir controles de ubicación (salida, mitad, llegada) por WhatsApp. El chofer responde con ubicación; soporte ve controles vencidos. La posición reportada es puntual. La ruta de mapa es orientativa, no navegación apta garantizada para camiones.

### QA por WhatsApp

Solo fuera de producción, con `ENABLE_TEST_ROLE_SWITCHING=true` y el contacto permitido en allowlist: empezar cada caso con `/test iniciar`, cambiar con `/soy productor` o `/soy transportista`, terminar con `/test cerrar`. No reutilizar registros cerrados ni borrar datos generales. Mantener cada recorrido dentro de su escenario. No mandar mensajes reales sin autorización explícita y limitarse al chat Sandbox acordado.

## Estados y eventos a comprobar

- Carga: borrador/incompleta → validada/publicada → en búsqueda (`MATCHING`) → asignada → cerrada/cancelada, sujeto a transiciones válidas de `docs/08-state-machine.md`.
- Oferta: interesado/no puede; una consulta de información o ambigüedad puede requerir operador.
- Aceptación del productor: asignación confirmada + viaje planificado; el interés del transportista por sí solo no mueve a viaje confirmado.
- Recorrido disponible: activo/cerrado/cancelado, separado de `Trip`.
- Cambios relevantes deben dejar actor, fecha, entidad y evento auditable. Ver `docs/09-event-log-design.md`.

## Criterio UX/UI para siguientes cambios

- Una pantalla, una tarea principal; título de pocas palabras y una frase que explique qué hacer.
- Usar palabras de trabajo diario: «carga», «viaje», «chofer», «unidad», «aviso», «revisar». Dejar IDs, estados internos y explicación técnica en detalle plegable o historial.
- Mantener español argentino, controles con etiquetas visibles y errores que digan qué dato corregir.
- No esconder faltantes, incertidumbre, estado de envío ni intervención humana.
- Confirmar acciones críticas con nombres concretos (carga, transportista, viaje); no usar una confirmación genérica.
- Conservar vocabulario canónico en backend/modelo, aunque la interfaz lo explique en criollo. Consultar `docs/22-data-standardization.md` antes de cambiar catálogos o normalización.
