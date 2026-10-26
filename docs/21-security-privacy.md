# Security & Privacy Baseline

Este documento define el baseline de seguridad y privacidad para AGRO Logistics MVP.

No reemplaza una revision legal ni una politica formal de compliance. Define controles minimos para operar con conversaciones, ubicaciones, telefonos y datos comerciales.

## Datos Sensibles

| Tipo | Ejemplos | Riesgo |
| --- | --- | --- |
| Telefonos | Productores, carriers, operadores. | Suplantacion, spam, exposicion personal. |
| Ubicaciones | Origen, destino, establecimiento, referencias rurales. | Seguridad fisica y privacidad operativa. |
| Documentacion | Patentes, documentos operativos futuros. | Exposicion de datos personales/operativos. |
| Homologacion | CUIT, licencia de conducir, email y datos de flota/vehiculos. | Suplantacion, fraude y exposicion de identidad o activos. |
| Conversaciones | Mensajes WhatsApp, audios transcriptos. | Contienen datos no estructurados sensibles. |
| Datos comerciales | Precios, comisiones, condiciones. | Riesgo comercial y reputacional. |
| Tarifas | Estimadas o pactadas. | Confusion con precio final o filtracion comercial. |

## Controles Tecnicos

| Control | Baseline MVP |
| --- | --- |
| Validacion HMAC webhooks | Obligatoria para KAPSO/WhatsApp webhooks. |
| Auth para admin | Requerida antes de operar datos reales. |
| Clave interna | `INTERNAL_API_KEY` aleatoria de al menos 32 caracteres fuera de local/desarrollo; comparar en tiempo constante. |
| Roles | Separar productor/carrier/admin/sistema; admin es soporte, no paso obligatorio. |
| Logs sin datos sensibles innecesarios | No loggear raw messages completos salvo storage controlado. |
| Cifrado en transito | HTTPS/TLS obligatorio. |
| Backups | Backups de DB con acceso restringido. |
| Auditoria | `EventLog` obligatorio para decisiones y cambios de estado. |
| Rate limiting | Aplicar a webhooks, auth y endpoints admin. |
| Replay attacks | HMAC + timestamp + idempotency key + ventana de aceptacion. |

Antes de exponer el webhook de Kapso, el backend rechaza ambientes no locales si falta un secreto HMAC fuerte, la clave interna es corta/ausente o el allowlist permite acceso por defecto. Los encabezados de operador no reemplazan la clave interna.

## Politicas Operativas

### Retencion De Mensajes

- Preservar mensajes necesarios para auditoria y extraccion.
- Definir retencion antes de operar a escala.
- Evitar exponer `raw_content` en dashboards.

### Acceso Interno

- Principio de minimo acceso.
- Operadores ven lo necesario para coordinar.
- Datos comerciales y notas de confianza deben ser internos.
- Acceso administrativo debe quedar auditado.
- CUIT, patentes, licencia e imagenes documentales solo se muestran a personal autorizado que participa de homologacion; ocultar o minimizar esos datos en listados y vistas generales.
- Servir adjuntos desde almacenamiento privado con URLs temporales/autorizadas. No incluir su contenido ni enlaces de acceso en logs, eventos generales, mensajes de difusion o respuestas de IA.
- La vista de conversaciones conserva una cronologia util para soporte, con acceso por rol y escenario QA; no convertir el backoffice en una exportacion irrestricta de mensajes. El listado no muestra cuerpos completos: el detalle autenticado puede mostrar texto de mensajes; nunca devuelve contenido de medios ni identificadores/URLs del proveedor.
- Las respuestas salientes aceptadas por el proveedor quedan como mensajes de agente; un evento de fallo de respuesta se presenta como aviso del sistema. “Aceptado por el proveedor” no equivale a “entregado”: el acuse final no forma parte del modelo actual.
- En desarrollo local, los headers de operador son una identidad ficticia de QA. En entornos compartidos, `INTERNAL_API_KEY` autentica solo integraciones backend y el servidor asigna un principal de servicio fijo; los headers de usuario/rol del cliente se ignoran. La clave nunca se expone con variables `VITE_*` ni se entrega al navegador.
- El backoffice humano aun no tiene autenticacion en entornos compartidos. Antes de habilitar datos reales, integrar Supabase Auth: verificar en backend firma, issuer, audience y vencimiento del JWT; tomar el ID de `sub`; obtener roles desde `app_metadata` o una tabla administrada por servidor (nunca de `user_metadata` ni headers); permitir solo `operator`/`admin`; y auditar las lecturas de conversaciones y datos documentales. Hasta entonces, el backoffice humano debe usarse solo en local.
- La ficha de productores agrega relaciones operativas, pero cada campo conserva su nivel de sensibilidad y permisos; mostrar faltantes en vez de derivar datos.

### Handoff Humano

- Handoff no debe exponer mas datos que los necesarios.
- Operador debe ver contexto, source message y riesgos.
- Toda decision tomada en handoff genera `EventLog`.

### Exportacion De Datos

- Exportaciones deben ser manuales/controladas en MVP.
- No exportar conversaciones completas salvo necesidad justificada.
- Sanitizar datos personales cuando se use para analisis externo.

### Eliminacion / Anulacion Futura

- MVP usa soft delete para preservar auditoria.
- Cancelacion de viaje/carga no es eliminacion de dato.
- Futuro: definir politica de anonimizacion o anulacion segun necesidad legal.

## Riesgos

| Riesgo | Descripcion | Mitigacion |
| --- | --- | --- |
| Filtracion de ubicacion | Origen/destino o establecimiento expuesto indebidamente. | Minimizar datos en alerts y controlar acceso. |
| Suplantacion de WhatsApp | Webhook falso o numero no verificado. | HMAC, idempotencia, mapeo de usuario y auditoria. |
| Error de AI | Extraccion o clasificacion incorrecta. | Backend decide, flags de confianza y soporte humano. |
| Asignacion incorrecta | Confirmacion sin doble aceptacion o por actor incorrecto. | Ownership por telefono, offer `INTERESTED`, idempotencia y EventLog. |
| Abuso de templates/broadcast | Spam o mensajes fuera de contexto. | Backend decide outbound y registra eventos. |

## Reglas Para Logs

- No incluir telefonos completos en logs tecnicos si no es necesario.
- No incluir ubicaciones detalladas en errores genericos.
- No incluir `raw_content` en traces de observabilidad.
- Usar `correlation_id` para debugging.
- Guardar payloads sensibles solo en storage transaccional controlado.

## Seguridad De Webhooks

- Validar HMAC antes de procesar.
- Validar timestamp para reducir replay.
- Persistir `idempotency_key`.
- Rechazar payloads sin estructura minima.
- Procesar async luego de validacion.
- DLQ con acceso restringido porque puede contener datos sensibles.

## Seguridad De AI

- No enviar mas contexto del necesario al proveedor AI.
- Para STT, enviar solo el audio necesario para transcribir el mensaje operativo.
- No permitir que AI confirme decisiones criticas.
- Guardar outputs con confianza y trazabilidad.
- Registrar correcciones humanas para auditoria y mejora.
- Si AI falla o devuelve baja confianza, escalar a humano.

## Seguridad De Admin Futuro

- Auth obligatoria.
- Roles y permisos por accion.
- Audit trail de cambios.
- Rate limit y session timeout.
- Ocultar datos sensibles por defecto cuando no sean necesarios.

## Datos Documentales De Homologacion

- Validar tipo y tamano de archivos, controlar acceso y registrar quien los consulto/reviso.
- No considerar recibido = aprobado ni inferir vigencia/validez desde una imagen. Soporte registra resultado y motivo.
- Definir retencion, renovacion/vencimiento y eliminacion/anonimizacion antes de activar captura de licencias en una operacion real.
- La matriz documental y las bases/obligaciones aplicables requieren definicion de producto y revision legal/operativa antes de habilitar aprobacion automatica; por ahora la decision es humana.

### Implementacion Actual De Descargas

- Las respuestas de detalle/listado de Carrier ya no incluyen `external_uri` ni `storage_uri`.
- El backoffice descarga archivos locales por endpoint autenticado de operador; el servidor comprueba que el documento pertenezca al Carrier solicitado (directamente o a uno de sus Drivers/Vehicles), limita la ruta al directorio `MEDIA_STORAGE_DIR`, responde como adjunto y aplica `Cache-Control: private, no-store`.
- Cada descarga exitosa agrega `CARRIER_DOCUMENT_ACCESSED` sin copiar ruta ni URL al evento. Los enlaces externos no se abren ni se descargan desde el backend.
- Los documentos manuales del backoffice pueden asociarse a Carrier, Driver o Vehicle, y la ficha muestra cada documento bajo su entidad. Asociar o revisar un documento no aprueba por si solo Driver/Vehicle. El alta por WhatsApp ya tiene captura progresiva en borrador: la asociacion de la licencia solo se permite durante el paso de licencia del onboarding abierto y el Driver debe pertenecer al Carrier del mensaje. El backend conserva la revision humana; la matriz documental, vencimientos y retencion siguen pendientes. Usar adjuntos ficticios en Sandbox.
- El contexto de captura se persiste en el onboarding, aislado del rol de productor/transportista del chat. El flujo acepta un adjunto como licencia solo cuando se espera esa licencia; otros medios del chat no se vinculan automaticamente. Esta regla reduce asociaciones accidentales, pero no reemplaza autenticacion del titular ni controles de contenido/retencion antes de recibir documentos reales.
- Las aprobaciones de Driver/Vehicle se registran separadas del Carrier y requieren una nota del operador. La nota deja constancia de la revision humana, pero no representa una lista obligatoria de documentos ni un control legal automatizado.

## Decisiones Tecnicas Tomadas

1. HMAC obligatorio para webhooks.
2. EventLog como auditoria principal.
3. Soft delete para preservar historia.
4. Raw messages con acceso restringido.
5. AI nunca confirma acciones criticas.

## Riesgos Tecnicos

1. Logs con datos sensibles por error.
2. Handoff humano sin suficiente control de acceso.
3. Replay attacks si no se valida timestamp/key.
4. Broadcasts mal gobernados afectando confianza.
5. Backups sin cifrado o permisos adecuados.

## Que Implementar Primero

1. HMAC + idempotencia + replay protection para webhooks.
2. Auth/roles minimos para endpoints admin.
3. Politica de logging seguro y EventLog obligatorio.
