# Alcance Del MVP

El MVP de AGRO Logistics coordina por WhatsApp cargas de hacienda y granos entre productores/comisionistas y transportistas, con backoffice para seguimiento y soporte. Este documento define el alcance de producto; la bitacora lleva prioridades y avances, y el modelo de dominio define los conceptos.

La regla principal es simple: el productor publica, los transportistas responden, el productor elige y el backend confirma el match. El admin existe para soporte y excepciones, no como paso obligatorio del flujo feliz.

## Incluye

| Funcionalidad | Descripcion |
| --- | --- |
| Publicacion de carga via WhatsApp | El productor o comisionista crea y confirma una solicitud desde WhatsApp. |
| Captura de datos guiada | El backend extrae tipo, cantidad y unidad, origen, destino y fecha; pregunta por campos requeridos faltantes. Para granos, nunca infiere la unidad: si se informó cantidad sin unidad, la pregunta antes de confirmar. En hacienda, el pesaje declarado por cabeza se muestra y guarda separado de la cantidad de animales. El contacto se toma del WhatsApp entrante y no es un campo obligatorio que se pregunta. |
| Normalizacion de fechas relativas | Interpretar dias de semana contra la fecha actual de Argentina y mostrar la fecha concreta (DD/MM/AAAA) antes de confirmar. Un dia igual al de hoy, expresado sin "hoy", se toma como su proxima ocurrencia semanal. |
| Hacienda y granos basicos | El MVP soporta hacienda y granos como soja, maiz, trigo, girasol, sorgo y cebada. |
| Publicacion self-service | Si la carga tiene datos minimos, el backend la publica sin operador a transportistas aprobados y elegibles. |
| Broadcast a transportistas | El sistema envia oportunidades a transportistas homologados/aprobados y compatibles con los criterios de busqueda. |
| Registro de interesados | Respuestas `1 Me interesa`, `2 No puedo` y `3 Mas info` quedan asociadas a la carga. |
| Eleccion por productor | El productor ve sus cargas en una lista interactiva con recorrido, fecha, cantidad de interesados y estado; al elegir una, consulta las ofertas y confirma expresamente la aceptacion de un transportista por WhatsApp. |
| Match confirmado | Backend crea `Assignment.CONFIRMED` y `Trip.PLANNED` cuando carrier y productor aceptaron. |
| Aviso de viaje planificado | Al confirmarse el match, el sistema avisa al productor y al transportista. El aviso al transportista no expone IDs internos. |
| Soporte/admin | Admin interviene en ambiguedades, reclamos, cancelaciones conflictivas y correcciones. |
| Event logging | Se registran eventos importantes durante todo el flujo. |
| Disponibilidad de recorrido del transportista | El transportista informa ruta, fechas/ventana, capacidad libre, unidad, equipo y paradas o desvio que acepta. Esta disponibilidad no crea un `Trip` ni una asignacion. |
| Busqueda por ruta y preferencias | El transportista consulta oportunidades entre zonas/fechas y configura zonas de interes para recibir avisos. Preferencias y disponibilidad concreta se guardan como conceptos separados. |
| Alternativas de retorno/carga parcial | El sistema puede sugerir cargas sobre el corredor o cerca de paradas/desvios aceptables; muestra la alternativa y requiere respuesta del transportista. No optimiza ni cambia una ruta por su cuenta. |
| Solicitud de homologacion por WhatsApp | El transportista puede iniciar y completar una solicitud como persona independiente o como empresa/flota. El perfil puede tener uno o varios conductores y vehiculos; licencia se asocia al conductor y datos/documentos del vehiculo a cada unidad. Soporte revisa y deja una decision auditable en backoffice. La matriz documental sigue pendiente. |
| Conversaciones en backoffice | Operadores pueden abrir el hilo cronologico con mensajes del usuario y del agente, emisor, fecha/direccion y estado de entrega disponible. |
| Productores en backoffice | Listado y ficha relacionan perfil disponible, cargas, ofertas, asignaciones/viajes, eventos y conversaciones, sujeto a permisos. |
| Interfaz de operación en español | Etiquetas, validaciones y mensajes nuevos del sistema se presentan en español argentino; los mensajes históricos y los textos escritos por personas se conservan. |
| Conversaciones paginadas | La bandeja permite navegar páginas y cada hilo carga inicialmente los últimos 50 mensajes, con carga progresiva de mensajes anteriores. |
| Catálogos administrables | Provincias, partidos/departamentos y localidades se mantienen en tablas de referencia editables desde backoffice. Categorías y tipos de carga tienen ABM, alias y estado activo; el backend los comparte con parser y agente para nuevas cargas. |

## No Incluye

| Fuera Del MVP | Motivo |
| --- | --- |
| Pagos dentro de la app | Agrega complejidad legal, financiera y operativa. |
| GPS continuo | El seguimiento se realiza con puntos enviados por el chofer por WhatsApp. |

| Optimizacion avanzada | Antes se necesita historial y aprendizaje operativo. |
| Pricing automatico definitivo | El precio requiere contexto local y queda fuera del match inicial. |
| App mobile | WhatsApp es el canal principal para reducir friccion. |
| Asignacion por interes unilateral | Carrier interesado no confirma viaje; el productor debe aceptar. |
| Operador obligatorio para cada carga | El flujo feliz de carga debe funcionar sin revision manual previa; la homologacion del transportista si requiere revision de soporte. |
| GPS y optimizacion automatica de rutas | El MVP muestra alternativas de compatibilidad; no rastrea ni altera recorridos en tiempo real. |

## Regla Clave

El sistema es self-service con soporte humano.

Esto significa:

- El backend extrae y normaliza los datos, pregunta por campos requeridos faltantes y presenta la fecha concreta antes de confirmar. El teléfono entrante ya identifica al productor.
- El backend publica automaticamente cargas con datos minimos.
- El transportista expresa interes, rechazo o pide mas informacion.
- Al consultar cargas, el productor puede elegir una carga concreta para ver sus ofertas; la aceptacion identifica esa oferta y carga, muestra el transportista y pide confirmacion explicita antes de crear el match. Las respuestas interactivas deben tener una alternativa textual y validar pertenencia, escenario y vigencia de la oferta.
- El transportista tambien puede publicar una disponibilidad concreta o consultar cargas por ruta; eso no equivale a tener una asignacion.
- El telefono WhatsApp identifica al contacto, no necesariamente a la empresa transportista ni al conductor que ejecutara el viaje.
- Un carrier aprobado puede recibir oportunidades; antes de iniciar el viaje deben identificarse el conductor y el vehiculo asignados y cumplirse los requisitos de revision acordados.
- El productor acepta una oferta.
- El backend registra el match, assignment, trip y eventos.
- El admin solo interviene si hay excepciones o soporte.
- Las ubicaciones se comparan con los datos declarados y catálogos disponibles. Hasta integrar un proveedor de mapas, no se calculan distancias de carretera ni desvíos en kilómetros.

## Limites De Automatizacion

El MVP no debe automatizar:

- Asignacion por el solo hecho de que un transportista responda `1`.
- Precio final.
- Resolucion de cancelaciones conflictivas.
- Cambios criticos de origen, destino, fecha o cantidad sin trazabilidad.
- Priorizacion definitiva entre transportistas sin aceptacion del productor.

Cuando exista duda, conflicto o informacion incompleta, el flujo debe pedir soporte humano.

## Criterio De Exito Inicial

El MVP funciona si permite:

- Tomar una solicitud real por WhatsApp.
- Publicarla a transportistas registrados.
- Registrar interesados.
- Mostrar interesados al productor.
- Permitir que el productor acepte una oferta.
- Crear `Assignment.CONFIRMED` y `Trip.PLANNED`.
- Dejar historial claro de lo ocurrido.
- Capturar solicitudes de homologacion, revisarlas en soporte y distinguir transportistas aprobados de pendientes.
- Consultar disponibilidad por ruta y sugerir cargas parciales sin modificar una ruta sin aceptacion.
- Consultar desde backoffice productores, conversaciones y su historial operativo relacionado.

## Decisiones De Alcance Pendientes

- Catalogos, unidades y capacidad aplicables por tipo de carga/vehiculo.
- Documentos exigidos por transportista y por vehiculo, vigencias, criterios de revision, retencion y permisos de acceso.
- Limites de desvio (distancia/tiempo), cantidad de paradas y criterio de caducidad de una disponibilidad.
- Si se permiten oportunidades con multiples cargas/asignaciones parciales sobre una misma disponibilidad y como se reserva/libera capacidad.
- Campos de perfil de productor que soporte necesita y cuales son visibles para cada rol.

No iniciar implementacion de reglas que dependan de estas decisiones como si ya estuvieran definidas; capturar candidatos y escalar a soporte.

## Mapas y distancia por carretera: bloque autorizado

El bloque autorizado completa localidades con coordenadas y procedencia, pedir precisión cuando haya homónimos, y calcular rutas conservando el orden de paradas. Un candidato a evaluar es [Google Routes](https://developers.google.com/maps/documentation/routes/compute-route-over); antes de habilitarlo habrá que revisar [precios, cuotas y facturación](https://developers.google.com/maps/documentation/routes/usage-and-billing), límites de gasto y comportamiento cuando el proveedor no responda. No hay proveedor elegido ni integración o facturación configurada.

Para comparar retornos, primero se filtra por fecha, carga, equipo y capacidad. Después se estima el desvío como kilómetros de la ruta con retiro/entrega menos kilómetros del corredor declarado. El bloque de difusión dirigida autorizado genera avisos solo para tramos declarados compatibles; las coincidencias por desvío siguen fuera de esta etapa. El transportista y el productor deben aceptar antes de confirmar el viaje.

## Bloque autorizado: recorridos y seguimiento

- Google Routes y Google Maps brindan una ruta orientativa al pasar a IN_TRANSIT; no garantizan aptitud del camino para camiones. El paso a LOADING_PENDING no inicia controles.
- Coordenadas exactas declaradas prevalecen sobre centroides Georef, identificados como aproximados. Los homónimos requieren aclaración.
- Seguimiento del chofer asignado y confirmado: salida, mitad del tiempo inicial y llegada. Recordatorio único a los 15 minutos, pendiente para soporte a los 30; nunca se inventan ubicaciones ni se confirma entrega por GPS.
- Difusión: disponibilidades compatibles primero, preferencias de recorridos habituales si no hay coincidencias o a los 30 minutos sin interés vigente. Solo tramos en el sentido de las paradas declaradas; no hay proximidad automática ni difusión general.
- Aceptar una oferta compromete una disponibilidad vinculada por transacción y cancela ampliaciones. Una carga por disponibilidad.
- Implementar y probar primero en local/Sandbox; Google real depende de credenciales y facturación. Se conserva OpenAI en backend.
