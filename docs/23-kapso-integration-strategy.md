# Estrategia De Integracion KAPSO

Este documento define como usar KAPSO en AGRO Logistics MVP sin romper el dominio ni mover logica de negocio fuera del backend.

KAPSO se usa como canal WhatsApp reemplazable. La conversacion y la IA se ejecutan en el backend, que llama OpenAI con credenciales propias.

## Regla Principal

KAPSO es canal. Backend es conversacion, logica y estado. OpenAI interpreta y extrae candidatos; el dominio valida reglas y cambios.

## Que Usamos En MVP

| Capacidad KAPSO | Uso permitido | Justificacion |
| --- | --- | --- |
| Webhooks | Recibir mensajes, eventos de workflow, flows y handoff. | Necesario para conectar WhatsApp con backend. |
| Workflows | No se ejecutan para responder conversaciones AGRO. | Evita respuestas duplicadas y consumo de IA de Kapso. |
| Flows estructurados | Diferidos en esta etapa. | La captura conversacional la coordina el backend. |
| Agent nodes | No se usan para AGRO. | OpenAI se invoca desde backend y la clave no se copia a Kapso. |
| Handoff humano | Pasar conversacion a soporte/admin. | Necesario para datos ambiguos, cancelaciones y excepciones. |
| Mensajes y adjuntos de homologacion | Transportar respuestas/medios hacia el backend para captura y revision. | Kapso no decide si documentos o transportistas estan aprobados. |
| Opciones interactivas | Facilitar menus y respuestas acotadas con fallback textual. | Cada accion se valida en backend; los botones no son autorizacion ni decision de negocio. |

## Que NO Usamos

| Capacidad | Motivo |
| --- | --- |
| Logica de negocio en workflows | Rompe source of truth del backend. |
| Functions criticas | Podrian decidir pricing, matching, estados o asignaciones fuera del dominio. |
| Broadcasts como core | El backend decide seleccion, trazabilidad y eventos. |
| Persistencia de estado de negocio | KAPSO no es owner de `LivestockLoad`, `Offer`, `Assignment`, `Trip` ni `EventLog`. |
| Pricing automatico | Fuera del MVP como decision final. |
| Matching unilateral | Carrier interesado no asigna viaje; productor debe aceptar la oferta. |

## Division De Responsabilidades

| Capa | Responsabilidad |
| --- | --- |
| KAPSO | Transporte WhatsApp |
| Backend | Conversacion, logica + estado |
| OpenAI | Interpretacion y extraccion invocadas desde backend |
| Dominio | Reglas |

Detalle:

- KAPSO transporta mensajes; el backend contesta por el adaptador de WhatsApp.
- Backend crea y actualiza `ConversationSession`, `Message`, `LivestockLoad`, `Offer`, `Assignment`, `Trip` y `EventLog`.
- Backend tambien administra solicitudes de homologacion, preferencias y disponibilidad de recorrido; KAPSO solo transporta interacciones y referencias a media.
- Una respuesta sobre disponibilidad o una sugerencia de retorno no crea un viaje confirmado por si sola.
- OpenAI extrae candidatos a datos; el backend aplica permisos y reglas.
- Dominio valida estados, datos criticos y reglas del MVP.

## Politica Outbound

Cada envio saliente debe clasificarse antes de salir del backend.

| Tipo | Cuando usar | Owner de decision | Reglas |
| --- | --- | --- | --- |
| Mensaje libre | Hay ventana activa de conversacion y respuesta contextual. | Backend | No debe confirmar viajes sin doble aceptacion. |
| Template | Fuera de ventana activa o para notificacion aprobada. | Backend | Debe usar contenido aprobado y registrar `MESSAGE_SENT`. |
| Flow con mensaje libre | Usuario ya esta conversando y conviene estructurar captura. | Backend | Flow captura datos; backend valida y persiste. |
| Flow con template | Se necesita iniciar o reactivar captura estructurada fuera de ventana. | Backend | Usar solo si el caso lo justifica; registrar evento. |

Reglas:

- KAPSO ejecuta el envio, no decide el tipo.
- Backend registra `Message` y `EventLog`.
- Si el envio falla, backend decide retry, DLQ o handoff.
- Un flow submit no cambia estado de dominio sin validacion backend.

## Configuracion Segura Del Provider

El provider WhatsApp se controla por ambiente:

| Variable | Uso |
| --- | --- |
| `WHATSAPP_PROVIDER=mock|kapso` | Selecciona provider operativo. |
| `ENABLE_REAL_WHATSAPP=false|true` | Opt-in obligatorio para outbound real. |
| `KAPSO_API_KEY` | Credencial API para envio outbound real. |
| `KAPSO_BASE_URL` | Base URL de Kapso, por ejemplo `https://api.kapso.ai/meta/whatsapp` (sin versión Graph al final). |
| `KAPSO_PHONE_NUMBER_ID` | WhatsApp Business phone number id usado en el endpoint outbound. |
| `KAPSO_SEND_MESSAGE_PATH` | Path configurable para mensajes outbound. |
| `KAPSO_NEW_LOAD_TEMPLATE_NAME` | Template aprobado para reabrir ventana 24h con alertas de nueva carga. |
| `KAPSO_TEMPLATE_LANGUAGE_CODE` | Codigo de idioma del template, por defecto `es_AR`. |
| `KAPSO_INTERACTIVE_ENABLED=false|true` | Habilita payloads interactivos preparados para botones. Default seguro: `false`. |
| `KAPSO_WEBHOOK_SECRET` | Secreto HMAC para inbound. |
| `KAPSO_TIMESTAMP_TOLERANCE_SECONDS` | Ventana anti-replay cuando KAPSO envia timestamp. |
| `WHATSAPP_ALLOWLIST_SOURCE=db|env|db_then_env` | Fuente efectiva del allowlist inbound. En production se fuerza `db`. |
| `WHATSAPP_ALLOWLIST_DEFAULT_ALLOW=false|true` | Solo aplica fuera de production. En production siempre es `false`. |
| `WHATSAPP_DEV_ALLOWLIST` | Fallback deprecado para local/staging, separado por coma. |
| `ENABLE_TEST_ROLE_SWITCHING=false|true` | Permite cambiar rol conversacional para test local con un mismo numero. No usar como autenticacion real. |

Reglas:

- Mock es el default seguro.
- `WHATSAPP_PROVIDER=kapso` no alcanza para enviar real; tambien se requiere `ENABLE_REAL_WHATSAPP=true`.
- Outbound real requiere `KAPSO_API_KEY`, `KAPSO_BASE_URL`, `KAPSO_PHONE_NUMBER_ID` y `KAPSO_WEBHOOK_SECRET`.
- Outbound real usa `X-API-Key` y el endpoint `{KAPSO_BASE_URL}/{KAPSO_PHONE_NUMBER_ID}{KAPSO_SEND_MESSAGE_PATH}`.
- Si el texto libre falla por ventana WhatsApp 24h, el backend puede reintentar con `KAPSO_NEW_LOAD_TEMPLATE_NAME`.
- El template recomendado de nueva carga usa 4 variables body: carga, ruta, fecha/hora y observaciones.
- Si `KAPSO_INTERACTIVE_ENABLED=false`, toda accion se envia como texto numerado con fallback centralizado.
- Si `KAPSO_INTERACTIVE_ENABLED=true`, el adapter puede enviar hasta 3 botones directos o una lista interactiva de hasta 10 opciones con shape compatible WhatsApp Cloud API. Confirmacion/edicion, alertas de carga, seleccion de ofertas y menus de productor/transportista ya producen acciones.
- En almacenamiento SQL, el API y `scripts/dispatch_notification_outbox.py` leen esta opcion al iniciar. Al cambiarla, reiniciar ambos procesos; si el API y el worker quedan con valores distintos, el worker podria enviar como texto un mensaje que el API preparo como interactivo.
- Las selecciones entrantes se comprueban contra las acciones aceptadas mas recientemente para esa conversacion y escenario; las validaciones de dominio siguen aplicando. En modo texto se conserva el fallback numerado/textual.
- Los menus de cinco opciones usan lista interactiva, no cinco botones directos. Si la funcion esta apagada o no disponible, se mantiene el fallback numerado/textual.
- El wrapper outbound concreto se validó en Kapso Sandbox: una lista de cinco opciones se mostró en WhatsApp y una selección llegó al backend y ejecutó la consulta correspondiente. La vista de confirmación mostró también los botones directos. El flag sigue apagado por defecto; habilitarlo solo explícitamente en el entorno que se quiera probar.
- En `APP_ENV != production`, todo destino outbound real debe estar en `WHATSAPP_DEV_ALLOWLIST`.
- El inbound de WhatsApp consulta `whatsapp_allowed_contacts` desde DB.
- En `production`, el source efectivo del allowlist inbound siempre es `db`, `WHATSAPP_DEV_ALLOWLIST` no autoriza y `WHATSAPP_ALLOWLIST_DEFAULT_ALLOW` siempre se fuerza a `false`.
- En `local` y `staging`, `WHATSAPP_ALLOWLIST_SOURCE=db_then_env` permite compatibilidad temporal: primero DB y luego fallback al env legado.
- En `local` y `staging`, `WHATSAPP_ALLOWLIST_SOURCE=env` usa exclusivamente `WHATSAPP_DEV_ALLOWLIST` e ignora contactos de DB. Esto permite un entorno Sandbox cerrado mientras su base no está disponible.
- El filtro outbound de `WHATSAPP_DEV_ALLOWLIST` compara números de Argentina equivalentes con y sin el `9` móvil, para que un mismo participante no quede bloqueado por la variante entregada por WhatsApp.
- En local/dev, si faltan credenciales, se puede volver a mock; en staging/produccion debe fallar claro.
- No se hardcodean credenciales ni URLs de entorno.

## Allowlist Inbound En Backoffice

El backoffice expone `/whatsapp-allowlist` para administrar numeros habilitados por:

- telefono y telefono normalizado
- ambiente: `local`, `staging`, `production`, `all`
- provider: `kapso`, `whatsapp`, `all`
- estado: `ACTIVE`, `BLOCKED`, `DISABLED`

Reglas:

- `BLOCKED` gana sobre matches mas genericos.
- DB tiene prioridad sobre `WHATSAPP_DEV_ALLOWLIST`.
- Un numero no autorizado se bloquea antes de crear `ConversationSession` o `Message`.
- Cada decision inbound queda auditada en `EventLog`.

Migracion de numeros legados:

```bash
.venv/bin/python scripts/import_whatsapp_allowlist.py
```

Importa `WHATSAPP_DEV_ALLOWLIST` como contactos `staging + kapso + ACTIVE`. No corre en `production`.

### Modo De Prueba Por Rol

Cuando `ENABLE_TEST_ROLE_SWITCHING=true`, el entorno no es `production` y el remitente esta allowlisted, se pueden probar varios roles desde un unico chat. Cada recorrido debe abrir y cerrar su propio escenario:

| Comando | Efecto |
| --- | --- |
| `/test iniciar` | Crea un ID de escenario QA nuevo y limpia el override de rol anterior. |
| `/soy productor` | Fuerza la conversacion como productor dentro del escenario activo. |
| `/soy transportista` | Fuerza la conversacion como transportista dentro del escenario activo. |
| `/soy operador` | Fuerza la conversacion como operador. |
| `/estado sesion` | Consulta el estado de sesion y carrier detectado. |
| `/reset` | Vuelve a clasificacion automatica por telefono. |
| `/test cerrar` | Cierra el escenario, limpia el override y preserva el historial etiquetado. |

Reglas:

- Esto es solo testing, no autenticacion real.
- Sin escenario activo, los comandos de rol se rechazan. No mezclar recorridos ni reutilizar contexto anterior.
- Mensajes conservan una cronologia, con rol etiquetado; cargas, ofertas, asignaciones, viajes y eventos quedan en el escenario correspondiente.
- Consultas y aceptacion del productor en modo QA solo muestran y mutan datos del escenario activo.
- El mismo telefono puede representar productor y transportista en perfiles separados dentro del escenario. La persona usa el Sandbox como participante; no conecta su numero al API de produccion.
- No borrar la base entre escenarios; preservar registros QA etiquetados.
- Cada cambio se audita con `EventLog`.
- Sin override, la regla productiva se mantiene: si el telefono pertenece a un `Carrier`, se prioriza `Carrier`.
- En `production` estos comandos no deben habilitar cambios de rol.

### Webhook Publico Para KAPSO

KAPSO debe apuntar a:

```text
POST https://<public-domain>/api/v1/webhooks/kapso
```

Antes de exponer el webhook, configurar un `KAPSO_WEBHOOK_SECRET` aleatorio (minimo 32 caracteres, distinto del default), un `INTERNAL_API_KEY` aleatorio (minimo 32 caracteres), allowlist sin acceso por defecto y autenticar todas las rutas administrativas. Los clientes Kapso pasan esa clave como `AGRO_OPERATOR_API_KEY`. Las rutas rechazan configuracion insegura fuera de local/desarrollo.

El inbound valida:

- HMAC en `x-kapso-signature` con formato `sha256=<digest>`.
- Timestamp anti-replay en `x-kapso-timestamp` cuando exista.
- `event_type`.
- `idempotency_key` o `provider_message_id`.

Mapeo minimo:

| Payload KAPSO | Uso backend |
| --- | --- |
| `event_type` | Tipo de evento externo. |
| `idempotency_key` | Deduplicacion provider + key. |
| `provider_message_id` | ID externo de mensaje y fallback de idempotencia. |
| `conversation_id` | `ConversationSession.external_conversation_id`. |
| `workflow_execution_id` | Trazabilidad de workflow. |
| `phone_number` | Participante del canal. |
| `payload.text` o `text` | Contenido de `Message`. |

## Conversaciones

### Texto Libre

Usar cuando:

- El usuario inicia con mensaje informal.
- Hay ambiguedad tolerable.
- Se requiere una pregunta simple.
- El carrier responde corto: "si", "puede ser", "no llego".

Regla: texto libre se interpreta por backend/agents y puede derivar en revision humana.

### Flow Estructurado

Usar cuando:

- Faltan datos criticos repetibles.
- Conviene pedir origen, destino, fecha, tipo o cantidad; el telefono entrante ya identifica el contacto.
- El usuario ya mostro intencion clara de cargar datos.

No usar cuando:

- La conversacion requiere negociacion.
- Hay cancelacion o incidencia.
- El usuario esta confundido o responde con contexto libre.

### Intervencion Humana

Usar cuando:

- Hay dato critico faltante luego de pregunta.
- Hay ubicacion ambigua.
- Hay cambio de origen, destino, fecha o cantidad.
- Hay precio, matching, asignacion o cancelacion.
- Hay error de workflow, evento desordenado o estado invalido.

## Handoff

### Cuando Se Activa

- `requiresHumanReview = true`.
- `missingCriticalFields` persiste despues de intento conversacional.
- `hasAmbiguousLocation = true`.
- Respuesta de carrier no confirma claramente interes o disponibilidad.
- Cancelacion, incidencia o reemplazo.
- Error tecnico en webhook, flow o workflow que afecta una operacion real.

### Que Bloquea

Mientras hay handoff activo:

- No se publica carga automaticamente.
- No se confirma `Assignment`.
- No se crea `Trip` confirmado.
- No se cierra ni cancela definitivamente sin operador.
- No se envia mensaje que prometa resultado final.

### Como Se Retoma

1. Operador revisa contexto, mensajes, entidad y eventos.
2. Backend registra decision del operador.
3. Se valida transicion de estado.
4. Se registra `EventLog`.
5. KAPSO puede retomar envio de mensajes o workflow solo con instruccion backend.

## Tabla De Casos De Uso

| Caso de uso | KAPSO | Backend | Humano | Comentario |
| --- | --- | --- | --- | --- |
| Productor envia pedido inicial | Recibe mensaje y webhook | Crea `ConversationSession`, `Message`, posible `LivestockLoad` | No siempre | Si faltan datos, se pregunta o escala. |
| Captura de datos faltantes | Puede ejecutar flow limitado | Valida datos y flags | Si hay ambiguedad | Flow no valida negocio. |
| Normalizar ubicacion | No decide | Agent/backend marcan confianza | Si hay varias opciones | KAPSO solo transporta respuesta. |
| Publicar carga | Puede enviar mensajes | Backend valida datos, selecciona carriers aprobados/elegibles y registra eventos | Solo ante faltantes/ambiguedad/excepcion | KAPSO no selecciona carriers. |
| Carrier responde interesado | Recibe respuesta | Crea/actualiza `Offer` | Si la respuesta es ambigua | "Si" no equivale a assignment. |
| Ranking de carriers | No participa | Backend/agent sugiere compatibilidad y explica criterios | Productor elige entre ofertas; soporte resuelve excepciones | KAPSO no ejecuta matching. |
| Estimacion de precio | No participa | Agent estima rango | Si, precio final | KAPSO no calcula precio. |
| Confirmar asignacion | Puede enviar confirmacion redactada | Backend valida ownership/estado y registra | La acepta explicitamente el productor; soporte interviene en excepciones | `Assignment.CONFIRMED` nace de aceptar una oferta interesada. |
| Cancelacion | Recibe mensaje y webhook | Marca riesgo, valida transicion | Si, obligatorio | No resolver en workflow. |
| Sin respuesta de carriers | Puede enviar recordatorio si backend ordena | Registra `NO_CARRIER_RESPONSE` | Si decide ampliar | Broadcast no es core de KAPSO. |
| Incidencia de viaje | Recibe mensaje | Registra riesgo/evento | Si, obligatorio | No hay GPS ni automatizacion avanzada. |

## Validacion Contra Domain Model

| Regla del dominio | Estrategia KAPSO |
| --- | --- |
| `LivestockLoad` puede existir incompleta | KAPSO puede capturar datos, backend marca faltantes. |
| `Offer` no confirma viaje | Respuestas de carriers se registran como `Offer`, no como `Assignment`. |
| `Assignment` requiere aceptacion del productor o seleccion excepcional de soporte | KAPSO nunca ejecuta confirmacion final. |
| `Trip` nace desde `Assignment.CONFIRMED` | KAPSO no crea trips. |
| `EventLog` obligatorio | Backend registra eventos para mensajes, flows, errores y estados. |
| WhatsApp es canal | KAPSO queda detras de adapter reemplazable. |

## Decision Sobre Broadcasts

KAPSO puede transportar mensajes masivos o secuenciales, pero no debe ser el core de broadcast.

Backend decide:

- Que `LivestockLoad` se publica.
- A que carriers contactar.
- Que mensaje se envia.
- Que eventos registrar.
- Cuando ampliar busqueda.

KAPSO ejecuta envio y devuelve estados de entrega o respuesta.

## Agent Nodes De KAPSO

Los Agent nodes de Kapso no forman parte del flujo AGRO. La interpretacion conversacional y la extraccion se ejecutan desde el backend con `OPENAI_API_KEY` y `OPENAI_MODEL`; el orquestador construye la respuesta y valida las acciones del dominio. No se permite que otro agente responda en paralelo al webhook backend, porque produciria respuestas duplicadas y dividiria el control de la conversacion.

## Functions / Tools Auxiliares

KAPSO puede invocar tools auxiliares solo si son wrappers hacia backend y no contienen reglas propias.

Regla: toda tool critica debe llamar backend, y backend decide.

Ejemplos permitidos:

- Consultar estado conversacional.
- Enviar input estructurado al backend.
- Solicitar handoff.

Ejemplos no permitidos:

- `assignCarrier`.
- `confirmTrip`.
- `calculateFinalPrice`.
- `changeLoadStatus`.

## Decisiones Pendientes

1. Definir contrato exacto de webhook KAPSO -> backend.
2. Definir estrategia de firma HMAC y rotacion de secrets.
3. Definir formato de `idempotency_key` si KAPSO no provee uno estable.
4. Definir cuando conviene usar flow vs texto libre por tipo de usuario.
5. Definir templates WhatsApp necesarios para fuera de ventana.

## Riesgos

1. Vendor lock-in si workflows concentran comportamiento operativo.
2. Dependencia de workflows que impida modo degradado.
3. Perdida de control del dominio si KAPSO cambia estados indirectamente.
4. Duplicados por reintentos mal deduplicados.
5. Handoff tardio ante ambiguedad o cancelacion.

## Mitigaciones

1. Adapter pattern obligatorio para KAPSO y WhatsApp provider.
2. Backend como unico owner de estado y eventos.
3. Validacion de transiciones antes de cualquier cambio.
4. Idempotencia persistida por provider + key.
5. Criterios explicitos de handoff y DLQ para errores.

## Diagrama Resumido

```text
KAPSO = canal/workflows/flows/handoff
Backend = ConversationSession + Message + LivestockLoad + Offer + Assignment + EventLog
Agents = interpretan y sugieren
Dominio = valida reglas y estados
Operator = confirma decisiones criticas
```

## Proximo Paso Recomendado

Cuando las credenciales hayan sido rotadas y el PostgreSQL local esté disponible, verificar el webhook de Sandbox y su allowlist efectiva; luego retirar el Agent node del workflow AGRO remoto durante la misma ventana en que se apunta el webhook al backend. Confirmar que solo una ruta responde antes de recorrer creación de carga, interés y aceptación. Mantener el workflow listo para volver a activar si falla el endpoint backend.
