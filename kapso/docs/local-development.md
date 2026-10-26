# Local Development

## 1. Install Kapso CLI

Dependencies include the Kapso CLI locally:

```bash
cd kapso
npm install
npx kapso --help
```

Some Kapso workflow examples also show a global install:

```bash
npm install -g @kapso/cli
```

That is optional for this repo.

## 2. Install Dependencies

```bash
cd kapso
npm install
```

## 3. Log In And Link

```bash
npx kapso login
npx kapso link --project <project-id>
npx kapso pull
```

Current project binding:

- Project: `APP TRANSPORTE`
- Project ID: `faf9ec96-ba68-4b9e-a34b-d8db98de7000`
- Sandbox WhatsApp phone number ID: `597907523413541`

## 4. Configure Environment

```bash
cp .env.example .env
```

Fill:

- `KAPSO_API_KEY`
- `KAPSO_PHONE_NUMBER_ID`
- `AGRO_BACKEND_BASE_URL`
- `AGRO_OPERATOR_USER_ID`
- `AGRO_OPERATOR_ROLE`
- optional `SLACK_WEBHOOK_URL`

## 5. Start Backend

From repo root:

```bash
.venv/bin/uvicorn app.main:app --app-dir backend --reload
```

Confirm:

```bash
curl http://127.0.0.1:8000/health/db
```

## 6. Typecheck And Build

```bash
cd kapso
npm run typecheck
npm run build
```

If `@kapso/workflows` API types differ from this skeleton, update `workflows/agro-whatsapp.workflow.ts` using the pulled project assets and Kapso docs before pushing.
Kapso CLI source files live at:

- `workflows/agro-whatsapp/workflow.ts`
- `workflows/agro-whatsapp/workflow.yaml`
- `workflows/agro-whatsapp/definition.json`
- `functions/<slug>/function.yaml`
- `functions/<slug>/index.js`

## 7. Push Functions And Workflow

```bash
npx kapso push --dry-run
npm run push
```

Available deployed slugs:

- `agro-backend-client`
- `search-knowledge`
- `escalate-to-human`
- `agro-whatsapp`

## 8. Test WhatsApp

1. Confirm backend webhook is configured:
   - `POST /api/v1/webhooks/kapso`
2. Publish a shipment from backend.
3. Send carrier reply:
   - `1` = interested
   - `2` = cannot
   - `3` = more info
4. Check backend DB:

```sql
select id, sender_type, raw_content
from messages
order by created_at desc
limit 5;

select *
from trip_offers
order by created_at desc
limit 5;

select event_type, entity_type, entity_id
from event_logs
order by occurred_at desc
limit 10;
```

Expected:

- `sender_type = Carrier`
- `TripOffer response_type = INTERESTED`
- `CARRIER_INTERESTED`
- first interested response moves shipment to `MATCHING`

## 9. Verify Template Fallback After Restart

Once the backend is restarted with real Kapso outbound enabled, run:

```bash
cd ..
.venv/bin/python scripts/verify_kapso_template_fallback.py
```

The check validates:

- backend health
- DB connectivity
- backend-loaded WhatsApp template config via `/health/whatsapp`
- template presence and approval status in Kapso

If the backend is exposed through another URL, set:

```bash
AGRO_BACKEND_VERIFY_BASE_URL="https://tu-backend" .venv/bin/python scripts/verify_kapso_template_fallback.py
```
