# AGRO Logistics MVP

AGRO Logistics coordina por WhatsApp cargas de hacienda y granos entre productores/comisionistas y transportistas. El backend conserva las reglas y los datos del negocio; el backoffice da seguimiento a personas, cargas, homologacion y conversaciones, con soporte humano para revision y excepciones.

Este repositorio contiene producto, documentacion y una implementacion en iteracion. Las propuestas nuevas se registran primero en la bitacora y se reflejan en los documentos de alcance/dominio antes de escribir codigo.

## Problema Que Resuelve

Coordinar un camion para mover hacienda suele depender de contactos informales, mensajes dispersos y confianza personal. Esto genera:

- Dificultad para conseguir transportistas disponibles.
- Coordinacion manual por WhatsApp sin trazabilidad.
- Precios poco claros o dificiles de comparar.
- Cancelaciones de ultimo momento.
- Falta de seguimiento del estado de cada viaje.
- Falta de historial operativo.
- Dependencia excesiva de la memoria del productor, comisionista u operador.

AGRO Logistics busca ordenar esa operacion sin forzar a los usuarios a cambiar sus habitos principales.

## Por Que WhatsApp

WhatsApp ya es el canal donde ocurre la operacion real:

- Productores y comisionistas ya lo usan para pedir camiones.
- Transportistas ya reciben oportunidades por grupos o mensajes directos.
- El operador interno puede intervenir sin pedir instalacion de una app.
- Reduce friccion de adopcion en zonas donde la conectividad y el tiempo disponible son limitados.

La decision de producto es clara: para el MVP, WhatsApp es el canal; no debe convertirse en la logica del negocio. El dominio debe poder funcionar aunque el canal cambie en el futuro.

## Que Incluye El MVP

Esta lista expresa el alcance de producto documentado; no afirma que todas las funciones esten implementadas. Para el estado real, consultar la tabla de tareas en [docs/plan-y-bitacora.md](docs/plan-y-bitacora.md).

El MVP incluye una operacion semi-automatica:

- Publicacion de carga via WhatsApp.
- Captura guiada de datos basicos de la carga.
- Validacion automatica por backend y preguntas al productor; soporte atiende ambiguedades y excepciones.
- Broadcast de oportunidades a transportistas.
- Registro de transportistas interesados.
- Matching sugerido, nunca automatico.
- Aceptacion explicita del productor, tras el interes del transportista; el backend registra assignment y viaje planificado.
- Recordatorios operativos.
- Historial basico de cargas y viajes.
- Registro de eventos relevantes.
- Disponibilidad declarada de recorridos del transportista y busqueda de oportunidades por ruta.
- Sugerencias de cargas parciales o de retorno, sujetas a aceptacion y validacion de capacidad.
- Solicitudes de homologacion de transportistas por WhatsApp con revision de soporte.
- Backoffice para consultar conversaciones cronologicas y perfiles de productores.

Una disponibilidad de recorrido no es un `Trip`: el viaje operativo se crea al confirmar una asignacion conforme al modelo de dominio. Ver [docs/07-domain-model.md](docs/07-domain-model.md).

## Que No Incluye El MVP

El MVP no incluye:

- Pagos dentro de la app.
- GPS en tiempo real.
- Optimizacion avanzada de rutas o flota.
- Pricing automatico definitivo.
- App mobile para productores o transportistas.
- Automatizacion completa de decisiones criticas.

## Como Usar Este Repo

La documentacion vigente se organiza por responsabilidad. La bitacora es el indice de prioridades/decisiones/avances; el alcance y los documentos de dominio definen el producto y las reglas.

Orden recomendado de lectura:

1. [docs/plan-y-bitacora.md](docs/plan-y-bitacora.md)
2. [docs/04-mvp-scope.md](docs/04-mvp-scope.md)
3. [docs/05-operating-model.md](docs/05-operating-model.md)
4. [docs/07-domain-model.md](docs/07-domain-model.md) y [docs/08-state-machine.md](docs/08-state-machine.md)
5. [docs/22-data-standardization.md](docs/22-data-standardization.md)
6. [AGENTS.md](AGENTS.md)

Referencias complementarias: [docs/09-event-log-design.md](docs/09-event-log-design.md) define auditoria; [DATA_CATALOG.md](DATA_CATALOG.md), campos/sensibilidad; [LINEAGE.md](LINEAGE.md), trazabilidad; [METRICS_DICTIONARY.md](METRICS_DICTIONARY.md), metricas; [docs/23-kapso-integration-strategy.md](docs/23-kapso-integration-strategy.md), responsabilidades del canal.

Antes de generar codigo, cualquier persona o agente AI debe entender:

- Que problema operativo se esta resolviendo.
- Que decisiones quedan en manos humanas.
- Que datos son necesarios para crear una carga.
- Que eventos deben registrarse.
- Que cosas estan fuera del MVP.

## Como Trabajar Con Agents Y Skills

Los agents AI deben seguir las reglas globales de [AGENTS.md](AGENTS.md). Su rol es asistir la operacion y el desarrollo, no inventar reglas de negocio ni reemplazar decisiones humanas sensibles.

Los agentes se describen en [agents/](agents/); las skills atomicas, en [skills/](skills/). Los README de esos directorios contienen sus indices.

Regla de trabajo:

- Los agents orquestan tareas.
- Las skills ejecutan capacidades especificas.
- El operador humano valida decisiones criticas.
- La documentacion se actualiza cuando cambia el modelo operativo.

## Orden Recomendado De Desarrollo

1. Resolver decisiones pendientes de alcance y mantener este mapa documental alineado.
2. Completar catalogos, homologacion, disponibilidades y privacidad documental.
3. Implementar las prioridades registradas en la bitacora con cambios acotados y verificables.
4. Validar primero localmente y despues con Sandbox controlado; revisar el criterio de pruebas antes de ejecutar.
5. Medir la operacion antes de automatizar decisiones criticas.

## Backend Local

El backend usa FastAPI. La suite completa se ejecuta con:

```bash
.venv/bin/python -m pytest
```

La persistencia real usa SQLAlchemy + Alembic y lee `DATABASE_URL` desde `.env`.

Modo in-memory, util para unit tests y prototipado local:

```bash
export KAPSO_WEBHOOK_SECRET="local-dev-secret"
export KAPSO_TIMESTAMP_TOLERANCE_SECONDS=300
export STORAGE_BACKEND=memory
.venv/bin/uvicorn app.main:app --app-dir backend --reload
```

En local, si `KAPSO_API_KEY` no esta configurada, los envios outbound usan `MockWhatsAppProvider`: no salen a internet, pero quedan auditados en `EventLog`.
Tambien se puede forzar mock de forma explicita:

```bash
export WHATSAPP_PROVIDER=mock
export ENABLE_REAL_WHATSAPP=false
```

Modo SQL, requerido antes de operar datos reales:

```bash
export STORAGE_BACKEND=sql
export DATABASE_URL="<driver>://<user>:<password>@<host>:<port>/<database>"
export KAPSO_WEBHOOK_SECRET="<webhook-secret>"
export KAPSO_TIMESTAMP_TOLERANCE_SECONDS=300
.venv/bin/uvicorn app.main:app --app-dir backend --reload
```

El health check de base de datos queda disponible en:

```bash
curl http://127.0.0.1:8000/health/db
```

Para correr migraciones:

```bash
export STORAGE_BACKEND=sql
export DATABASE_URL="<driver>://<user>:<password>@<host>:<port>/<database>"
.venv/bin/alembic upgrade head
```

Los repositorios in-memory siguen existiendo para unit tests y prototipado dev-only. No deben usarse como fuente de verdad con datos reales.

Webhook KAPSO local/mock:

```bash
BODY='{"event_type":"message.received","idempotency_key":"local_evt_1","provider_message_id":"wamid_local_1","conversation_id":"conv_local_1","phone_number":"+5491111111111","payload":{"text":"Necesito camion para 35 novillos de Azul a Liniers"}}'
SIGNATURE=$(BODY="$BODY" python -c 'import hashlib,hmac,os; body=os.environ["BODY"].encode(); secret=os.environ.get("KAPSO_WEBHOOK_SECRET","local-dev-secret").encode(); print("sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest())')
curl -X POST http://127.0.0.1:8000/api/v1/webhooks/kapso \
  -H "content-type: application/json" \
  -H "x-kapso-signature: $SIGNATURE" \
  -d "$BODY"
```

Outbound a transportistas:

- Cuando soporte usa la publicacion administrativa/excepcional `POST /api/v1/shipment-requests/{id}/publish`, el backend genera una alerta por cada `carrier_id`; el flujo feliz publica tras la confirmacion del productor.
- El `carrier_id` debe existir y tener `contact_phone`, `normalized_phone_number`, `provider_contact_id` o `provider_conversation_id`.
- Cada alerta registra `CARRIER_NOTIFICATION_REQUESTED` y luego `CARRIER_NOTIFICATION_SENT` o `CARRIER_NOTIFICATION_FAILED`.
- La idempotencia outbound usa una key deterministica por carga + transportista + tipo de alerta, por lo que republicar o reintentar la misma alerta no duplica envios ya marcados como enviados.
- En local/mock, la respuesta admin incluye el resumen `notifications_sent`, `notifications_failed` y `notifications_skipped` sin depender de credenciales reales.

Modo KAPSO real controlado:

```bash
export APP_ENV=staging
export WHATSAPP_PROVIDER=kapso
export ENABLE_REAL_WHATSAPP=true
export KAPSO_API_KEY="<api-key>"
export KAPSO_BASE_URL="https://api.kapso.ai/meta/whatsapp/v24.0"
export KAPSO_PHONE_NUMBER_ID="<whatsapp-business-phone-number-id>"
export KAPSO_SEND_MESSAGE_PATH="/messages"
export KAPSO_NEW_LOAD_TEMPLATE_NAME="<approved-template-name>"
export KAPSO_TEMPLATE_LANGUAGE_CODE="es_AR"
export KAPSO_WEBHOOK_SECRET="<webhook-secret>"
export WHATSAPP_DEV_ALLOWLIST="+5491111111111,+5492222222222"
```

Reglas de seguridad:

- `ENABLE_REAL_WHATSAPP=false` usa mock aunque existan credenciales.
- En `APP_ENV != production`, el destino outbound debe estar en `WHATSAPP_DEV_ALLOWLIST`.
- KAPSO outbound real usa `X-API-Key` y publica en `{KAPSO_BASE_URL}/{KAPSO_PHONE_NUMBER_ID}{KAPSO_SEND_MESSAGE_PATH}`.
- Si WhatsApp rechaza texto libre por ventana 24h y `KAPSO_NEW_LOAD_TEMPLATE_NAME` esta configurado, el adapter reintenta la alerta de carga con template aprobado.
- El template sugerido para nueva carga usa 4 variables body: `{{1}}` carga, `{{2}}` ruta, `{{3}}` fecha/hora, `{{4}}` observaciones.
- En `production`, no se aplica allowlist dev, pero el modo real sigue requiriendo opt-in y credenciales completas.
- Si faltan credenciales en `local`, el backend vuelve a mock; fuera de local/dev falla claro al construir el provider.

Para exponer el webhook local a KAPSO, levantar el backend y usar un tunel HTTPS:

```bash
.venv/bin/uvicorn app.main:app --app-dir backend --reload
ngrok http 8000
# o cloudflared tunnel --url http://127.0.0.1:8000
# o lt --port 8000
```

Configurar en KAPSO la URL publica:

```text
https://<tunnel-domain>/api/v1/webhooks/kapso
```

Inbound acepta `X-Webhook-Signature` o `x-kapso-signature` y valida HMAC con `KAPSO_WEBHOOK_SECRET`. Si KAPSO envia `x-kapso-timestamp`, se valida contra `KAPSO_TIMESTAMP_TOLERANCE_SECONDS`. El payload minimo esperado incluye `event_type` y `idempotency_key` o `provider_message_id`; `payload.text` se mapea al texto de `Message`.

## Contactos De Prueba

Para probar outbound con SQL, cargar primero carriers/productores con telefonos no reales. El backend normaliza telefonos argentinos a E.164, por ejemplo `11 15 1234 5678` -> `+5491112345678`.

Ejemplo rapido desde Python:

```bash
PYTHONPATH=backend .venv/bin/python - <<'PY'
from app.application.contact_mapping import normalize_phone_number
from app.domain.models import Carrier, Producer
from app.infrastructure.db.repositories import SqlCarrierRepository, SqlProducerRepository
from app.infrastructure.db.session import get_session_factory
from app.core.config import get_settings

factory = get_session_factory(get_settings().database_url)
with factory() as session, session.begin():
    carrier_phone = "11 15 1234 5678"
    producer_phone = "11 15 8765 4321"
    SqlCarrierRepository(session).add(Carrier(
        id="car_test_1",
        name="Carrier Test",
        contact_phone=carrier_phone,
        normalized_phone_number=normalize_phone_number(carrier_phone),
        provider_name="kapso",
        provider_contact_id="kapso_contact_test_1",
        provider_conversation_id="kapso_conv_test_1",
    ))
    SqlProducerRepository(session).add(Producer(
        id="prod_test_1",
        name="Producer Test",
        contact_phone=producer_phone,
        normalized_phone_number=normalize_phone_number(producer_phone),
        provider_name="kapso",
        provider_contact_id="kapso_contact_prod_1",
        provider_conversation_id="kapso_conv_prod_1",
    ))
PY
```

En `APP_ENV != production`, si se activa WhatsApp real, agregar el telefono normalizado del carrier al allowlist:

```bash
export WHATSAPP_DEV_ALLOWLIST="+5491112345678"
```
