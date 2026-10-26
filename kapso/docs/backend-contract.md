# Backend Contract

Kapso functions call the AGRO backend over HTTP. Backend remains the source of truth.

## Existing Endpoints

### `GET /api/v1/admin/shipments/with-offers`

Lists published or matching shipments with active `TripOffer` records.

Used by:

- operator command: `ver cargas`
- agent summary of active opportunities

### `POST /api/v1/shipments/{shipment_id}/select-offer`

Selects an offer and creates `Assignment + Trip` through backend logic.

Headers:

- `X-Operator-User-Id`
- `X-Operator-Role`

Body:

```json
{
  "trip_offer_id": "off_...",
  "idempotency_key": "select_..."
}
```

### `GET /api/v1/admin/assignments/pending`

Lists assignments that still need manual operator confirmation.

Used by:

- operator command: `ver viajes pendientes`
- indexed operator command: `confirmar viaje 1`

Headers:

- `X-Operator-User-Id`
- `X-Operator-Role`

Query:

- `limit`

### `POST /api/v1/assignments/{assignment_id}/confirm`

Confirms an assignment manually through backend logic. If a `Trip.PLANNED` was already created by offer selection, backend reuses it instead of creating a duplicate trip.

Headers:

- `X-Operator-User-Id`
- `X-Operator-Role`

Body:

```json
{
  "confirmation_notes": "productor y transportista confirmados",
  "idempotency_key": "confirm_..."
}
```

### `POST /api/v1/shipment-requests/{shipment_request_id}/publish`

Publishes a validated shipment to carriers.

Headers:

- `X-Operator-User-Id`
- `X-Operator-Role`

Body:

```json
{
  "carrier_ids": ["car_..."],
  "idempotency_key": "publish_..."
}
```

### `POST /api/v1/webhooks/kapso`

Receives inbound Kapso/WhatsApp events. This is already the backend source for carrier replies like `1`, `2`, and `3`.

### `POST /api/v1/shipment-requests/from-chat`

Creates a draft shipment from chat text. The backend remains source of truth; Kapso does not create business state directly.

Body:

```json
{
  "text": "Necesito camión para 40 novillos de Azul a Liniers mañana",
  "phone_number": "+549...",
  "idempotency_key": "chat_..."
}
```

Behavior:

- Persist `ShipmentRequest` as `DRAFT`.
- Store the original text as `operational_notes`.
- Record `EventLog`.

## Recommended Missing Endpoints

### `POST /api/v1/shipment-requests/{id}/confirm-from-chat`

Operator or producer confirms a draft captured in chat. Backend decides if it can move to validated/published flow.

### `GET /api/v1/shipment-requests/{id}`

Read one shipment for confirmation or status display.

### `POST /api/v1/admin/handoff`

Create an operator handoff task/event from Kapso.

Expected behavior:

- Record `HUMAN_REVIEW_REQUESTED`.
- Include message/conversation context.
- Do not change business state unless backend rules allow it.
