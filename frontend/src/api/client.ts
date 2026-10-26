import type {
  CarrierDetail,
  ConversationMessage,
  ConversationMessagePage,
  CarrierDashboard,
  CarrierDriver,
  CarrierDocument,
  CarrierListItem,
  CarrierOnboardingPending,
  CarrierVehicle,
  CarrierPayload,
  DocumentPayload,
  ProducerDashboard,
  ProducerDetail,
  ProducerListItem,
  OperatorProfile,
  ManualShipmentAssignmentResult,
  ManualShipmentInterestResult,
  OpenConversation,
  OpenConversationListPage,
  ListPage,
  Overview,
  NotificationOutboxPage,
  ShipmentPayload,
  ShipmentDetail,
  TripOperatorActionResult,
  Trip,
  TripPayload,
  UnassignedShipment,
  VehiclePayload,
  WhatsappAllowlistContact,
  WhatsappAllowlistPayload,
  RouteAvailability,
  RouteAvailabilityPayload,
  RouteAvailabilityMatch,
  GeographicCatalogEntry,
  CargoCatalog,
  CargoCategory,
  CargoType
} from "../types";
import { authHeaders } from "../auth/supabase";
import { errorLabel } from "../labels";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const identityHeaders = await authHeaders();
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      "content-type": "application/json",
      ...identityHeaders,
      ...(options.headers ?? {})
    }
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      detail = body.detail ?? detail;
    } catch {
      // Keep the HTTP status text when the body is not JSON.
    }
    throw new Error(errorLabel(`${response.status} ${detail}`));
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export const api = {
  overview: () => request<Overview>("/api/v1/backoffice/overview"),
  currentOperator: () => request<OperatorProfile>("/api/v1/backoffice/me"),
  producers: (search?: string, limit = 50, offset = 0) => {
    const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (search) query.set("search", search);
    return request<ProducerListItem[]>(`/api/v1/backoffice/producers?${query.toString()}`);
  },
  producersPage: (search?: string, limit = 25, offset = 0) => {
    const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (search) query.set("search", search);
    return request<ListPage<ProducerListItem>>(`/api/v1/backoffice/producers/page?${query.toString()}`);
  },
  producerDetail: (producerId: string) =>
    request<ProducerDetail>(`/api/v1/backoffice/producers/${encodeURIComponent(producerId)}`),
  notificationOutbox: (status?: string, limit = 50, offset = 0) => {
    const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (status) query.set("status", status);
    return request<NotificationOutboxPage>(`/api/v1/backoffice/notification-outbox?${query.toString()}`);
  },
  reconcileNotification: (outboxId: string, resolution: "ACCEPTED" | "RETRY_NOT_SENT", evidenceReference: string) =>
    request<{ id: string; status: string }>(
      `/api/v1/backoffice/notification-outbox/${encodeURIComponent(outboxId)}/reconcile`,
      { method: "POST", body: JSON.stringify({ resolution, evidence_reference: evidenceReference }) }
    ),
  openConversations: (options: { limit?: number; offset?: number; needsOperator?: boolean } = {}) => {
    const query = new URLSearchParams({ limit: String(options.limit ?? 25), offset: String(options.offset ?? 0) });
    if (options.needsOperator !== undefined) query.set("needs_operator", String(options.needsOperator));
    return request<OpenConversation[]>(`/api/v1/backoffice/conversations/open?${query.toString()}`);
  },
  openConversationsPage: (options: { limit?: number; offset?: number; needsOperator?: boolean; ambiguousOnly?: boolean } = {}) => {
    const query = new URLSearchParams({ limit: String(options.limit ?? 25), offset: String(options.offset ?? 0) });
    if (options.needsOperator !== undefined) query.set("needs_operator", String(options.needsOperator));
    if (options.ambiguousOnly !== undefined) query.set("ambiguous_only", String(options.ambiguousOnly));
    return request<OpenConversationListPage>(`/api/v1/backoffice/conversations/open/page?${query.toString()}`);
  },
  conversationMessages: (conversationId: string) =>
    request<ConversationMessage[]>(
      `/api/v1/backoffice/conversations/${encodeURIComponent(conversationId)}/messages`
    ),
  conversationMessagePage: (conversationId: string, options: { cursor?: string; direction?: "older" | "newer" } = {}) => {
    const query = new URLSearchParams({ limit: "50", direction: options.direction ?? "older" });
    if (options.cursor) query.set("cursor", options.cursor);
    return request<ConversationMessagePage>(
      `/api/v1/backoffice/conversations/${encodeURIComponent(conversationId)}/messages/page?${query.toString()}`
    );
  },
  unassignedShipments: () =>
    request<UnassignedShipment[]>("/api/v1/backoffice/shipments/unassigned"),
  unassignedShipmentsPage: (limit = 25, offset = 0) =>
    request<ListPage<UnassignedShipment>>(`/api/v1/backoffice/shipments/unassigned/page?limit=${limit}&offset=${offset}`),
  shipmentDetail: (shipmentId: string) =>
    request<ShipmentDetail>(`/api/v1/backoffice/shipments/${shipmentId}`),
  updateShipment: (shipmentId: string, payload: ShipmentPayload) =>
    request<ShipmentDetail>(`/api/v1/backoffice/shipments/${shipmentId}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
  deleteShipment: (shipmentId: string) =>
    request<void>(`/api/v1/backoffice/shipments/${shipmentId}`, {
      method: "DELETE"
    }),
  registerManualInterest: (shipmentId: string, carrierId: string, notes?: string) =>
    request<ManualShipmentInterestResult>(`/api/v1/backoffice/shipments/${shipmentId}/manual-interest`, {
      method: "POST",
      body: JSON.stringify({ carrier_id: carrierId, notes: notes ?? null })
    }),
  assignShipmentManually: (shipmentId: string, carrierId: string, notes?: string) =>
    request<ManualShipmentAssignmentResult>(`/api/v1/backoffice/shipments/${shipmentId}/manual-assign`, {
      method: "POST",
      body: JSON.stringify({ carrier_id: carrierId, notes: notes ?? null })
    }),
  startTrip: (tripId: string, notes?: string) =>
    request<TripOperatorActionResult>(`/api/v1/backoffice/trips/${tripId}/start`, {
      method: "POST",
      body: JSON.stringify({ notes: notes ?? null })
    }),
  assignTripCrew: (tripId: string, driverId: string, vehicleId: string) =>
    request<{ trip_id: string; carrier_id: string; driver_id: string; vehicle_id: string; trip_status: string }>(
      `/api/v1/backoffice/trips/${tripId}/crew`,
      { method: "POST", body: JSON.stringify({ driver_id: driverId, vehicle_id: vehicleId }) }
    ),
  markTripInTransit: (tripId: string, notes?: string) =>
    request<TripOperatorActionResult>(`/api/v1/backoffice/trips/${tripId}/mark-in-transit`, {
      method: "POST",
      body: JSON.stringify({ notes: notes ?? null })
    }),
  completeTrip: (tripId: string, notes?: string) =>
    request<TripOperatorActionResult>(`/api/v1/backoffice/trips/${tripId}/complete`, {
      method: "POST",
      body: JSON.stringify({ notes: notes ?? null })
    }),
  cancelTripFromBackoffice: (tripId: string, reason: string) =>
    request<TripOperatorActionResult>(`/api/v1/backoffice/trips/${tripId}/cancel`, {
      method: "POST",
      body: JSON.stringify({ reason })
    }),
  trips: (status?: string) => {
    const query = status ? `?status=${encodeURIComponent(status)}` : "";
    return request<Trip[]>(`/api/v1/backoffice/trips${query}`);
  },
  tripsPage: (status?: string, limit = 25, offset = 0) => {
    const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (status) query.set("status", status);
    return request<ListPage<Trip>>(`/api/v1/backoffice/trips/page?${query.toString()}`);
  },
  updateTrip: (tripId: string, payload: TripPayload) =>
    request<Trip>(`/api/v1/backoffice/trips/${tripId}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
  deleteTrip: (tripId: string) =>
    request<void>(`/api/v1/backoffice/trips/${tripId}`, {
      method: "DELETE"
    }),
  downloadCarrierDocument: async (carrierId: string, documentId: string, fileName: string) => {
    const response = await fetch(
      `${API_BASE_URL}/api/v1/backoffice/carriers/${encodeURIComponent(carrierId)}/documents/${encodeURIComponent(documentId)}/content`,
      {
        headers: {
          ...(await authHeaders())
        }
      }
    );
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const body = (await response.json()) as { detail?: string };
        detail = body.detail ?? detail;
      } catch {
        // Retain status text for non-JSON errors.
      }
      throw new Error(`${response.status} ${detail}`);
    }
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const link = window.document.createElement("a");
    link.href = objectUrl;
    link.download = fileName.split(/[\\/]/).pop() || documentId;
    link.click();
    URL.revokeObjectURL(objectUrl);
  },
  carriers: (params?: {
    validation_status?: string;
    pending_only?: boolean;
    onboarding_pending_only?: boolean;
    is_validated?: boolean;
    search?: string;
    limit?: number;
    offset?: number;
  }) => {
    const query = new URLSearchParams();
    if (params?.validation_status) query.set("validation_status", params.validation_status);
    if (params?.pending_only !== undefined) query.set("pending_only", String(params.pending_only));
    if (params?.onboarding_pending_only !== undefined) query.set("onboarding_pending_only", String(params.onboarding_pending_only));
    if (params?.is_validated !== undefined) query.set("is_validated", String(params.is_validated));
    if (params?.search) query.set("search", params.search);
    if (params?.limit !== undefined) query.set("limit", String(params.limit));
    if (params?.offset !== undefined) query.set("offset", String(params.offset));
    const suffix = query.size ? `?${query.toString()}` : "";
    return request<CarrierListItem[]>(`/api/v1/backoffice/carriers${suffix}`);
  },
  carriersPage: (params?: {
    validation_status?: string; pending_only?: boolean; onboarding_pending_only?: boolean;
    is_validated?: boolean; search?: string; limit?: number; offset?: number;
  }) => {
    const query = new URLSearchParams({ limit: String(params?.limit ?? 25), offset: String(params?.offset ?? 0) });
    if (params?.validation_status) query.set("validation_status", params.validation_status);
    if (params?.pending_only !== undefined) query.set("pending_only", String(params.pending_only));
    if (params?.onboarding_pending_only !== undefined) query.set("onboarding_pending_only", String(params.onboarding_pending_only));
    if (params?.is_validated !== undefined) query.set("is_validated", String(params.is_validated));
    if (params?.search) query.set("search", params.search);
    return request<ListPage<CarrierListItem>>(`/api/v1/backoffice/carriers/page?${query.toString()}`);
  },
  routeAvailabilities: () => request<RouteAvailability[]>("/api/v1/backoffice/route-availabilities"),
  routeAvailabilitiesPage: (limit = 25, offset = 0) =>
    request<ListPage<RouteAvailability>>(`/api/v1/backoffice/route-availabilities/page?limit=${limit}&offset=${offset}`),
  createRouteAvailability: (payload: RouteAvailabilityPayload) =>
    request<RouteAvailability>("/api/v1/backoffice/route-availabilities", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  updateRouteAvailabilityStatus: (availabilityId: string, nextStatus: "ACTIVE" | "CLOSED" | "CANCELLED") =>
    request<RouteAvailability>(`/api/v1/backoffice/route-availabilities/${availabilityId}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status: nextStatus })
    }),
  matchRouteAvailabilities: (payload: {
    origin: string; destination: string; shipment_at?: string | null; cargo_type?: string | null;
    quantity?: string | null; quantity_unit?: string | null; equipment_type?: string | null;
  }) => request<RouteAvailabilityMatch[]>("/api/v1/backoffice/route-availabilities/match", {
    method: "POST", body: JSON.stringify(payload)
  }),
  pendingOnboarding: () =>
    request<CarrierOnboardingPending[]>("/api/v1/backoffice/carrier-onboarding/pending"),
  producerDashboard: (phoneNumber: string) =>
    request<ProducerDashboard>(`/api/v1/producer/dashboard?phone_number=${encodeURIComponent(phoneNumber)}`),
  carrierDashboard: (carrierId: string) =>
    request<CarrierDashboard>(`/api/v1/carrier/dashboard/${carrierId}`),
  createCarrier: (payload: CarrierPayload) =>
    request<CarrierDetail>("/api/v1/backoffice/carriers", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  updateCarrier: (carrierId: string, payload: CarrierPayload) =>
    request<CarrierDetail>(`/api/v1/backoffice/carriers/${carrierId}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
  carrierDetail: (carrierId: string) =>
    request<CarrierDetail>(`/api/v1/backoffice/carriers/${carrierId}/onboarding`),
  approveCarrier: (carrierId: string, notes?: string) =>
    request<CarrierDetail>(`/api/v1/backoffice/carriers/${carrierId}/approve`, {
      method: "POST",
      body: JSON.stringify({ notes: notes ?? null })
    }),
  rejectCarrier: (carrierId: string, reason: string) =>
    request<CarrierDetail>(`/api/v1/backoffice/carriers/${carrierId}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason })
    }),
  suspendCarrier: (carrierId: string, reason: string) =>
    request<CarrierDetail>(`/api/v1/backoffice/carriers/${carrierId}/suspend`, {
      method: "POST",
      body: JSON.stringify({ reason })
    }),
  markCarrierInReview: (carrierId: string, notes?: string) =>
    request<CarrierDetail>(`/api/v1/backoffice/carriers/${carrierId}/mark-in-review`, {
      method: "POST",
      body: JSON.stringify({ notes: notes ?? null })
    }),
  createVehicle: (carrierId: string, payload: VehiclePayload) =>
    request(`/api/v1/backoffice/carriers/${carrierId}/vehicles`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  updateVehicle: (carrierId: string, vehicleId: string, payload: VehiclePayload) =>
    request(`/api/v1/backoffice/carriers/${carrierId}/vehicles/${vehicleId}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
  deleteVehicle: (carrierId: string, vehicleId: string) =>
    request(`/api/v1/backoffice/carriers/${carrierId}/vehicles/${vehicleId}`, {
      method: "DELETE"
    }),
  approveCarrierVehicle: (carrierId: string, vehicleId: string, notes?: string) =>
    request<CarrierVehicle>(`/api/v1/backoffice/carriers/${carrierId}/vehicles/${vehicleId}/approve`, {
      method: "POST",
      body: JSON.stringify({ notes: notes ?? null })
    }),
  createCarrierDriver: (carrierId: string, payload: { name: string; phone?: string | null; license_category?: string | null }) =>
    request<CarrierDriver>(`/api/v1/backoffice/carriers/${carrierId}/drivers`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  approveCarrierDriver: (carrierId: string, driverId: string, notes?: string) =>
    request<CarrierDriver>(`/api/v1/backoffice/carriers/${carrierId}/drivers/${driverId}/approve`, {
      method: "POST",
      body: JSON.stringify({ notes: notes ?? null })
    }),
  rejectCarrierDriver: (carrierId: string, driverId: string, reason: string) =>
    request<CarrierDriver>(`/api/v1/backoffice/carriers/${carrierId}/drivers/${driverId}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason })
    }),
  createCarrierDocument: (carrierId: string, payload: DocumentPayload) =>
    request<CarrierDocument>(`/api/v1/backoffice/carriers/${carrierId}/documents`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  updateCarrierDocument: (carrierId: string, documentId: string, payload: DocumentPayload) =>
    request<CarrierDocument>(`/api/v1/backoffice/carriers/${carrierId}/documents/${documentId}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
  whatsappAllowlist: (params?: {
    status?: string;
    environment?: string;
    provider?: string;
    search?: string;
    limit?: number;
    offset?: number;
  }) => {
    const query = new URLSearchParams();
    if (params?.status) query.set("status", params.status);
    if (params?.environment) query.set("environment", params.environment);
    if (params?.provider) query.set("provider", params.provider);
    if (params?.search) query.set("search", params.search);
    if (params?.limit !== undefined) query.set("limit", String(params.limit));
    if (params?.offset !== undefined) query.set("offset", String(params.offset));
    const suffix = query.size ? `?${query.toString()}` : "";
    return request<WhatsappAllowlistContact[]>(`/api/v1/backoffice/whatsapp-allowlist${suffix}`);
  },
  createWhatsappAllowlistContact: (payload: WhatsappAllowlistPayload) =>
    request<WhatsappAllowlistContact>("/api/v1/backoffice/whatsapp-allowlist", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  updateWhatsappAllowlistContact: (contactId: string, payload: WhatsappAllowlistPayload) =>
    request<WhatsappAllowlistContact>(`/api/v1/backoffice/whatsapp-allowlist/${contactId}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
  blockWhatsappAllowlistContact: (contactId: string, reason: string) =>
    request<WhatsappAllowlistContact>(`/api/v1/backoffice/whatsapp-allowlist/${contactId}/block`, {
      method: "POST",
      body: JSON.stringify({ reason })
    }),
  reactivateWhatsappAllowlistContact: (contactId: string) =>
    request<WhatsappAllowlistContact>(`/api/v1/backoffice/whatsapp-allowlist/${contactId}/reactivate`, {
      method: "POST"
    }),
  disableWhatsappAllowlistContact: (contactId: string) =>
    request<WhatsappAllowlistContact>(`/api/v1/backoffice/whatsapp-allowlist/${contactId}/disable`, {
      method: "POST"
    }),
  approveDocument: (carrierId: string, documentId: string, notes?: string) =>
    request<CarrierDocument>(
      `/api/v1/backoffice/carriers/${carrierId}/documents/${documentId}/approve`,
      {
        method: "POST",
        body: JSON.stringify({ notes: notes ?? null })
      }
    ),
  rejectDocument: (carrierId: string, documentId: string, reason: string) =>
    request<CarrierDocument>(
      `/api/v1/backoffice/carriers/${carrierId}/documents/${documentId}/reject`,
      {
        method: "POST",
        body: JSON.stringify({ reason })
      }
    ),
  geographicCatalog: (params: {
    kind?: GeographicCatalogEntry["kind"];
    parent_id?: string;
    search?: string;
    active?: boolean | null;
    limit?: number;
    offset?: number;
  } = {}) => {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
    }
    return request<ListPage<GeographicCatalogEntry>>(`/api/v1/backoffice/catalogs/geography?${query.toString()}`);
  },
  createGeographicEntry: (payload: Pick<GeographicCatalogEntry, "kind" | "name" | "parent_id" | "aliases">) =>
    request<GeographicCatalogEntry>("/api/v1/backoffice/catalogs/geography", {
      method: "POST", body: JSON.stringify(payload)
    }),
  updateGeographicEntry: (id: string, payload: Partial<Pick<GeographicCatalogEntry, "name" | "parent_id" | "aliases" | "active">>) =>
    request<GeographicCatalogEntry>(`/api/v1/backoffice/catalogs/geography/${encodeURIComponent(id)}`, {
      method: "PATCH", body: JSON.stringify(payload)
    }),
  cargoCatalog: (includeInactive = true) =>
    request<CargoCatalog>(`/api/v1/backoffice/catalogs/cargo?include_inactive=${includeInactive}`),
  createCargoCategory: (payload: Pick<CargoCategory, "code" | "name" | "aliases" | "active" | "sort_order">) =>
    request<CargoCategory>("/api/v1/backoffice/catalogs/cargo/categories", {
      method: "POST", body: JSON.stringify(payload)
    }),
  updateCargoCategory: (code: string, payload: Partial<Pick<CargoCategory, "name" | "aliases" | "active" | "sort_order">>) =>
    request<CargoCategory>(`/api/v1/backoffice/catalogs/cargo/categories/${encodeURIComponent(code)}`, {
      method: "PATCH", body: JSON.stringify(payload)
    }),
  createCargoType: (payload: Pick<CargoType, "code" | "category_code" | "name" | "aliases" | "active" | "sort_order">) =>
    request<CargoType>("/api/v1/backoffice/catalogs/cargo/types", {
      method: "POST", body: JSON.stringify(payload)
    }),
  updateCargoType: (code: string, payload: Partial<Pick<CargoType, "category_code" | "name" | "aliases" | "active" | "sort_order">>) =>
    request<CargoType>(`/api/v1/backoffice/catalogs/cargo/types/${encodeURIComponent(code)}`, {
      method: "PATCH", body: JSON.stringify(payload)
    })
};

export const routingApi = {
  config: () => request<{google_maps_browser_key: string | null; route_provider_configured: boolean}>("/api/v1/backoffice/routing/config"),
  tracking: (id: string, scope = "") => request<import("../types").TrackingView>(`/api/v1/backoffice/trips/${encodeURIComponent(id)}/tracking${scope ? `?test_run_id=${encodeURIComponent(scope)}` : ""}`),
  action: (id: string, action: string, scope = "") => request(`/api/v1/backoffice/trips/${encodeURIComponent(id)}/tracking/${action}${scope ? `?test_run_id=${encodeURIComponent(scope)}` : ""}`, { method: "POST" }),
  preferences: (id: string, scope = "") => request<{items: import("../types").RoutingRow<import("../types").RoutePreferenceData>[]; total: number}>(`/api/v1/backoffice/carriers/${encodeURIComponent(id)}/route-preferences${scope ? `?test_run_id=${encodeURIComponent(scope)}` : ""}`),
  savePreference: (id: string, data: import("../types").RoutePreferenceInput, scope = "", preferenceId?: string) => request(`/api/v1/backoffice/carriers/${encodeURIComponent(id)}/route-preferences${preferenceId ? `/${encodeURIComponent(preferenceId)}` : ""}${scope ? `?test_run_id=${encodeURIComponent(scope)}` : ""}`, {method: preferenceId ? "PUT" : "POST", body: JSON.stringify(data)}),
  setPoint: (shipment: string, side: string, latitude: number, longitude: number, scope = "") => request(`/api/v1/backoffice/shipments/${encodeURIComponent(shipment)}/locations/${side}${scope ? `?test_run_id=${encodeURIComponent(scope)}` : ""}`, {method:"PUT", body:JSON.stringify({latitude, longitude})}),
  setRequirements: (id: string, equipmentType: string, scope = "") => request(`/api/v1/backoffice/shipments/${encodeURIComponent(id)}/route-requirements${scope ? `?test_run_id=${encodeURIComponent(scope)}` : ""}`, {method:"PUT",body:JSON.stringify({equipment_type:equipmentType || null})}),
  dispatch: (id: string, scope = "") => request<{equipment_type: string | null; decisions: import("../types").RoutingRow<{carrier_id?:string; stage?:string; reason:string}>[]; jobs: import("../types").RoutingRow<{action:string}>[]}>(`/api/v1/backoffice/shipments/${encodeURIComponent(id)}/dispatch${scope ? `?test_run_id=${encodeURIComponent(scope)}` : ""}`)
};
