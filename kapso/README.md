# AGRO Logistics Kapso Channel

Kapso transports WhatsApp messages for AGRO Logistics MVP. The backend owns
conversation handling and uses the configured OpenAI API key; Kapso's AI agent
is not part of the intended runtime flow.

## What This Layer Does

- Delivers WhatsApp inbound webhooks to the AGRO backend.
- Sends backend-authored replies through the Kapso WhatsApp API.
- The local `agro-whatsapp` agent workflow is in draft to prevent duplicate replies.

## How It Coexists With `/backend`

`/backend` remains the source of truth for:

- `ShipmentRequest`
- `TripOffer`
- `Assignment`
- `Trip`
- `EventLog`
- state transitions
- carrier matching and offer selection

`/kapso` is a transport integration only. It must not own conversational routing,
persist business state, or implement domain rules.

## Install

```bash
cd kapso
npm install
```

This project uses the local CLI dependency `@kapso/cli`. Run it through npm scripts or `npx kapso`:

```bash
npx kapso --help
```

The Kapso docs also show `npm install -g @kapso/cli`; a global install is optional.

## Configure

```bash
cp .env.example .env
```

Set:

- `KAPSO_API_KEY`
- `KAPSO_PHONE_NUMBER_ID`
- `KAPSO_NEW_LOAD_TEMPLATE_NAME=agro_new_load_available`
- `AGRO_BACKEND_BASE_URL`
- `AGRO_OPERATOR_USER_ID`
- `AGRO_OPERATOR_ROLE`
- `AGRO_OPERATOR_API_KEY` (same private value as backend `INTERNAL_API_KEY` outside local development)
- optional `SLACK_WEBHOOK_URL`

Do not commit `.env` or real secrets.

## Local Development

Start backend first:

```bash
cd ..
.venv/bin/uvicorn app.main:app --app-dir backend --reload
```

Then from `kapso`:

```bash
npm run typecheck
npm run build
```

Templates and broadcasts are outside the Sandbox MVP test. Use the active Sandbox session for free-form messages; template setup is deferred.

Post-restart verification:

```bash
.venv/bin/python scripts/verify_kapso_template_fallback.py
```

If the backend is not running on `http://127.0.0.1:8000`, override it with:

```bash
AGRO_BACKEND_VERIFY_BASE_URL="https://tu-backend" .venv/bin/python scripts/verify_kapso_template_fallback.py
```

## Kapso Project Flow

```bash
npx kapso login
npx kapso link --project <project-id>
npx kapso pull
npm run build
npm run push
```

Current linked project:

- Project: `APP TRANSPORTE`
- Project ID: `faf9ec96-ba68-4b9e-a34b-d8db98de7000`
- Sandbox WhatsApp phone number ID used by `agro-whatsapp`: `597907523413541`

As of 2026-09-28, the remote Kapso project does not contain the `agro-whatsapp`
workflow or `agro-backend-client` function. The local workflow is explicitly
scoped to the Sandbox phone number ID above. Review its dry-run before publishing.

Source-controlled Kapso assets use the CLI layout:

- `functions/agro-backend-client/function.yaml` + `index.js`
- `functions/search-knowledge/function.yaml` + `index.js`
- `functions/escalate-to-human/function.yaml` + `index.js`
- `workflows/agro-whatsapp/workflow.ts`

`workflows/agro-whatsapp.workflow.ts` is only a compatibility re-export for the original skeleton path.

## Backend Tool Contract

`agro-backend-client` is a thin HTTP client. For chat drafts it calls:

```text
POST ${AGRO_BACKEND_BASE_URL}/api/v1/shipment-requests/from-chat
```

with admin headers from `AGRO_OPERATOR_USER_ID` and `AGRO_OPERATOR_ROLE`, and sends only:

```json
{
  "text": "Necesito camión para 40 novillos...",
  "phone_number": "+549...",
  "idempotency_key": "kapso_chat_draft_..."
}
```

It returns `{ "ok": true, "shipment_id": "sr_...", "status": "DRAFT" }` to the agent. Business parsing, validation, state changes and persistence stay in `/backend`.

## WhatsApp Testing

1. Confirm the backend is reachable at `AGRO_BACKEND_BASE_URL`.
2. Confirm `POST /api/v1/webhooks/kapso` is configured for inbound events.
3. Publish a shipment from backend/admin.
4. Send a WhatsApp reply like `1`, `2`, or `3`.
5. Verify backend DB:
   - `messages.sender_type`
   - `trip_offers`
   - `event_logs`

## What Must Not Live In Kapso

- Pricing decisions.
- Carrier assignment.
- Shipment state transitions.
- Trip creation outside backend APIs.
- Business persistence.
- Final confirmation of transport.
- Any workaround that bypasses Postgres `EventLog`.

## References

- Kapso workflow code example: `Workflow`, `START`, `inbound_message`, `send_text`.
- Historical Kapso agent instructions are retired; do not attach them to a workflow.
- Kapso function runtime: define `async function handler(request, env)`; do not export a default worker.

See `docs/architecture.md`, `docs/backend-contract.md`, and `docs/local-development.md` for the integration contract.
