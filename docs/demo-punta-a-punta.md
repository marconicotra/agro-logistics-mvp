# Demo de AGRO Logistics

Este documento separa la demo ficticia en memoria de la presentación integrada
con Kapso Sandbox y PostgreSQL local. No apuntan a la misma fuente de datos.

## Demo visual ficticia en memoria

Este modo no depende de Kapso, OpenAI, Supabase, credenciales, internet ni una
base persistente. Todo lo que aparece es ficticio y se carga en memoria al
iniciar el servidor. Por eso la bandeja contiene solo `cs_demo_punta_a_punta`.

## Preparacion

Desde la raiz del repositorio, abrir dos terminales.

Terminal 1 — API de demo:

```bash
.venv/bin/python scripts/run_local_demo.py
```

Terminal 2 — backoffice apuntando a esa API:

```bash
cd frontend
VITE_API_BASE_URL=http://127.0.0.1:8001 ./node_modules/.bin/vite --host 127.0.0.1 --port 5174 --strictPort
```

Abrir `http://127.0.0.1:5174/dashboard`. Ambos procesos quedan ligados a
`127.0.0.1`; no reemplazan los servicios habituales en los puertos 8000/5173.
El demo fuerza `APP_ENV=local`, memoria, proveedor WhatsApp mock, IA desactivada,
descarga de medios desactivada y allowlist de QA desactivada. No procesa mensajes
entrantes. Reiniciar la API vuelve a cargar el mismo escenario sintético.

## Recorrido sugerido

1. En **Dashboard**, mostrar una carga asignada, un viaje planificado y un
   transportista ficticio marcado como aprobado en el fixture.
2. En **Conversaciones**, abrir el hilo `cs_demo_punta_a_punta`. La cronología
   presenta: carga y fecha concreta, confirmación del productor, publicación,
   interés del transportista, aceptación del productor y viaje planificado.
3. En **Viajes**, mostrar el estado `PLANNED` y el corredor Azul → Rosario.
4. En **Transportistas**, mostrar el perfil de ejemplo. Su contacto y CUIT son
   placeholders deliberadamente inválidos; el documento asociado también es
   ficticio y su nota aclara que no acredita revisión real.
5. Explicar que productor y transportista son roles de una operación, que el
   interés no asigna el viaje y que la aceptación explícita del productor crea
   la asignación y el viaje.

La conversación es un transcript de demostración precargado; no se envió por
WhatsApp. El recorrido de dominio se verifica aparte con el test interno de
marketplace, que usa el orquestador real, proveedor mock, datos en memoria y
completa publicación, interés, aceptación, viaje, avisos e idempotencia:

```bash
cd backend
APP_ENV=local INTERNAL_API_KEY='' AI_PROVIDER=disabled OPENAI_API_KEY='' STT_ENABLED=false STORAGE_BACKEND=memory MEDIA_DOWNLOAD_ENABLED=false ../.venv/bin/pytest tests/test_carrier_responses.py -k internal_qa_marketplace_happy_path -q
```

## Limites que conviene explicitar

- Este modo demuestra la interfaz y el estado operativo, no una conexión real de
  WhatsApp ni entrega de mensajes.
- La autenticación humana del backoffice en entornos compartidos espera la
  futura integración con Supabase Auth.
- No presentar como terminados el matching por disponibilidad/ruta, el retorno
  parcial, la outbox transaccional ni la homologación legal/documental completa;
  siguen como trabajo pendiente en `docs/plan-y-bitacora.md`.
- El entorno no configura ni requiere Supabase. No usar datos ni documentos
  reales durante esta presentación.

## Presentación integrada: WhatsApp Sandbox + backoffice SQL local

La versión integrada usa el webhook de Kapso Sandbox en `:8002`, que persiste
mensajes y operaciones en el PostgreSQL local; el panel de lectura/operación usa
una API local separada en `:8003` y Vite en `:5175`. El API del panel usa el
proveedor WhatsApp mock para que una acción desde el navegador no envíe mensajes.
Los tres servicios se ligan a `127.0.0.1`. No uses `:5174` para revisar mensajes
reales: ese puerto muestra la demo en memoria.

### Orden de preparación

Desde la raíz del repositorio:

1. Si PostgreSQL no está activo, iniciarlo y confirmar la revisión de esquema:

```bash
docker compose up -d db
APP_ENV=local STORAGE_BACKEND=sql .venv/bin/alembic current
```

La revisión esperada es `0015_route_availability_capture`. Si la base informa una
revisión anterior, hacer primero un respaldo privado fuera del repositorio y
después aplicar migraciones:

```bash
umask 077
docker exec agro_postgres pg_dump -Fc -U postgres -d agro_logistics > /tmp/agro_logistics_pre_demo.dump
APP_ENV=local STORAGE_BACKEND=sql .venv/bin/alembic upgrade head
```

2. Verificar el webhook y la base. Si el webhook ya está activo en `:8002`, no
levantes otra instancia:

```bash
curl -fsS http://127.0.0.1:8002/health
curl -fsS http://127.0.0.1:8003/health/db
```

Si el webhook está detenido, desde una terminal:

```bash
APP_ENV=staging STORAGE_BACKEND=sql .venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8002
```

El túnel de ngrok debe seguir apuntando a `:8002`. Si se reinicia con otro
dominio, el webhook configurado en Kapso debe actualizarse manualmente antes de
probar; no cambies el webhook del otro número.

3. Mantener un solo worker de outbox. Si ya hay uno corriendo, no inicies otro.
Si no hay ninguno, abrir otra terminal:

```bash
APP_ENV=staging STORAGE_BACKEND=sql .venv/bin/python scripts/dispatch_notification_outbox.py --poll-seconds 2
```

4. Si la API SQL local del panel no está activa, abrir otra terminal:

```bash
APP_ENV=local STORAGE_BACKEND=sql WHATSAPP_PROVIDER=mock ENABLE_REAL_WHATSAPP=false AI_PROVIDER=disabled STT_ENABLED=false MEDIA_DOWNLOAD_ENABLED=false .venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8003
```

5. Si Vite no está activo, abrir otra terminal:

```bash
cd frontend
VITE_API_BASE_URL=http://127.0.0.1:8003 VITE_SUPABASE_URL= VITE_SUPABASE_ANON_KEY= VITE_OPERATOR_USER_ID=user_operator VITE_OPERATOR_ROLE=operator ./node_modules/.bin/vite --host 127.0.0.1 --port 5175 --strictPort
```

Abrir `http://127.0.0.1:5175/conversations` para los mensajes de WhatsApp
persistidos y `http://127.0.0.1:5175/route-availabilities` para disponibilidades.
Los headers de operador de desarrollo solo funcionan con `APP_ENV=local` en el
API enlazado a loopback; no sirven para abrir el backoffice a otras personas por
internet. Supabase Auth real sigue pendiente.

### Recorrido de WhatsApp para presentar

Usar el chat **Kapso Sandbox** y solamente datos ficticios. Si hay un escenario
activo de una prueba anterior, cerrarlo primero. Los registros permanecen en la
base etiquetados con su escenario; no se borran.

1. Iniciar y alternar al rol productor:

```text
/test cerrar    (solo si el bot avisa que ya hay uno activo)
/test iniciar
/soy productor
```

2. Crear una carga ficticia por WhatsApp, confirmar el resumen y mostrarla en
**Cargas**:

```text
Necesito transportar 25 cabezas de novillos desde Pergamino hasta Rosario el 14/10/2026
```

3. Para mostrar las opciones interactivas y el recorrido del transportista:

```text
/soy transportista
hola
```

Abrir **Ver opciones** y elegir **🛣️ Recorrido**. El bot pregunta, en este orden:

```text
Rosario
Pergamino
15/10/2026
Paraná
25 cabezas
novillos
jaula
```

Revisar el resumen (incluye fecha concreta y día completo en Argentina), tocar
**Confirmar** o responder `confirmar`. El registro aparece en **Disponibilidad**
con su ruta, parada, fecha, capacidad, carga, equipo y estado. Esta acción no crea
un viaje ni un match. La búsqueda de oportunidades desde WhatsApp y el
compromiso de capacidad siguen pendientes.

4. Para mostrar la aceptación de una oferta dentro del mismo escenario QA:

   - Como transportista, abrir **Ver opciones** → **Ver carga recibida** y
     elegir la carga recién publicada. Tocar **Me interesa** (o responder
     `me interesa` si el mensaje llegó como texto). Si el bot pide identificar
     la carga, elegir la opción correspondiente; no uses una referencia de una
     prueba anterior.
   - Cambiar a productor con `/soy productor`, abrir **Ver opciones** →
     **Ver interesados** y tocar **Aceptar 1** para la oferta de esta prueba.
   - Comprobar la confirmación del viaje planificado en WhatsApp y abrir
     **Viajes** en el backoffice. La aceptación confirma el match; la asignación
     de conductor, unidad y horario queda para la operación posterior.

   El alta/homologación de otro transportista queda fuera de este recorrido.

5. Cerrar al terminar:

```text
/test cerrar
```

El modo QA exige el flag de pruebas y la allowlist configurada. El webhook
Sandbox y su túnel ya estaban levantados al registrar este procedimiento; estos
comandos no cambian Kapso ni el número de producción.

### Cierre de la demo

- En WhatsApp, cerrar el escenario con `/test cerrar`.
- Detener con `Ctrl+C` las terminales que se hayan iniciado para la demo. Si se
  usa Docker para PostgreSQL, no apagarlo si otros proyectos lo necesitan.
- Mantener la base y sus filas QA; no ejecutar borrados generales.
- El panel integrado queda en `:5175`. El servidor ficticio de `:5174` se retiró
  para evitar confundirlo con las conversaciones persistidas.
