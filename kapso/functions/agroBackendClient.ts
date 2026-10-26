import { z } from "zod";

export interface AgroBackendEnv {
  AGRO_BACKEND_BASE_URL?: string;
  AGRO_OPERATOR_USER_ID?: string;
  AGRO_OPERATOR_ROLE?: string;
  AGRO_OPERATOR_API_KEY?: string;
}

export class AgroBackendUnavailableError extends Error {
  readonly backendUnavailable = true;

  constructor(message: string) {
    super(message);
    this.name = "AgroBackendUnavailableError";
  }
}

export interface ConversationContext {
  phoneNumber?: string;
  idempotencyKey?: string;
  provider?: string;
  conversationId?: string;
  contactId?: string;
  raw?: unknown;
}

const ShipmentWithOffersSchema = z.array(
  z.object({
    shipment_id: z.string(),
    status: z.string(),
    cargo_category: z.string().nullable().optional(),
    cargo_type: z.string().nullable().optional(),
    quantity_unit: z.string().nullable().optional(),
    livestock_type: z.string().nullable().optional(),
    quantity_estimate: z.union([z.string(), z.number()]).nullable().optional(),
    offers: z.array(
      z.object({
        trip_offer_id: z.string(),
        carrier_id: z.string(),
        response_type: z.string(),
        status: z.string(),
        created_at: z.string(),
      }),
    ),
  }),
);

const ChatDraftsSchema = z.array(
  z.object({
    shipment_id: z.string(),
    status: z.string(),
    cargo_category: z.string().nullable().optional(),
    cargo_type: z.string().nullable().optional(),
    quantity_unit: z.string().nullable().optional(),
    livestock_type: z.string().nullable().optional(),
    quantity_estimate: z.union([z.string(), z.number()]).nullable().optional(),
    operational_notes: z.string().nullable().optional(),
    created_at: z.string(),
    source_phone_number: z.string().nullable().optional(),
  }),
);

const ProducerShipmentsSchema = z.array(
  z.object({
    shipment_id: z.string(),
    status: z.string(),
    cargo_category: z.string().nullable().optional(),
    cargo_type: z.string().nullable().optional(),
    quantity_unit: z.string().nullable().optional(),
    livestock_type: z.string().nullable().optional(),
    quantity_estimate: z.union([z.string(), z.number()]).nullable().optional(),
    operational_notes: z.string().nullable().optional(),
    created_at: z.string(),
    interested_offers_count: z.number(),
  }),
);

const ProducerInterestedOffersSchema = z.array(
  z.object({
    index: z.number(),
    shipment_id: z.string(),
    shipment_status: z.string(),
    trip_offer_id: z.string(),
    carrier_id: z.string(),
    response_type: z.string(),
    offer_status: z.string(),
    cargo_category: z.string().nullable().optional(),
    cargo_type: z.string().nullable().optional(),
    quantity_unit: z.string().nullable().optional(),
    livestock_type: z.string().nullable().optional(),
    quantity_estimate: z.union([z.string(), z.number()]).nullable().optional(),
    created_at: z.string(),
  }),
);

const PendingAssignmentsSchema = z.array(
  z.object({
    assignment_id: z.string(),
    assignment_status: z.string(),
    shipment_id: z.string(),
    cargo_category: z.string().nullable().optional(),
    cargo_type: z.string().nullable().optional(),
    quantity_unit: z.string().nullable().optional(),
    livestock_type: z.string().nullable().optional(),
    quantity_estimate: z.union([z.string(), z.number()]).nullable().optional(),
    carrier_id: z.string(),
    trip_offer_id: z.string().nullable().optional(),
    trip_id: z.string().nullable().optional(),
    trip_status: z.string().nullable().optional(),
    created_at: z.string(),
  }),
);

const OperationSummarySchema = z.object({
  shipment_id: z.string(),
  shipment_status: z.string(),
  assignment_id: z.string(),
  assignment_status: z.string(),
  trip_id: z.string().nullable().optional(),
  trip_status: z.string().nullable().optional(),
  carrier_id: z.string(),
  trip_offer_id: z.string().nullable().optional(),
  cargo_category: z.string().nullable().optional(),
  cargo_type: z.string().nullable().optional(),
  quantity_unit: z.string().nullable().optional(),
  livestock_type: z.string().nullable().optional(),
  quantity_estimate: z.union([z.string(), z.number()]).nullable().optional(),
  operational_notes: z.string().nullable().optional(),
  created_at: z.string(),
});

const OperationSummariesSchema = z.array(OperationSummarySchema);

const TestSessionStatusSchema = z.object({
  enabled: z.boolean(),
  mode: z.string(),
  role_override: z.string().nullable().optional(),
  active_test_run_id: z.string().nullable().optional(),
  phone_number: z.string().nullable().optional(),
  carrier_detected: z.boolean(),
  carrier_id: z.string().nullable().optional(),
});

const JourneyStatusSchema = z.object({
  shipment_id: z.string(),
  shipment_status: z.string(),
  trip_id: z.string().nullable().optional(),
  trip_status: z.string().nullable().optional(),
  assignment_id: z.string().nullable().optional(),
  assignment_status: z.string().nullable().optional(),
  origin: z.string().nullable().optional(),
  destination: z.string().nullable().optional(),
  cargo_category: z.string().nullable().optional(),
  cargo_type: z.string().nullable().optional(),
  quantity_unit: z.string().nullable().optional(),
  livestock_type: z.string().nullable().optional(),
  quantity_estimate: z.union([z.string(), z.number()]).nullable().optional(),
  operational_notes: z.string().nullable().optional(),
  interested_offers_count: z.number(),
  counterparty_id: z.string().nullable().optional(),
  counterparty_name: z.string().nullable().optional(),
  counterparty_phone: z.string().nullable().optional(),
  planned_start_at: z.string().nullable().optional(),
  completed_at: z.string().nullable().optional(),
  created_at: z.string(),
});

const ProducerDashboardSchema = z.object({
  phone_number: z.string(),
  total_shipments: z.number(),
  active_shipments: z.number(),
  active_trips: z.number(),
  completed_trips: z.number(),
  pending_interested_offers: z.number(),
  current_operations: z.array(JourneyStatusSchema),
  past_operations: z.array(JourneyStatusSchema),
});

function backendBaseUrl(env: AgroBackendEnv): string {
  if (!env.AGRO_BACKEND_BASE_URL) {
    throw new Error("Missing AGRO_BACKEND_BASE_URL in Kapso function environment.");
  }
  return env.AGRO_BACKEND_BASE_URL.replace(/\/$/, "");
}

function adminHeaders(env: AgroBackendEnv): Record<string, string> {
  if (!env.AGRO_OPERATOR_USER_ID) {
    throw new Error("Missing AGRO_OPERATOR_USER_ID in Kapso function environment.");
  }
  if (!env.AGRO_OPERATOR_ROLE) {
    throw new Error("Missing AGRO_OPERATOR_ROLE in Kapso function environment.");
  }
  return {
    "Content-Type": "application/json",
    "X-Operator-User-Id": env.AGRO_OPERATOR_USER_ID,
    "X-Operator-Role": env.AGRO_OPERATOR_ROLE,
    ...(env.AGRO_OPERATOR_API_KEY ? { "X-Internal-API-Key": env.AGRO_OPERATOR_API_KEY } : {}),
  };
}

async function requestJson<T>(
  env: AgroBackendEnv,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${backendBaseUrl(env)}${path}`, {
      ...init,
      headers: {
        ...(init.headers || {}),
      },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new AgroBackendUnavailableError(`AGRO backend unavailable: ${message}`);
  }

  const text = await response.text();
  const payload = text ? parseJsonOrNull(text) : null;

  if (!response.ok) {
    if (response.status >= 500) {
      throw new AgroBackendUnavailableError(
        `AGRO backend unavailable ${response.status} ${response.statusText}: ${text.slice(0, 500)}`,
      );
    }
    throw new Error(
      `AGRO backend request failed ${response.status} ${response.statusText}: ${text.slice(0, 500)}`,
    );
  }

  return payload as T;
}

function parseJsonOrNull(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function isBackendUnavailableError(error: unknown): boolean {
  return error instanceof AgroBackendUnavailableError;
}

export async function createShipmentDraftFromText(
  env: AgroBackendEnv,
  text: string,
  context: ConversationContext = {},
): Promise<{ ok: true; shipment_id: string | null; status: string; message: string }> {
  void text;
  void context;
  const drafts = await listRecentChatDrafts(env, undefined, 1);
  const latest = drafts[0];
  return {
    ok: true,
    shipment_id: latest?.shipment_id ?? null,
    status: latest?.status ?? "DRAFT_PENDING_OPERATOR_REVIEW",
    message: "Producer confirmation is handled by the AGRO backend webhook.",
  };
}

export async function createShipmentDraftFromTextRaw(
  env: AgroBackendEnv,
  text: string,
  phoneNumber?: string,
  idempotencyKey?: string,
): Promise<{ ok: true; shipment_id: string | null; status: string; message: string }> {
  return createShipmentDraftFromText(env, text, { phoneNumber, idempotencyKey });
}

export async function publishShipment(
  env: AgroBackendEnv,
  shipmentId: string,
  carrierIds: string[],
  idempotencyKey = `kapso_publish_${shipmentId}`,
): Promise<unknown> {
  return requestJson(env, `/api/v1/shipment-requests/${encodeURIComponent(shipmentId)}/publish`, {
    method: "POST",
    headers: adminHeaders(env),
    body: JSON.stringify({
      carrier_ids: carrierIds,
      idempotency_key: idempotencyKey,
    }),
  });
}

export async function validateShipment(
  env: AgroBackendEnv,
  shipmentId: string,
  notes = "Validado desde Kapso",
  idempotencyKey = `kapso_validate_${shipmentId}`,
): Promise<unknown> {
  return requestJson(env, `/api/v1/shipment-requests/${encodeURIComponent(shipmentId)}/validate`, {
    method: "POST",
    headers: adminHeaders(env),
    body: JSON.stringify({
      notes,
      idempotency_key: idempotencyKey,
    }),
  });
}

export async function listShipmentsWithOffers(env: AgroBackendEnv) {
  const payload = await requestJson<unknown>(env, "/api/v1/admin/shipments/with-offers", {
    method: "GET",
    headers: { "Content-Type": "application/json" },
  });
  return ShipmentWithOffersSchema.parse(payload);
}

export async function listOperatorLoads(env: AgroBackendEnv, limit = 10) {
  const shipments = await listShipmentsWithOffers(env);
  const active_assignments = await listActiveAssignments(env, limit).catch(() => []);
  const selectable_offers = shipments
    .filter((shipment) => shipment.status === "MATCHING")
    .flatMap((shipment) =>
      shipment.offers
        .filter((offer) => offer.response_type === "INTERESTED")
        .map((offer, index) => ({
          index: index + 1,
          shipment_id: shipment.shipment_id,
          shipment_status: shipment.status,
          cargo_category: shipment.cargo_category ?? null,
          cargo_type: shipment.cargo_type ?? shipment.livestock_type ?? null,
          quantity_unit: shipment.quantity_unit ?? null,
          livestock_type: shipment.livestock_type ?? null,
          quantity_estimate: shipment.quantity_estimate ?? null,
          trip_offer_id: offer.trip_offer_id,
          carrier_id: offer.carrier_id,
          response_type: offer.response_type,
          offer_status: offer.status,
          offer_created_at: offer.created_at,
        })),
    )
    .slice(0, limit)
    .map((offer, index) => ({ ...offer, index: index + 1 }));
  return {
    ok: true as const,
    selectable_offers,
    advanced_loads: active_assignments.map((assignment, index) => ({
      index: index + 1,
      shipment_id: assignment.shipment_id,
      assignment_id: assignment.assignment_id,
      assignment_status: assignment.assignment_status,
      trip_id: assignment.trip_id ?? null,
      trip_status: assignment.trip_status ?? null,
      cargo_category: assignment.cargo_category ?? null,
      cargo_type: assignment.cargo_type ?? assignment.livestock_type ?? null,
      quantity_unit: assignment.quantity_unit ?? null,
      livestock_type: assignment.livestock_type ?? null,
      quantity_estimate: assignment.quantity_estimate ?? null,
      carrier_id: assignment.carrier_id,
      trip_offer_id: assignment.trip_offer_id ?? null,
    })),
    counts: {
      published_or_matching_shipments: shipments.length,
      selectable_offers: selectable_offers.length,
      advanced_loads: active_assignments.length,
    },
  };
}

export async function listDraftShipments(env: AgroBackendEnv, limit = 10) {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  const payload = await requestJson<unknown>(env, `/api/v1/admin/shipments/drafts?${params.toString()}`, {
    method: "GET",
    headers: adminHeaders(env),
  });
  return ChatDraftsSchema.parse(payload);
}

export async function listRecentChatDrafts(
  env: AgroBackendEnv,
  phoneNumber?: string,
  limit = 3,
) {
  const params = new URLSearchParams();
  if (phoneNumber) {
    params.set("phone_number", phoneNumber);
  }
  params.set("limit", String(limit));
  const payload = await requestJson<unknown>(
    env,
    `/api/v1/admin/shipments/from-chat/recent?${params.toString()}`,
    {
      method: "GET",
      headers: adminHeaders(env),
    },
  );
  return ChatDraftsSchema.parse(payload);
}

export async function listProducerShipments(
  env: AgroBackendEnv,
  phoneNumber: string,
  limit = 5,
) {
  if (!phoneNumber) {
    return {
      ok: false as const,
      error: "phoneNumber is required",
      backend_unavailable: false,
      shipments: [],
    };
  }
  const params = new URLSearchParams();
  params.set("phone_number", phoneNumber);
  params.set("limit", String(limit));
  try {
    const payload = await requestJson<unknown>(env, `/api/v1/producer/shipments?${params.toString()}`, {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });
    return {
      ok: true as const,
      shipments: ProducerShipmentsSchema.parse(payload),
      backend_unavailable: false,
    };
  } catch (error) {
    if (isBackendUnavailableError(error)) {
      const message = error instanceof Error ? error.message : String(error);
      return {
        ok: false as const,
        error: message,
        backend_unavailable: true,
        shipments: [],
      };
    }
    throw error;
  }
}

export async function listProducerInterestedOffers(
  env: AgroBackendEnv,
  phoneNumber: string,
  limit = 10,
) {
  if (!phoneNumber) {
    return {
      ok: false as const,
      error: "phoneNumber is required",
      backend_unavailable: false,
      offers: [],
    };
  }
  const params = new URLSearchParams();
  params.set("phone_number", phoneNumber);
  params.set("limit", String(limit));
  try {
    const payload = await requestJson<unknown>(
      env,
      `/api/v1/producer/shipments/interested-offers?${params.toString()}`,
      {
        method: "GET",
        headers: { "Content-Type": "application/json" },
      },
    );
    return {
      ok: true as const,
      offers: ProducerInterestedOffersSchema.parse(payload),
      backend_unavailable: false,
    };
  } catch (error) {
    if (isBackendUnavailableError(error)) {
      const message = error instanceof Error ? error.message : String(error);
      return {
        ok: false as const,
        error: message,
        backend_unavailable: true,
        offers: [],
      };
    }
    throw error;
  }
}

export async function getProducerDashboard(
  env: AgroBackendEnv,
  phoneNumber: string,
  limit = 12,
) {
  if (!phoneNumber) {
    return {
      ok: false as const,
      error: "phoneNumber is required",
      backend_unavailable: false,
      dashboard: null,
    };
  }
  const params = new URLSearchParams();
  params.set("phone_number", phoneNumber);
  params.set("limit", String(limit));
  try {
    const payload = await requestJson<unknown>(
      env,
      `/api/v1/producer/dashboard?${params.toString()}`,
      {
        method: "GET",
        headers: { "Content-Type": "application/json" },
      },
    );
    return {
      ok: true as const,
      dashboard: ProducerDashboardSchema.parse(payload),
      backend_unavailable: false,
    };
  } catch (error) {
    if (isBackendUnavailableError(error)) {
      const message = error instanceof Error ? error.message : String(error);
      return {
        ok: false as const,
        error: message,
        backend_unavailable: true,
        dashboard: null,
      };
    }
    throw error;
  }
}

export async function acceptProducerOffer(
  env: AgroBackendEnv,
  shipmentId: string,
  tripOfferId: string,
  phoneNumber: string,
  idempotencyKey = `kapso_producer_accept_${shipmentId}_${tripOfferId}`,
): Promise<unknown> {
  return requestJson(
    env,
    `/api/v1/shipments/${encodeURIComponent(shipmentId)}/offers/${encodeURIComponent(tripOfferId)}/accept`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        phone_number: phoneNumber,
        idempotency_key: idempotencyKey,
      }),
    },
  );
}

export async function acceptProducerOfferByIndex(
  env: AgroBackendEnv,
  selectionIndex: number,
  phoneNumber: string,
  limit = 10,
): Promise<unknown> {
  const listed = await listProducerInterestedOffers(env, phoneNumber, limit);
  if (!listed.ok) {
    return listed;
  }
  const selected = listed.offers[selectionIndex - 1];
  if (!selected) {
    throw new Error(`No producer interested offer found for index ${selectionIndex}.`);
  }
  return acceptProducerOffer(env, selected.shipment_id, selected.trip_offer_id, phoneNumber);
}

export async function getTestSessionStatus(env: AgroBackendEnv, phoneNumber: string) {
  const params = new URLSearchParams();
  params.set("phone_number", phoneNumber);
  const payload = await requestJson<unknown>(
    env,
    `/api/v1/admin/test/session-status?${params.toString()}`,
    {
      method: "GET",
      headers: adminHeaders(env),
    },
  );
  return TestSessionStatusSchema.parse(payload);
}

export async function selectOffer(
  env: AgroBackendEnv,
  shipmentId: string,
  tripOfferId: string,
  idempotencyKey = `kapso_select_${shipmentId}_${tripOfferId}`,
): Promise<unknown> {
  return requestJson(env, `/api/v1/shipments/${encodeURIComponent(shipmentId)}/select-offer`, {
    method: "POST",
    headers: adminHeaders(env),
    body: JSON.stringify({
      trip_offer_id: tripOfferId,
      idempotency_key: idempotencyKey,
    }),
  });
}

export async function selectOfferByIndex(
  env: AgroBackendEnv,
  selectionIndex: number,
  limit = 10,
): Promise<unknown> {
  const shipments = await listShipmentsWithOffers(env);
  const selectableOffers = shipments
    .filter((shipment) => shipment.status === "MATCHING")
    .flatMap((shipment) =>
      shipment.offers
        .filter((offer) => offer.response_type === "INTERESTED")
        .map((offer) => ({
          shipment_id: shipment.shipment_id,
          trip_offer_id: offer.trip_offer_id,
        })),
    )
    .slice(0, limit);
  const selected = selectableOffers[selectionIndex - 1];
  if (!selected) {
    throw new Error(`No selectable offer found for index ${selectionIndex}.`);
  }
  return selectOffer(env, selected.shipment_id, selected.trip_offer_id);
}

export async function listPendingAssignments(env: AgroBackendEnv, limit = 10) {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  const payload = await requestJson<unknown>(env, `/api/v1/admin/assignments/pending?${params.toString()}`, {
    method: "GET",
    headers: adminHeaders(env),
  });
  return PendingAssignmentsSchema.parse(payload).map((assignment, index) => ({ index: index + 1, ...assignment }));
}

export async function listActiveAssignments(env: AgroBackendEnv, limit = 10) {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  const payload = await requestJson<unknown>(env, `/api/v1/admin/assignments/active?${params.toString()}`, {
    method: "GET",
    headers: adminHeaders(env),
  });
  return OperationSummariesSchema.parse(payload).map((operation, index) => ({ index: index + 1, ...operation }));
}

export async function lookupOperation(env: AgroBackendEnv, entityId: string) {
  const payload = await requestJson<unknown>(env, `/api/v1/admin/operations/lookup/${encodeURIComponent(entityId)}`, {
    method: "GET",
    headers: adminHeaders(env),
  });
  return OperationSummarySchema.parse(payload);
}

export async function confirmAssignment(
  env: AgroBackendEnv,
  assignmentId: string,
  confirmationNotes = "Confirmado desde Kapso",
  idempotencyKey = `kapso_confirm_${assignmentId}`,
): Promise<unknown> {
  return requestJson(env, `/api/v1/assignments/${encodeURIComponent(assignmentId)}/confirm`, {
    method: "POST",
    headers: adminHeaders(env),
    body: JSON.stringify({
      confirmation_notes: confirmationNotes,
      idempotency_key: idempotencyKey,
    }),
  });
}

export async function confirmAssignmentByIndex(
  env: AgroBackendEnv,
  selectionIndex: number,
  limit = 10,
): Promise<unknown> {
  const assignments = await listPendingAssignments(env, limit);
  const selected = assignments[selectionIndex - 1];
  if (!selected) {
    throw new Error(`No pending assignment found for index ${selectionIndex}.`);
  }
  return confirmAssignment(env, selected.assignment_id);
}

export async function cancelTrip(
  env: AgroBackendEnv,
  tripId: string,
  reason: string,
  idempotencyKey = `kapso_cancel_${tripId}`,
): Promise<unknown> {
  return requestJson(env, `/api/v1/trips/${encodeURIComponent(tripId)}/cancel`, {
    method: "POST",
    headers: adminHeaders(env),
    body: JSON.stringify({
      reason,
      idempotency_key: idempotencyKey,
    }),
  });
}

export async function logConversationEvent(
  env: AgroBackendEnv,
  event: Record<string, unknown>,
): Promise<unknown> {
  // TODO backend endpoint recommended:
  // POST /api/v1/admin/handoff or POST /api/v1/conversation-events
  // For now this returns the payload so Kapso can continue without pretending
  // that an audit event was persisted.
  void env;
  return {
    persisted: false,
    todo: "Backend endpoint required for generic conversation events.",
    event,
  };
}

export default {
  createShipmentDraftFromText,
  validateShipment,
  publishShipment,
  listOperatorLoads,
  listShipmentsWithOffers,
  listDraftShipments,
  listRecentChatDrafts,
  listProducerShipments,
  listProducerInterestedOffers,
  getProducerDashboard,
  acceptProducerOffer,
  acceptProducerOfferByIndex,
  selectOffer,
  selectOfferByIndex,
  listPendingAssignments,
  listActiveAssignments,
  lookupOperation,
  confirmAssignment,
  confirmAssignmentByIndex,
  cancelTrip,
  logConversationEvent,
  getTestSessionStatus,
};

export function toolNameFromKapsoBody(body: Record<string, unknown>): string | null {
  const flowEventToolName = findToolNameInFlowEvents(body.flow_events);
  return (
    stringOrNull(body.tool_name) ||
    stringOrNull(body.toolName) ||
    stringOrNull(body.name) ||
    stringOrNull(body.function_name) ||
    stringOrNull(body.functionName) ||
    stringOrNull((body.function as Record<string, unknown> | undefined)?.name) ||
    stringOrNull((body.tool as Record<string, unknown> | undefined)?.name) ||
    stringOrNull((body.flow_agent_tool as Record<string, unknown> | undefined)?.name) ||
    stringOrNull((body.flow_info as Record<string, unknown> | undefined)?.tool_name) ||
    stringOrNull((body.flow_info as Record<string, unknown> | undefined)?.toolName) ||
    stringOrNull((body.execution_context as Record<string, unknown> | undefined)?.tool_name) ||
    stringOrNull((body.execution_context as Record<string, unknown> | undefined)?.toolName) ||
    flowEventToolName
  );
}

function findToolNameInFlowEvents(flowEvents: unknown): string | null {
  if (!flowEvents) {
    return null;
  }
  const events = Array.isArray(flowEvents) ? flowEvents : [flowEvents];
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (!event || typeof event !== "object") {
      continue;
    }
    const record = event as Record<string, unknown>;
    const payload =
      record.payload && typeof record.payload === "object"
        ? (record.payload as Record<string, unknown>)
        : undefined;
    const toolName =
      stringOrNull(record.tool_name) ||
      stringOrNull(record.toolName) ||
      stringOrNull(record.name) ||
      stringOrNull(payload?.tool_name) ||
      stringOrNull(payload?.toolName) ||
      stringOrNull(payload?.name) ||
      stringOrNull(payload?.function_name) ||
      stringOrNull(payload?.functionName);
    if (toolName) {
      return toolName;
    }
  }
  return null;
}

function stringOrNull(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}
