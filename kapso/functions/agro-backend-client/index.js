async function handler(request, env) {
  const body = await request.json().catch(() => ({}));
  if (isWorkflowFunctionNodeInvocation(body)) {
    return await previewInboundLoadForWorkflow(body, env);
  }
  const input = normalizeInput(body.input || body.arguments || body);
  const context = body.execution_context?.context || {};
  const action = inferAction(body, input);
  const resolvedPhoneNumber =
    input.phone_number || input.phoneNumber || phoneNumberFromContext(body, context);
  console.log("AGRO_BACKEND_CLIENT_CALL", {
    action,
    input: redactDebugValue(input),
    resolved_phone_number: maskPhone(resolvedPhoneNumber),
    agro_backend_base_url: env.AGRO_BACKEND_BASE_URL || null,
    agro_backend_fallback_base_url: env.AGRO_BACKEND_FALLBACK_BASE_URL || null,
    operator_user_id_present: Boolean(env.AGRO_OPERATOR_USER_ID),
    operator_role: env.AGRO_OPERATOR_ROLE || null,
  });

  try {
    if (action === "createShipmentDraftFromText") {
      return json(
        await acknowledgeProducerConfirmation(
          env,
          input.text,
          resolvedPhoneNumber,
          input.idempotency_key || input.idempotencyKey || idempotencyKeyFromContext(body),
        ),
      );
    }

    if (action === "previewShipmentFromText") {
      return json(await previewShipmentFromText(env, input.text));
    }

    if (action === "publishShipment") {
      return json(await publishShipment(env, input.shipmentId, input.carrierIds, input.idempotencyKey));
    }

    if (action === "validateShipment") {
      return json(await validateShipment(env, input.shipmentId, input.notes, input.idempotencyKey));
    }

    if (action === "listShipmentsWithOffers") {
      return json(await listShipmentsWithOffers(env));
    }

    if (action === "listOperatorLoads") {
      return json(await listOperatorLoads(env, input.limit));
    }

    if (action === "selectOfferByIndex") {
      return json(
        await selectOfferByIndex(
          env,
          input.selectionIndex || input.index || input.number,
          input.limit,
          input.idempotencyKey || input.idempotency_key,
        ),
      );
    }

    if (action === "listDraftShipments") {
      return json(await listDraftShipments(env, input.limit));
    }

    if (action === "listPendingAssignments") {
      return json(await listPendingAssignments(env, input.limit));
    }

    if (action === "listActiveAssignments") {
      return json(await listActiveAssignments(env, input.limit));
    }

    if (action === "lookupOperation") {
      return json(await lookupOperation(env, input.entityId || input.entity_id || input.id));
    }

    if (action === "confirmAssignment") {
      return json(
        await confirmAssignment(
          env,
          input.assignmentId || input.assignment_id,
          input.confirmationNotes || input.confirmation_notes || input.notes,
          input.idempotencyKey || input.idempotency_key,
        ),
      );
    }

    if (action === "confirmAssignmentByIndex") {
      return json(
        await confirmAssignmentByIndex(
          env,
          input.selectionIndex || input.index || input.number,
          input.limit,
          input.confirmationNotes || input.confirmation_notes || input.notes,
          input.idempotencyKey || input.idempotency_key,
        ),
      );
    }

    if (action === "cancelTrip") {
      return json(
        await cancelTrip(
          env,
          input.tripId || input.trip_id,
          input.reason,
          input.idempotencyKey || input.idempotency_key,
        ),
      );
    }

    if (action === "listRecentChatDrafts") {
      return json(
        await listRecentChatDrafts(
          env,
          resolvedPhoneNumber,
          input.limit,
        ),
      );
    }

    if (action === "listProducerShipments") {
      return json(
        await listProducerShipments(
          env,
          resolvedPhoneNumber,
          input.limit,
        ),
      );
    }

    if (action === "listProducerInterestedOffers") {
      return json(
        await listProducerInterestedOffers(
          env,
          resolvedPhoneNumber,
          input.limit,
        ),
      );
    }

    if (action === "getProducerDashboard") {
      return json(
        await getProducerDashboard(
          env,
          resolvedPhoneNumber,
          input.limit,
        ),
      );
    }

    if (action === "acceptProducerOfferByIndex") {
      return json(
        await acceptProducerOfferByIndex(
          env,
          input.selectionIndex || input.index || input.number,
          resolvedPhoneNumber,
          input.limit,
          input.idempotencyKey || input.idempotency_key,
        ),
      );
    }

    if (action === "acceptProducerOffer") {
      return json(
        await acceptProducerOffer(
          env,
          input.shipmentId || input.shipment_id,
          input.tripOfferId || input.trip_offer_id,
          resolvedPhoneNumber,
          input.idempotencyKey || input.idempotency_key,
        ),
      );
    }

    if (action === "getTestSessionStatus") {
      return json(
        await getTestSessionStatus(
          env,
          resolvedPhoneNumber,
        ),
      );
    }

    if (action === "selectOffer") {
      return json(
        await selectOffer(
          env,
          input.shipmentId || input.shipment_id,
          input.tripOfferId || input.trip_offer_id,
          input.idempotencyKey || input.idempotency_key,
        ),
      );
    }

    if (action === "logConversationEvent") {
      return json(await logConversationEvent(input.event));
    }

    return json(
      {
        ok: false,
        action,
        error: "Unsupported action.",
        debug: {
          input: redactDebugValue(input),
          tool_name: toolNameFromBody(body),
        },
        supported_actions: [
          "createShipmentDraftFromText",
          "previewShipmentFromText",
          "publishShipment",
          "validateShipment",
          "listOperatorLoads",
          "listShipmentsWithOffers",
          "selectOfferByIndex",
          "listDraftShipments",
          "listPendingAssignments",
          "listActiveAssignments",
          "lookupOperation",
          "confirmAssignment",
          "confirmAssignmentByIndex",
          "cancelTrip",
          "listRecentChatDrafts",
          "listProducerShipments",
          "listProducerInterestedOffers",
          "getProducerDashboard",
          "acceptProducerOfferByIndex",
          "acceptProducerOffer",
          "getTestSessionStatus",
          "selectOffer",
          "logConversationEvent",
        ],
      },
      200,
    );
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    console.log("AGRO_BACKEND_CLIENT_ERROR", {
      action,
      error_message: errorMessage,
      resolved_phone_number: maskPhone(resolvedPhoneNumber),
      agro_backend_base_url: env.AGRO_BACKEND_BASE_URL || null,
      agro_backend_fallback_base_url: env.AGRO_BACKEND_FALLBACK_BASE_URL || null,
    });
    return json(
      {
        ok: false,
        action,
        error: errorMessage,
        debug: {
          url: debugUrl(env, action),
          input: redactDebugValue(input),
          env: {
            agro_backend_base_url: env.AGRO_BACKEND_BASE_URL || null,
            agro_backend_fallback_base_url: env.AGRO_BACKEND_FALLBACK_BASE_URL || null,
            operator_user_id_present: Boolean(env.AGRO_OPERATOR_USER_ID),
            operator_role: env.AGRO_OPERATOR_ROLE || null,
          },
        },
      },
      200,
    );
  }
}

function isWorkflowFunctionNodeInvocation(body) {
  const executionContext = body?.execution_context || body?.executionContext;
  const flowEvents = body?.flow_events || body?.flowEvents;
  return Boolean(
    body &&
      typeof body === "object" &&
      executionContext &&
      Array.isArray(flowEvents) &&
      !body.input &&
      !body.arguments &&
      !body.action,
  );
}

async function previewInboundLoadForWorkflow(body, env) {
  const executionContext = body.execution_context || body.executionContext || {};
  const whatsappContext = body.whatsapp_context || body.whatsappContext || {};
  const text = findInboundMessageText({
    lastUserInput:
      executionContext.vars?.lastUserInput || executionContext.vars?.last_user_input,
    messages: whatsappContext.messages,
    events: body.flow_events || body.flowEvents,
  });
  if (!text || !looksLikeLoadRequest(text)) {
    return json({ vars: { canonical_preview_ready: false, canonical_preview_summary: "" } });
  }

  try {
    const preview = await previewShipmentFromText(env, text);
    if (!preview.ok || !preview.confirmation_summary) {
      return json({ vars: { canonical_preview_ready: false, canonical_preview_summary: "" } });
    }
    return json({
      vars: {
        canonical_preview_ready: true,
        canonical_preview_summary: preview.confirmation_summary,
      },
    });
  } catch {
    return json({ vars: { canonical_preview_ready: false, canonical_preview_summary: "" } });
  }
}

function findInboundMessageText(value, depth = 0) {
  if (depth > 8 || value == null) return null;
  if (Array.isArray(value)) {
    for (let index = value.length - 1; index >= 0; index -= 1) {
      const found = findInboundMessageText(value[index], depth + 1);
      if (found) return found;
    }
    return null;
  }
  if (typeof value !== "object") return null;

  if (typeof value.lastUserInput === "string" && value.lastUserInput.trim()) {
    return value.lastUserInput.trim();
  }
  if (typeof value.last_user_input === "string" && value.last_user_input.trim()) {
    return value.last_user_input.trim();
  }

  for (const key of ["text", "body", "content", "message_text", "messageText"]) {
    const candidate = value[key];
    if (typeof candidate === "string" && candidate.trim()) return candidate.trim();
    if (candidate && typeof candidate === "object") {
      const nested = findInboundMessageText(candidate, depth + 1);
      if (nested) return nested;
    }
  }
  for (const key of [
    "payload",
    "message",
    "messages",
    "rawMessage",
    "raw_message",
    "data",
    "event",
    "events",
    "value",
  ]) {
    const found = findInboundMessageText(value[key], depth + 1);
    if (found) return found;
  }
  return null;
}

function looksLikeLoadRequest(text) {
  return /\b(vacas?|toros?|novillos?|terneros?|terneras?|vaquillonas?|hacienda|soja|ma[ií]z|trigo|girasol|sorgo|cebada)\b/i.test(
    text,
  ) && /\b(transportar|necesito|carga|llevar|mover|mandar|camiones?)\b/i.test(text);
}

async function createShipmentDraftFromText(env, text, phoneNumber, idempotencyKey) {
  if (!text) {
    return { ok: false, error: "text is required" };
  }

  const payload = {
    text,
    phone_number: phoneNumber || null,
    idempotency_key: idempotencyKey || null,
  };
  const path = "/api/v1/shipment-requests/from-chat";
  console.log("CALLING BACKEND", {
    url: `${backendBaseUrl(env)}${path}`,
    payload: redactDebugValue(payload),
  });

  const response = await backendRequest(env, path, {
    method: "POST",
    headers: adminHeaders(env),
    body: JSON.stringify(payload),
  });

  return {
    ok: true,
    shipment_id: response.data.shipment_id,
    status: response.data.status,
  };
}

async function previewShipmentFromText(env, text) {
  if (!text || !String(text).trim()) {
    return { ok: false, error: "text is required" };
  }
  const response = await backendRequest(env, "/api/v1/admin/shipments/chat-preview", {
    method: "POST",
    headers: adminHeaders(env),
    body: JSON.stringify({ text: String(text) }),
  });
  return { ok: true, ...response.data };
}

async function acknowledgeProducerConfirmation(env, text, phoneNumber, idempotencyKey) {
  console.log("CREATE_SHIPMENT_DRAFT_TOOL_DISABLED", {
    reason: "producer_confirmation_is_handled_by_backend_webhook",
    text_present: Boolean(text),
    phone_number: maskPhone(phoneNumber),
    idempotency_key_present: Boolean(idempotencyKey),
  });

  const recent = await listRecentChatDrafts(env, null, 1).catch((error) => ({
    ok: false,
    error: error instanceof Error ? error.message : String(error),
    drafts: [],
  }));

  const latest = Array.isArray(recent.drafts) ? recent.drafts[0] : null;
  return {
    ok: true,
    status: latest?.status || "DRAFT_PENDING_OPERATOR_REVIEW",
    shipment_id: latest?.shipment_id || null,
    message: "Producer confirmation is handled by the AGRO backend webhook.",
    draft_lookup: recent,
  };
}

async function publishShipment(env, shipmentId, carrierIds, idempotencyKey) {
  if (!shipmentId || !Array.isArray(carrierIds)) {
    return { ok: false, error: "shipmentId and carrierIds are required" };
  }
  const normalizedCarrierIds = normalizeCarrierIds(carrierIds);
  if (normalizedCarrierIds.length === 0) {
    return { ok: false, error: "At least one carrier id is required" };
  }

  const response = await backendRequest(env, `/api/v1/shipment-requests/${encodeURIComponent(shipmentId)}/publish`, {
    method: "POST",
    headers: adminHeaders(env),
    body: JSON.stringify({
      carrier_ids: normalizedCarrierIds,
      idempotency_key: idempotencyKey || `kapso_publish_${shipmentId}`,
    }),
  });

  return { ok: true, data: response.data };
}

function normalizeCarrierIds(carrierIds) {
  return carrierIds
    .map((carrierId) => String(carrierId || "").trim())
    .filter(Boolean)
    .map((carrierId) => carrierId.replace(/^(el|la|los|las)[_ -]+/i, ""))
    .map((carrierId) => carrierId.replace(/[.,;:]$/g, ""))
    .filter(Boolean);
}

async function validateShipment(env, shipmentId, notes, idempotencyKey) {
  if (!shipmentId) {
    return { ok: false, error: "shipmentId is required" };
  }

  const response = await backendRequest(env, `/api/v1/shipment-requests/${encodeURIComponent(shipmentId)}/validate`, {
    method: "POST",
    headers: adminHeaders(env),
    body: JSON.stringify({
      notes: notes || "Validado desde Kapso",
      idempotency_key: idempotencyKey || `kapso_validate_${shipmentId}`,
    }),
  });

  return { ok: true, data: response.data };
}

async function listShipmentsWithOffers(env) {
  const response = await backendRequest(env, "/api/v1/admin/shipments/with-offers", {
    method: "GET",
    headers: { "Content-Type": "application/json" },
  });

  return { ok: true, shipments: response.data };
}

async function listOperatorLoads(env, limit) {
  const listed = await listShipmentsWithOffers(env);
  const activeAssignmentsResult = await listActiveAssignments(env, limit).catch((error) => ({
    ok: false,
    error: error instanceof Error ? error.message : String(error),
    operations: [],
  }));
  const activeAssignments = Array.isArray(activeAssignmentsResult.operations) ? activeAssignmentsResult.operations : [];
  const shipments = Array.isArray(listed.shipments) ? listed.shipments : [];
  const selectableOffers = selectableInterestedOffers(shipments, limit);
  return {
    ok: true,
    selectable_offers: selectableOffers,
    advanced_loads: activeAssignments.map((assignment, index) => ({
      index: index + 1,
      shipment_id: assignment.shipment_id,
      assignment_id: assignment.assignment_id,
      assignment_status: assignment.assignment_status,
      trip_id: assignment.trip_id || null,
      trip_status: assignment.trip_status || null,
      cargo_category: assignment.cargo_category || null,
      cargo_type: assignment.cargo_type || assignment.livestock_type || null,
      quantity_unit: assignment.quantity_unit || null,
      livestock_type: assignment.livestock_type || null,
      quantity_estimate: assignment.quantity_estimate || null,
      carrier_id: assignment.carrier_id,
      trip_offer_id: assignment.trip_offer_id || null,
    })),
    counts: {
      published_or_matching_shipments: shipments.length,
      selectable_offers: selectableOffers.length,
      advanced_loads: activeAssignments.length,
    },
    note: "For ver cargas, show only selectable_offers and advanced_loads. Do not list generic shipments.",
  };
}

async function selectOfferByIndex(env, selectionIndex, limit, idempotencyKey) {
  const index = parseSelectionIndex(selectionIndex);
  if (index === null) {
    return { ok: false, error: "selectionIndex must be a positive number." };
  }

  const listed = await listShipmentsWithOffers(env);
  const selectableOffers = selectableInterestedOffers(listed.shipments, limit);
  const selected = selectableOffers[index - 1];
  if (!selected) {
    return {
      ok: false,
      error: `No selectable offer found for index ${index}.`,
      selectable_offers: selectableOffers,
    };
  }

  const result = await selectOffer(
    env,
    selected.shipment_id,
    selected.trip_offer_id,
    idempotencyKey || `kapso_select_index_${selected.shipment_id}_${selected.trip_offer_id}`,
  );

  return {
    ok: true,
    selected_offer: selected,
    already_active_assignment: Array.isArray(result.data?.event_types) && result.data.event_types.length === 0,
    data: result.data,
  };
}

function selectableInterestedOffers(shipments, limit) {
  const maxRows = Math.max(1, Math.min(Number(limit || 10), 50));
  const rows = [];
  for (const shipment of Array.isArray(shipments) ? shipments : []) {
    if (shipment.status !== "MATCHING") {
      continue;
    }
    for (const offer of Array.isArray(shipment.offers) ? shipment.offers : []) {
      if (offer.response_type !== "INTERESTED") {
        continue;
      }
      rows.push({
        index: rows.length + 1,
        shipment_id: shipment.shipment_id,
        shipment_status: shipment.status,
        cargo_category: shipment.cargo_category || null,
        cargo_type: shipment.cargo_type || shipment.livestock_type || null,
        quantity_unit: shipment.quantity_unit || null,
        livestock_type: shipment.livestock_type || null,
        quantity_estimate: shipment.quantity_estimate || null,
        trip_offer_id: offer.trip_offer_id,
        carrier_id: offer.carrier_id,
        response_type: offer.response_type,
        offer_status: offer.status,
        offer_created_at: offer.created_at,
      });
      if (rows.length >= maxRows) {
        return rows;
      }
    }
  }
  return rows;
}

async function listDraftShipments(env, limit) {
  const params = new URLSearchParams();
  params.set("limit", String(limit || 10));
  const response = await backendRequest(env, `/api/v1/admin/shipments/drafts?${params.toString()}`, {
    method: "GET",
    headers: adminHeaders(env),
  });

  return { ok: true, drafts: response.data };
}

async function listPendingAssignments(env, limit) {
  const params = new URLSearchParams();
  params.set("limit", String(limit || 10));
  const response = await backendRequest(env, `/api/v1/admin/assignments/pending?${params.toString()}`, {
    method: "GET",
    headers: adminHeaders(env),
  });

  const assignments = Array.isArray(response.data)
    ? response.data.map((assignment, index) => ({ index: index + 1, ...assignment }))
    : [];
  return { ok: true, assignments };
}

async function listActiveAssignments(env, limit) {
  const params = new URLSearchParams();
  params.set("limit", String(limit || 10));
  const response = await backendRequest(env, `/api/v1/admin/assignments/active?${params.toString()}`, {
    method: "GET",
    headers: adminHeaders(env),
  });

  const operations = Array.isArray(response.data)
    ? response.data.map((operation, index) => ({ index: index + 1, ...operation }))
    : [];
  return { ok: true, operations };
}

async function lookupOperation(env, entityId) {
  if (!entityId) {
    return { ok: false, error: "entityId is required" };
  }

  const response = await backendRequest(env, `/api/v1/admin/operations/lookup/${encodeURIComponent(entityId)}`, {
    method: "GET",
    headers: adminHeaders(env),
  });
  return { ok: true, operation: response.data };
}

async function confirmAssignment(env, assignmentId, confirmationNotes, idempotencyKey) {
  if (!assignmentId) {
    return { ok: false, error: "assignmentId is required" };
  }

  const response = await backendRequest(env, `/api/v1/assignments/${encodeURIComponent(assignmentId)}/confirm`, {
    method: "POST",
    headers: adminHeaders(env),
    body: JSON.stringify({
      confirmation_notes: confirmationNotes || "Confirmado desde WhatsApp operador",
      idempotency_key: idempotencyKey || `kapso_confirm_${assignmentId}`,
    }),
  });

  return { ok: true, data: response.data };
}

async function confirmAssignmentByIndex(env, selectionIndex, limit, confirmationNotes, idempotencyKey) {
  const index = parseSelectionIndex(selectionIndex);
  if (index === null) {
    return { ok: false, error: "selectionIndex must be a positive number." };
  }

  const listed = await listPendingAssignments(env, limit);
  const selected = listed.assignments[index - 1];
  if (!selected) {
    return {
      ok: false,
      error: `No pending assignment found for index ${index}.`,
      assignments: listed.assignments,
    };
  }

  const result = await confirmAssignment(
    env,
    selected.assignment_id,
    confirmationNotes,
    idempotencyKey || `kapso_confirm_index_${selected.assignment_id}`,
  );

  return {
    ok: true,
    selected_assignment: selected,
    data: result.data,
  };
}

async function cancelTrip(env, tripId, reason, idempotencyKey) {
  if (!tripId) {
    return { ok: false, error: "tripId is required" };
  }
  if (!reason || !String(reason).trim()) {
    return { ok: false, error: "reason is required" };
  }

  const response = await backendRequest(env, `/api/v1/trips/${encodeURIComponent(tripId)}/cancel`, {
    method: "POST",
    headers: adminHeaders(env),
    body: JSON.stringify({
      reason: String(reason).trim(),
      idempotency_key: idempotencyKey || `kapso_cancel_${tripId}_${stableReasonKey(reason)}`,
    }),
  });

  return { ok: true, trip: response.data };
}

function stableReasonKey(reason) {
  return String(reason || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 40) || "sin_motivo";
}

function parseSelectionIndex(value) {
  const parsed = Number(String(value || "").trim());
  if (!Number.isInteger(parsed) || parsed < 1) {
    return null;
  }
  return parsed;
}

async function listRecentChatDrafts(env, phoneNumber, limit) {
  const effectiveLimit = limit || 3;
  const response = await backendRequest(env, recentChatDraftsPath(phoneNumber, effectiveLimit), {
    method: "GET",
    headers: adminHeaders(env),
  });
  let drafts = response.data;

  if (Array.isArray(drafts) && drafts.length === 0) {
    const devFallbackUrl = currentDevBackendFallbackUrl(env);
    if (devFallbackUrl && devFallbackUrl !== backendBaseUrl(env)) {
      console.log("RECENT_CHAT_DRAFTS_EMPTY_RETRY_DEV_FALLBACK", {
        fallback_url: devFallbackUrl,
      });
      const fallbackResponse = await singleBackendRequest(devFallbackUrl, recentChatDraftsPath(null, effectiveLimit), {
        method: "GET",
        headers: adminHeaders(env),
      });
      drafts = fallbackResponse.data;
    }
  }

  if (phoneNumber) {
    console.log("RECENT_CHAT_DRAFTS_PHONE_FILTER_USED", {
      phone_number: maskPhone(phoneNumber),
    });
  }

  if (Array.isArray(drafts) && drafts.length === 0) {
    return {
      ok: false,
      drafts: [],
      error: "No chat drafts found in the configured AGRO backend.",
      debug: {
        configured_backend_base_url: backendBaseUrl(env),
        dev_fallback_base_url: currentDevBackendFallbackUrl(env),
      },
    };
  }

  return { ok: true, drafts, phone_filter_used: Boolean(phoneNumber) };
}

async function listProducerShipments(env, phoneNumber, limit) {
  if (!phoneNumber) {
    return { ok: false, error: "phoneNumber is required" };
  }
  const params = new URLSearchParams();
  params.set("phone_number", phoneNumber);
  params.set("limit", String(limit || 10));
  console.log("LIST_PRODUCER_SHIPMENTS", {
    phone_number: maskPhone(phoneNumber),
    url: `${backendBaseUrl(env)}/api/v1/producer/shipments?${params.toString()}`,
  });
  const response = await backendRequest(env, `/api/v1/producer/shipments?${params.toString()}`, {
    method: "GET",
    headers: { "Content-Type": "application/json" },
  });
  return { ok: true, shipments: Array.isArray(response.data) ? response.data : [] };
}

async function listProducerInterestedOffers(env, phoneNumber, limit) {
  if (!phoneNumber) {
    return { ok: false, error: "phoneNumber is required" };
  }
  const params = new URLSearchParams();
  params.set("phone_number", phoneNumber);
  params.set("limit", String(limit || 10));
  console.log("LIST_PRODUCER_INTERESTED_OFFERS", {
    phone_number: maskPhone(phoneNumber),
    url: `${backendBaseUrl(env)}/api/v1/producer/shipments/interested-offers?${params.toString()}`,
  });
  const response = await backendRequest(env, `/api/v1/producer/shipments/interested-offers?${params.toString()}`, {
    method: "GET",
    headers: { "Content-Type": "application/json" },
  });
  return { ok: true, offers: Array.isArray(response.data) ? response.data : [] };
}

async function getProducerDashboard(env, phoneNumber, limit) {
  if (!phoneNumber) {
    return {
      ok: false,
      error: "phoneNumber is required",
      backend_unavailable: false,
      dashboard: null,
    };
  }
  const params = new URLSearchParams();
  params.set("phone_number", phoneNumber);
  params.set("limit", String(limit || 12));
  try {
    const response = await backendRequest(env, `/api/v1/producer/dashboard?${params.toString()}`, {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });
    return { ok: true, dashboard: response.data, backend_unavailable: false };
  } catch (error) {
    if (isBackendUnavailableError(error)) {
      const message = error instanceof Error ? error.message : String(error);
      return {
        ok: false,
        error: message,
        backend_unavailable: true,
        dashboard: null,
      };
    }
    throw error;
  }
}

async function acceptProducerOfferByIndex(env, selectionIndex, phoneNumber, limit, idempotencyKey) {
  const index = parseSelectionIndex(selectionIndex);
  if (index === null) {
    return { ok: false, error: "selectionIndex must be a positive number." };
  }
  const listed = await listProducerInterestedOffers(env, phoneNumber, limit);
  const selected = listed.offers[index - 1];
  if (!selected) {
    return {
      ok: false,
      error: `No producer interested offer found for index ${index}.`,
      offers: listed.offers,
    };
  }
  const result = await acceptProducerOffer(
    env,
    selected.shipment_id,
    selected.trip_offer_id,
    phoneNumber,
    idempotencyKey || `kapso_producer_accept_${selected.shipment_id}_${selected.trip_offer_id}`,
  );
  return {
    ok: true,
    selected_offer: selected,
    data: result.data,
  };
}

async function acceptProducerOffer(env, shipmentId, tripOfferId, phoneNumber, idempotencyKey) {
  if (!shipmentId || !tripOfferId || !phoneNumber) {
    return { ok: false, error: "shipmentId, tripOfferId and phoneNumber are required" };
  }
  const response = await backendRequest(
    env,
    `/api/v1/shipments/${encodeURIComponent(shipmentId)}/offers/${encodeURIComponent(tripOfferId)}/accept`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        phone_number: phoneNumber,
        idempotency_key: idempotencyKey || `kapso_producer_accept_${shipmentId}_${tripOfferId}`,
      }),
    },
  );
  return { ok: true, data: response.data };
}

async function getTestSessionStatus(env, phoneNumber) {
  if (!phoneNumber) {
    return { ok: false, error: "phoneNumber is required" };
  }
  const params = new URLSearchParams();
  params.set("phone_number", phoneNumber);
  const response = await backendRequest(env, `/api/v1/admin/test/session-status?${params.toString()}`, {
    method: "GET",
    headers: adminHeaders(env),
  });
  return { ok: true, status: response.data };
}

function recentChatDraftsPath(phoneNumber, limit) {
  const params = new URLSearchParams();
  if (phoneNumber) {
    params.set("phone_number", phoneNumber);
  }
  params.set("limit", String(limit || 3));
  return `/api/v1/admin/shipments/from-chat/recent?${params.toString()}`;
}

async function selectOffer(env, shipmentId, tripOfferId, idempotencyKey) {
  if (!shipmentId || !tripOfferId) {
    return { ok: false, error: "shipmentId and tripOfferId are required" };
  }

  const response = await backendRequest(env, `/api/v1/shipments/${encodeURIComponent(shipmentId)}/select-offer`, {
    method: "POST",
    headers: adminHeaders(env),
    body: JSON.stringify({
      trip_offer_id: tripOfferId,
      idempotency_key: idempotencyKey || `kapso_select_${shipmentId}_${tripOfferId}`,
    }),
  });

  return { ok: true, data: response.data };
}

async function logConversationEvent(event) {
  return {
    ok: false,
    persisted: false,
    todo: "Backend endpoint required for generic conversation events.",
    event: event || {},
  };
}

async function backendRequest(env, path, options) {
  const primaryBaseUrl = backendBaseUrl(env);
  const attempts = [primaryBaseUrl, ...fallbackBackendBaseUrls(env, primaryBaseUrl)];
  let lastError = null;

  for (const baseUrl of attempts) {
    try {
      return await singleBackendRequest(baseUrl, path, options, { retryableAttempts: attempts });
    } catch (error) {
      if (baseUrl !== attempts[attempts.length - 1]) {
        console.log("AGRO_BACKEND_CLIENT_RETRY", {
          failed_url: `${baseUrl}${path}`,
          error_message: error instanceof Error ? error.message : String(error),
        });
        lastError = error;
        continue;
      }
      throw error;
    }
  }

  throw lastError || new Error("AGRO backend request failed.");
}

async function singleBackendRequest(baseUrl, path, options, context = {}) {
  const url = `${baseUrl}${path}`;
  console.log("URL", url);
  const response = await fetch(url, {
    ...options,
    headers: options.headers || {},
  });
  const text = await response.text();
  const data = parseJsonOrNull(text);

  if (!response.ok) {
    const error = new Error(`AGRO backend request failed ${response.status}: ${text.slice(0, 500)}`);
    const attempts = context.retryableAttempts || [baseUrl];
    if (shouldRetryBackendRequest(response.status, text, baseUrl, attempts)) {
      console.log("AGRO_BACKEND_CLIENT_RETRY", {
        failed_url: url,
        status: response.status,
        reason: retryReason(text),
      });
    }
    throw error;
  }

  return { data, status: response.status };
}

function backendBaseUrl(env) {
  const configured = env.AGRO_BACKEND_BASE_URL || env.AGRO_BACKEND_FALLBACK_BASE_URL;
  if (!configured) {
    throw new Error("Missing AGRO_BACKEND_BASE_URL in Kapso function environment.");
  }
  return configured.replace(/\/$/, "");
}

function fallbackBackendBaseUrls(env, primaryBaseUrl) {
  return [env.AGRO_BACKEND_FALLBACK_BASE_URL, currentDevBackendFallbackUrl(env)]
    .filter(Boolean)
    .map((url) => url.replace(/\/$/, ""))
    .filter((url, index, urls) => url !== primaryBaseUrl && urls.indexOf(url) === index);
}

function currentDevBackendFallbackUrl(env) {
  if (env.AGRO_BACKEND_DEV_FALLBACK_DISABLED === "true") {
    return null;
  }
  const configured = env.AGRO_BACKEND_DEV_FALLBACK_URL || env.AGRO_BACKEND_FALLBACK_BASE_URL;
  return configured ? configured.replace(/\/$/, "") : null;
}

function shouldRetryBackendRequest(status, text, baseUrl, attempts) {
  if (baseUrl === attempts[attempts.length - 1]) {
    return false;
  }
  if (status >= 500) {
    return true;
  }
  return text.includes("ERR_NGROK_") || text.includes("ngrok");
}

function retryReason(text) {
  const match = text.match(/ERR_NGROK_[0-9]+/);
  return match ? match[0] : "non_ok_response";
}

function adminHeaders(env) {
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

function idempotencyKeyFromContext(body) {
  const flowId =
    body.idempotency_key ||
    body.whatsapp_context?.message_id ||
    body.whatsapp_context?.message?.id ||
    body.flow_info?.id ||
    body.flow_info?.execution_id ||
    body.execution_context?.id ||
    body.execution_context?.execution_id;
  if (!flowId) {
    return null;
  }
  return `kapso_chat_draft_${flowId}`;
}

function parseJsonOrNull(text) {
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function normalizeInput(value) {
  if (typeof value === "string") {
    try {
      return JSON.parse(value);
    } catch {
      return { text: value };
    }
  }
  if (!value || typeof value !== "object") {
    return {};
  }
  return value;
}

function inferAction(body, input) {
  if (input.action) {
    return input.action;
  }
  const toolName = toolNameFromBody(body);
  if (toolName === "create_shipment_draft_from_text" || toolName === "createShipmentDraftFromText") {
    return "createShipmentDraftFromText";
  }
  if (toolName === "preview_shipment_from_text" || toolName === "previewShipmentFromText") {
    return "previewShipmentFromText";
  }
  if (toolName === "publish_shipment" || toolName === "publishShipment") {
    return "publishShipment";
  }
  if (toolName === "validate_shipment" || toolName === "validateShipment") {
    return "validateShipment";
  }
  if (toolName === "list_shipments_with_offers" || toolName === "listShipmentsWithOffers") {
    return "listShipmentsWithOffers";
  }
  if (toolName === "list_operator_loads" || toolName === "listOperatorLoads") {
    return "listOperatorLoads";
  }
  if (toolName === "select_offer_by_index" || toolName === "selectOfferByIndex") {
    return "selectOfferByIndex";
  }
  if (toolName === "list_draft_shipments" || toolName === "listDraftShipments") {
    return "listDraftShipments";
  }
  if (toolName === "list_pending_assignments" || toolName === "listPendingAssignments") {
    return "listPendingAssignments";
  }
  if (toolName === "list_active_assignments" || toolName === "listActiveAssignments") {
    return "listActiveAssignments";
  }
  if (toolName === "lookup_operation" || toolName === "lookupOperation") {
    return "lookupOperation";
  }
  if (toolName === "confirm_assignment" || toolName === "confirmAssignment") {
    return "confirmAssignment";
  }
  if (toolName === "confirm_assignment_by_index" || toolName === "confirmAssignmentByIndex") {
    return "confirmAssignmentByIndex";
  }
  if (toolName === "cancel_trip" || toolName === "cancelTrip") {
    return "cancelTrip";
  }
  if (toolName === "list_recent_chat_drafts" || toolName === "listRecentChatDrafts") {
    return "listRecentChatDrafts";
  }
  if (toolName === "list_producer_shipments" || toolName === "listProducerShipments") {
    return "listProducerShipments";
  }
  if (toolName === "list_producer_interested_offers" || toolName === "listProducerInterestedOffers") {
    return "listProducerInterestedOffers";
  }
  if (toolName === "get_producer_dashboard" || toolName === "getProducerDashboard") {
    return "getProducerDashboard";
  }
  if (toolName === "accept_producer_offer_by_index" || toolName === "acceptProducerOfferByIndex") {
    return "acceptProducerOfferByIndex";
  }
  if (toolName === "accept_producer_offer" || toolName === "acceptProducerOffer") {
    return "acceptProducerOffer";
  }
  if (toolName === "get_test_session_status" || toolName === "getTestSessionStatus") {
    return "getTestSessionStatus";
  }
  if (toolName === "select_offer" || toolName === "selectOffer") {
    return "selectOffer";
  }
  if (input.tripOfferId || input.trip_offer_id) {
    return "selectOffer";
  }
  return undefined;
}

function toolNameFromBody(body) {
  const flowEventToolName = findToolNameInFlowEvents(body.flow_events);
  return (
    body.tool_name ||
    body.toolName ||
    body.name ||
    body.function_name ||
    body.functionName ||
    body.function?.name ||
    body.tool?.name ||
    body.flow_agent_tool?.name ||
    body.flow_info?.tool_name ||
    body.flow_info?.toolName ||
    body.execution_context?.tool_name ||
    body.execution_context?.toolName ||
    flowEventToolName ||
    null
  );
}

function findToolNameInFlowEvents(flowEvents) {
  if (!flowEvents) {
    return null;
  }
  const events = Array.isArray(flowEvents) ? flowEvents : [flowEvents];
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (!event || typeof event !== "object") {
      continue;
    }
    const payload = event.payload && typeof event.payload === "object" ? event.payload : {};
    const toolName =
      event.tool_name ||
      event.toolName ||
      event.name ||
      payload.tool_name ||
      payload.toolName ||
      payload.name ||
      payload.function_name ||
      payload.functionName;
    if (toolName) {
      return toolName;
    }
  }
  return null;
}

function phoneNumberFromContext(body, context) {
  return (
    context.phone_number ||
    context.phoneNumber ||
    body.whatsapp_context?.phone_number ||
    body.whatsapp_context?.from ||
    body.whatsapp_context?.contact?.phone_number ||
    body.whatsapp_context?.message?.from ||
    null
  );
}

function debugUrl(env, action) {
  if (!env.AGRO_BACKEND_BASE_URL) {
    return null;
  }
  if (action === "createShipmentDraftFromText") {
    return `${env.AGRO_BACKEND_BASE_URL.replace(/\/$/, "")}/api/v1/shipment-requests/from-chat`;
  }
  if (action === "previewShipmentFromText") {
    return `${env.AGRO_BACKEND_BASE_URL.replace(/\/$/, "")}/api/v1/admin/shipments/chat-preview`;
  }
  if (action === "listRecentChatDrafts") {
    return `${env.AGRO_BACKEND_BASE_URL.replace(/\/$/, "")}/api/v1/admin/shipments/from-chat/recent`;
  }
  if (action === "listProducerShipments") {
    return `${env.AGRO_BACKEND_BASE_URL.replace(/\/$/, "")}/api/v1/producer/shipments`;
  }
  if (action === "listProducerInterestedOffers") {
    return `${env.AGRO_BACKEND_BASE_URL.replace(/\/$/, "")}/api/v1/producer/shipments/interested-offers`;
  }
  if (action === "acceptProducerOffer" || action === "acceptProducerOfferByIndex") {
    return `${env.AGRO_BACKEND_BASE_URL.replace(/\/$/, "")}/api/v1/shipments/{shipment_id}/offers/{trip_offer_id}/accept`;
  }
  if (action === "getTestSessionStatus") {
    return `${env.AGRO_BACKEND_BASE_URL.replace(/\/$/, "")}/api/v1/admin/test/session-status`;
  }
  if (action === "listDraftShipments") {
    return `${env.AGRO_BACKEND_BASE_URL.replace(/\/$/, "")}/api/v1/admin/shipments/drafts`;
  }
  if (action === "listPendingAssignments") {
    return `${env.AGRO_BACKEND_BASE_URL.replace(/\/$/, "")}/api/v1/admin/assignments/pending`;
  }
  if (action === "listActiveAssignments") {
    return `${env.AGRO_BACKEND_BASE_URL.replace(/\/$/, "")}/api/v1/admin/assignments/active`;
  }
  if (action === "lookupOperation") {
    return `${env.AGRO_BACKEND_BASE_URL.replace(/\/$/, "")}/api/v1/admin/operations/lookup`;
  }
  if (action === "cancelTrip") {
    return `${env.AGRO_BACKEND_BASE_URL.replace(/\/$/, "")}/api/v1/trips`;
  }
  if (action === "listOperatorLoads") {
    return `${env.AGRO_BACKEND_BASE_URL.replace(/\/$/, "")}/api/v1/admin/shipments/with-offers`;
  }
  return env.AGRO_BACKEND_BASE_URL.replace(/\/$/, "");
}

function redactDebugValue(value) {
  if (Array.isArray(value)) {
    return value.map((item) => redactDebugValue(item));
  }
  if (!value || typeof value !== "object") {
    return value;
  }
  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => {
      if (key.toLowerCase().includes("phone")) {
        return [key, maskPhone(item)];
      }
      if (["text", "message", "raw_content", "body"].includes(key.toLowerCase())) {
        return [key, "<redacted>"];
      }
      return [key, redactDebugValue(item)];
    }),
  );
}

function maskPhone(value) {
  if (!value) {
    return value;
  }
  const digits = String(value).replace(/\D/g, "");
  if (digits.length <= 6) {
    return "***";
  }
  return `${digits.slice(0, 3)}***${digits.slice(-3)}`;
}
