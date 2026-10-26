# Recorridos, difusión y seguimiento

Bloque autorizado el 25/10/2026. La implementación usa Google como estimador orientativo; los puntos de WhatsApp son posiciones declaradas, no GPS continuo ni prueba de entrega.

## Operación

1. Aplicar las migraciones explícitamente, con el API y los workers detenidos y respaldo previo de la base seleccionada. La revisión nueva es `0019_route_operations`, sucesora de `0018_jauregui_geo_localities`. No ejecutar una instalación nueva con `create_all` ni modificar tablas al iniciar el API.
2. Configurar las claves Google en el entorno del backend: `GOOGLE_ROUTES_API_KEY` (solo servidor), `GOOGLE_MAPS_BROWSER_KEY` (pública, restringida a sitios autorizados), `GOOGLE_ROUTES_DAILY_LIMIT` (100 por defecto). En Sandbox, el proyecto `agro-logistics-sandbox-2026` tiene facturación vinculada y Routes API y Maps JavaScript habilitadas. La clave vigente `AGRO Routes Backend Sandbox 2026-10-26` solo admite Routes API y no tiene restricción por IP porque el backend corre localmente; no usarla desde un servidor público. `AGRO Maps Web 5175` solo admite Maps JavaScript API y está restringida a `http://127.0.0.1:5175/*` y `http://localhost:5175/*`. Las dos claves están guardadas en el `.env` local; nunca copiar la clave Routes al navegador ni registrar valores secretos en documentación. Antes de desplegar, restringir Routes por la IP de egreso estable. La cuota de ComputeRoutes está limitada a 100 solicitudes por día tanto en Google como en la aplicación. El seguimiento manual sigue disponible si Google no responde.
3. Iniciar API en loopback y el backoffice habitual. El acceso compartido sigue condicionado a Auth real; las identidades de desarrollo no habilitan exposición pública.
4. Iniciar **un worker de recorridos** y el despachador de outbox existente. Para procesar solo tareas vencidas una vez:

```sh
.venv/bin/python scripts/run_route_worker.py --once
.venv/bin/python scripts/dispatch_notification_outbox.py --once
```

Para operación continua:

```sh
.venv/bin/python scripts/run_route_worker.py --poll-seconds 2
.venv/bin/python scripts/dispatch_notification_outbox.py --poll-seconds 2
```

5. Declarar disponibilidades con localidad y provincia. Las paradas de WhatsApp se separan con **punto y coma**, para conservar la coma entre localidad y provincia. Usar el escenario QA al cargar registros de prueba en backoffice.
6. Confirmar el WhatsApp del chofer asignado en **Viajes → Seguimiento**. Al cambiar chofer o teléfono se exige nueva confirmación. El contacto de empresa conserva su función comercial.
7. Pasar el viaje a **En tránsito**. El worker calcula la ruta, prepara el aviso y pide ubicación de salida. Si Google falla, soporte ve el cálculo pendiente; puede reintentarlo desde **Calcular recorrido**.
8. Revisar `/api/v1/backoffice/routing/status`, Avisos y el seguimiento. Un control sin respuesta recibe un recordatorio a los 15 minutos y queda pendiente para soporte a los 30. La mitad y la llegada estimada dependen del cálculo inicial; sin estimación se requieren controles manuales hasta resolverla.

Los trabajos se guardan en `routing_operations`, con tipo, entidad, escenario, estado, fecha de ejecución e índices. El worker usa transacciones y bloqueos de PostgreSQL; un reinicio anterior al commit conserva el trabajo pendiente. Los envíos se realizan desde la outbox después del commit. Un resultado ambiguo del proveedor exige conciliación, sin reenvío ciego.

## Comandos de WhatsApp

Los comandos conservan alternativa textual a los botones.

- `mis recorridos` o `recorridos habituales`: listar preferencias y pausar/activar desde las opciones.
- `agregar recorrido habitual`: origen → destino → paradas → categoría o tipo → equipo → autorización de avisos → confirmación. También se puede declarar durante el registro; no bloquea homologación.
- `informar disponibilidad`: recorrido concreto, fecha, capacidad y unidad. Es independiente del habitual.
- `/ubicacion origen <id_carga>` y `/ubicacion destino <id_carga>`: el productor titular comparte el punto exacto del acceso. El operador también puede confirmar un punto haciendo clic en el mapa del viaje.
- `/viaje <id_viaje> ubicacion`: solicita otro control de ubicación para el chofer confirmado.
- `/viaje <id_viaje> llegue`: el chofer confirmado informa llegada y recibe el control final. No confirma entrega.
- `/viaje <id_viaje> ayuda`: registra solicitud de ayuda para soporte.
- `/ubicacion <id_reporte> <id_control>`: alternativa textual a seleccionar el control correspondiente a un punto sin mensaje citado.

Si la ubicación cita una solicitud anterior, se conserva en su escenario de origen. Si no hay cita, el usuario debe elegir explícitamente el control. No se asignan puntos al último viaje por inferencia. Los webhooks duplicados no crean otro reporte.

## Selección de destinatarios

- La difusión nueva usa disponibilidades activas y aprobadas: mismo tramo y sentido, fecha dentro de ventana, tipo y capacidad compatibles. Cuando se declara un equipo requerido, se filtra también por él; si no se declaró, queda para confirmación operativa.
- Los nodos se comparan por ID canónico; homónimos o localidades desconocidas requieren corrección. Los puntos exactos y centroides nunca inventan paradas ni compatibilidad por cercanía.
- Sin disponibilidad compatible se usan inmediatamente recorridos habituales activos y autorizados. Si hubo disponibilidad, se amplía a los 30 minutos sin interés vigente. Rechazos y consultas no bloquean la ampliación.
- Cada carga/transportista tiene una decisión registrada. Antes de enviar, el worker revalida carga abierta, aprobación, recorrido y escenario. Backoffice diferencia encolado de aceptación por proveedor; no presume entrega o lectura.
- La aceptación reserva una sola disponibilidad para una carga bajo bloqueo, dentro de la transacción que crea la asignación. Se cancelan ampliaciones pendientes. Una cancelación no libera automáticamente capacidad.
- Sin destinatarios nuevos se informa al productor y se deriva a soporte. No se realiza difusión general.

## API y persistencia

Recursos nuevos bajo `/api/v1/backoffice`, todos con autenticación de operador y contexto `test_run_id` explícito para QA:

- `GET/POST /carriers/{id}/route-preferences`, `PUT .../{preference_id}`.
- `GET /shipments/{id}/dispatch`, `PUT /shipments/{id}/route-requirements`.
- `PUT /shipments/{id}/locations/{origin|destination}`.
- `GET /trips/{id}/tracking`, `POST .../confirm-driver`, `POST .../request-location`, `POST .../route`.
- `GET /routing/config`, `GET /routing/status`. La configuración solo expone la clave pública de Maps, nunca la clave de Routes.

El webhook agrega `location` y referencia al mensaje citado de forma aditiva. La ubicación se valida como coordenadas finitas. Cada lectura del seguimiento registra auditoría.

Los puntos propios quedan separados de la geometría Google. El contenido temporal de rutas vence a las 24 horas y el worker lo purga; las vistas no muestran geometría vencida. Conservar las atribuciones de Google y monitorear el worker de limpieza. El historial propio QA se preserva. No publicar una política de retención de datos reales a partir de esta demo.

## Pruebas y límites

### Proyecto Google preparado

Proyecto Sandbox: `agro-logistics-sandbox-2026` (nombre **AGRO Logistics Sandbox**, número `610444033637`). Creado el 25/10/2026 en la cuenta indicada por el usuario. El estado vigente de facturación, APIs, claves y cuotas se registra en las entradas fechadas de la bitácora; el historial de preparación que sigue describe los estados que se observaron en cada fecha.

Al completar la facturación, habilitar únicamente Routes y Maps JavaScript para este bloque. Crear una clave privada restringida a Routes y otra de navegador restringida a Maps JavaScript y a los orígenes exactos del backoffice local. Confirmar los puertos antes de definir los referentes. Para Routes, restringir también la IP de salida cuando se identifique; un cambio de IP requiere actualizar esa restricción, no quitarla. No reutilizar credenciales de otros proyectos.

El entorno declara un límite interno de 100 cálculos diarios. No es un límite de gasto de Google y no incluye visualizaciones de Maps; configurar además cuotas del proveedor y avisos de presupuesto. Estos últimos avisan, no detienen el consumo.

- Regresión en memoria y SQLite con proveedor mock y transporte HTTP simulado. La suite nueva cubre permisos, escenarios, altas de preferencias, selección, expansión, reservas, controles, errores y ubicación tardía/duplicada.
- Prueba integrada con webhooks HMAC ficticios: publicación, interés, aceptación con confirmación, reserva, asignación de chofer/unidad, tránsito y recepción del punto desde un teléfono de chofer distinto.
- PostgreSQL descartable: cadena de migraciones, reversión/subida de 0019, dos reservas concurrentes y dos workers concurrentes. Pruebas opt-in solo si `AGRO_QA_POSTGRES_URL` apunta a loopback y base `agro_route_qa`.
- Los casos históricos de difusión explícita usan una fixture que deshabilita la función nueva para seguir probando sus adaptadores. Los casos nuevos verifican el comportamiento dirigido con la función habilitada.
- Google real requiere credenciales/facturación. Sandbox admite mensajes interactivos, pero no permite validar plantillas ni múltiples destinatarios. No contar simulaciones como entregas reales.

Demo visual enteramente ficticia, sin credenciales ni servicios externos:

```sh
LOCAL_DEMO_API_PORT=58400 .venv/bin/python scripts/run_routing_demo.py
VITE_API_BASE_URL=http://127.0.0.1:58400 VITE_SUPABASE_URL='' VITE_SUPABASE_ANON_KEY='' npm run dev --prefix frontend -- --host 127.0.0.1 --port 58401 --strictPort
```

Abrir `/trips/trip_demo_planificado/tracking?test_run_id=qa_demo_20261010`. Los kilómetros de esta demo son sintéticos y no provienen de Google. Al terminar, detener ambos procesos; la memoria desaparece. Para comprobar el mapa real se necesita la clave pública configurada.

### Resultado local 2026-10-25

426 pruebas aprobadas, 7 avisos de deprecación. Build frontend aprobado; PostgreSQL descartable completó instalación, reversión/subida de 0019 y comprobación de esquema sin diferencias. Se revisó el backoffice en Chrome normal con datos ficticios. Estas verificaciones no acreditan conexión ni entregas reales de Google/Kapso.
