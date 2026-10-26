# Outbox transaccional de notificaciones

## Objetivo

Una confirmacion de negocio y la intencion de notificar deben guardarse en una sola transaccion SQL. El proceso web no envia mensajes a WhatsApp en esa transaccion. Un proceso separado toma las filas pendientes y llama al proveedor despues del commit.

## Flujo y estados

1. El servicio de negocio valida/actualiza carga, oferta, asignacion o viaje.
2. El adaptador `SqlNotificationOutboxProvider` persiste el mensaje y su clave idempotente en `notification_outbox`, usando la misma sesion SQL. El evento de negocio y la fila outbox comparten commit/rollback. Cada fila conserva por separado la correlacion funcional y la clave de envio, junto con la sesion, rol y escenario QA resueltos al encolar.
3. `scripts/dispatch_notification_outbox.py` procesa filas `PENDING` y `RETRY` fuera de la transaccion web.
4. Una aceptacion del proveedor deja `ACCEPTED`, registra el identificador del proveedor, el evento de auditoria y, cuando la sesion se resolvio al encolar, el mensaje saliente en ese hilo exacto. El evento conserva las referencias a la carga y los botones para enrutar la respuesta del transportista.
5. Un rechazo explicito vuelve a `RETRY` con espera exponencial y hasta cinco intentos; agotados, queda `FAILED`.
6. Una excepcion de red o un worker interrumpido deja `RECONCILE_REQUIRED`. No se reenvia automaticamente: Kapso podria haber aceptado el mensaje antes de perderse la respuesta. Esto prioriza no duplicar por sobre el reintento ciego. Un operador debe comprobar la entrega antes de una accion manual.

Estados: `PENDING`, `PROCESSING`, `RETRY`, `ACCEPTED`, `FAILED`, `RECONCILE_REQUIRED`, `CONFIGURATION_MISMATCH`, `CANCELLED`.

Al cerrar un escenario QA, solo se cancelan de forma condicional las filas
`PENDING`/`RETRY` que todavia no comenzo a procesar ningun worker. Las filas
`PROCESSING` quedan para conciliacion porque el proveedor puede haber recibido
el pedido; `ACCEPTED` y sus evidencias se conservan. Una respuesta tardia sigue
asociada a la conversacion y escenario originales del momento de encolado.

Cada fila conserva el identificador no secreto del phone number de Kapso usado al encolarla. El worker verifica que proveedor y cuenta coincidan con la configuracion activa; si cambiaron, detiene la fila en `CONFIGURATION_MISMATCH` en vez de enviarla por otro numero.

La clave de envio unica evita encolar dos veces un mismo mensaje; reutilizarla con un payload distinto genera error. No garantiza entrega exactamente una vez en WhatsApp: el proveedor no ofrece aqui una clave de idempotencia saliente documentada. Por eso la ventana de resultado de red desconocido necesita conciliacion humana.

## Operacion

El backoffice local incluye una vista protegida de consulta para ver cantidades por estado y filas paginadas. Presenta proveedor, tipo de aviso, operacion, intentos y un codigo de error acotado; no devuelve el cuerpo, telefono, phone number ID ni identificador del proveedor. La conciliacion permite al rol `admin` registrar una referencia de evidencia, confirmar que el proveedor acepto el aviso o autorizar un reintento despues de comprobar que no hubo envio. Las dos decisiones generan auditoria; no representan un acuse de entrega de WhatsApp.

La migracion `0009_notification_outbox` esta creada y fue verificada en un PostgreSQL Docker descartable junto con las revisiones posteriores; **no se aplico a ninguna base del proyecto**. Antes de habilitar el modo SQL hay que aplicar y verificar migraciones por el proceso normal del entorno. Para despachar se ejecuta un worker aparte con el mismo entorno de aplicacion:

```bash
python scripts/dispatch_notification_outbox.py
```

Para una corrida puntual:

```bash
python scripts/dispatch_notification_outbox.py --once
```

El worker requiere `STORAGE_BACKEND=sql` y la configuracion ya administrada del proveedor. No se debe iniciar antes de validar el destino y la allowlist del entorno; no se configura ni ejecuta desde este cambio.

El cuerpo del mensaje queda almacenado en la outbox hasta resolverse, ya que es necesario para el envio/reintento. Aplican los controles de acceso, respaldo y retencion de la base de conversaciones. Los logs del worker solo muestran el resultado/estado y no imprimen el texto ni el telefono.

## Limitaciones pendientes antes de produccion

- La conciliacion se implemento y probo localmente; falta validar la operacion con evidencia real de Sandbox. El operador debe verificar Kapso antes de decidir y el sistema no presenta aceptacion como entrega/lectura.
- Debe desplegarse y monitorizarse el worker junto con la API; sin worker, se acumulan notificaciones `PENDING`.
- No se conoce una clave de idempotencia saliente de Kapso que permita reintentar resultados ambiguos sin riesgo de duplicado.
- La migracion no se aplico a una base del proyecto; upgrade/downgrade/upgrade paso en PostgreSQL descartable.
- El contexto inmutable y la conciliacion se probaron en SQLite temporal; falta prueba de concurrencia PostgreSQL y navegacion visual del backoffice.
- La cancelacion de mensajes no iniciados al cerrar QA se probo con SQLite temporal; los intentos ya iniciados se conservan. La migracion y el worker permanente siguen pendientes.
