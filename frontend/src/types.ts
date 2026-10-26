export type Overview = {
  open_conversations: number;
  open_conversations_requiring_operator: number;
  ambiguous_conversations: number;
  failed_notifications: number;
  total_shipments: number;
  published_shipments: number;
  shipments_in_matching: number;
  assigned_shipments: number;
  unassigned_published_shipments: number;
  avg_unassigned_age_hours: number;
  total_trips: number;
  planned_trips: number;
  in_progress_trips: number;
  completed_trips: number;
  cancelled_trips: number;
  failed_trips: number;
  total_carriers: number;
  validated_carriers: number;
  pending_validation_carriers: number;
  carrier_onboarding_pending_review: number;
  carrier_documents_pending_review: number;
  total_documents: number;
  pending_documents: number;
  approved_documents: number;
  rejected_documents: number;
};

export type ListPage<T> = { items: T[]; total: number; limit: number; offset: number };

export type OpenConversation = {
  id: string;
  participant_phone: string | null;
  channel: string;
  last_message_preview: string | null;
  last_activity_at: string | null;
  status: string;
  needs_operator: boolean;
  related_entity_type: string | null;
  related_entity_id: string | null;
};

export type OpenConversationListPage = {
  items: OpenConversation[];
  total: number;
  limit: number;
  offset: number;
};

export type ConversationMessage = {
  id: string;
  conversation_session_id: string;
  direction: string;
  sender_type: string;
  message_type: string;
  content: string | null;
  occurred_at: string;
  test_run_id: string | null;
  qa_role: string | null;
  delivery_status: string | null;
};

export type ConversationMessagePage = {
  items: ConversationMessage[];
  next_cursor: string | null;
  latest_cursor: string | null;
  has_more: boolean;
};

export type NotificationOutboxItem = {
  id: string;
  status: string;
  provider: string;
  notification_type: string | null;
  entity_type: string | null;
  entity_id: string | null;
  test_run_id: string | null;
  attempts: number;
  created_at: string;
  updated_at: string;
  available_at: string;
  last_error_code: string | null;
};

export type NotificationOutboxPage = {
  counts: Record<string, number>;
  items: NotificationOutboxItem[];
  total: number;
  limit: number;
  offset: number;
};

export type ProducerListItem = {
  id: string;
  name: string;
  phone: string | null;
  is_validated: boolean;
  usual_location_id: string | null;
  last_activity_at: string | null;
  shipments_count: number;
  active_shipments_count: number;
  trips_count: number;
  conversations_count: number;
};

export type OperatorProfile = { user_id: string; role: string };

export type ProducerDetail = {
  producer: ProducerListItem;
  email: string | null;
  trust_notes: string | null;
  validated_at: string | null;
  shipments: Array<{
    id: string;
    status: string;
    origin: string | null;
    destination: string | null;
    cargo_category: string | null;
    cargo_type: string | null;
    quantity_estimate: number | string | null;
    weight_per_head_kg?: number | string | null;
    quantity_unit: string | null;
    date_window_start: string | null;
    date_window_end: string | null;
    created_at: string;
  }>;
  offers: Array<{
    id: string;
    shipment_request_id: string;
    carrier_id: string;
    status: string;
    response_type: string;
    created_at: string;
  }>;
  trips: Array<{
    id: string;
    shipment_request_id: string;
    carrier_id: string;
    status: string;
    planned_start_at: string | null;
    created_at: string;
  }>;
  conversation_ids: string[];
  events: Array<{
    id: string;
    event_type: string;
    occurred_at: string;
    actor_type: string;
    summary: string;
    entity_type: string;
    entity_id: string;
  }>;
};

export type UnassignedShipment = {
  id: string;
  origin: string | null;
  destination: string | null;
  cargo_category: string | null;
  cargo_type: string | null;
  quantity_unit: string | null;
  livestock_type: string | null;
  quantity_estimate: string | number | null;
  weight_per_head_kg?: string | number | null;
  status: string;
  created_at: string;
  age_hours: number;
  offers_count: number;
  interested_carriers_count: number;
};

export type ShipmentPayload = {
  status?: string;
  producer_phone_number?: string | null;
  origin?: string | null;
  destination?: string | null;
  cargo_category?: string | null;
  cargo_type?: string | null;
  quantity_unit?: string | null;
  livestock_type?: string | null;
  quantity_estimate?: string | number | null;
  weight_per_head_kg?: string | number | null;
  operational_notes?: string | null;
  date_window_start?: string | null;
  date_window_end?: string | null;
  requires_human_review?: boolean;
  has_ambiguous_location?: boolean;
  has_estimated_values?: boolean;
};

export type ShipmentDetail = {
  shipment: {
    id: string;
    test_run_id: string | null;
    status: string;
    producer_phone_number: string | null;
    origin: string | null;
    destination: string | null;
    cargo_category: string | null;
    cargo_type: string | null;
    quantity_unit: string | null;
    livestock_type: string | null;
    quantity_estimate: string | number | null;
    weight_per_head_kg?: string | number | null;
    operational_notes: string | null;
    date_window_start: string | null;
    date_window_end: string | null;
    source_message_id: string | null;
    source_message_preview: string | null;
    requires_human_review: boolean;
    has_ambiguous_location: boolean;
    has_estimated_values: boolean;
    missing_critical_fields: string[];
    field_confidence: Record<string, string>;
    created_at: string;
    updated_at: string;
  };
  offers: Array<{
    id: string;
    carrier_id: string;
    carrier_name: string | null;
    carrier_phone: string | null;
    vehicle_id: string | null;
    vehicle_plate: string | null;
    response_type: string;
    status: string;
    price_estimate: string | number | null;
    availability_window_start: string | null;
    availability_window_end: string | null;
    confidence: string;
    requires_human_review: boolean;
    source_message_id: string | null;
    source_message_preview: string | null;
    created_at: string;
    updated_at: string;
  }>;
  active_assignment: {
    id: string;
    shipment_request_id: string;
    carrier_id: string;
    carrier_name: string | null;
    carrier_phone: string | null;
    vehicle_id: string | null;
    vehicle_plate: string | null;
    trip_offer_id: string | null;
    status: string;
    selected_by_user_id: string;
    confirmed_by_user_id: string | null;
    confirmed_at: string | null;
    confirmation_notes: string | null;
    requires_human_review: boolean;
    created_at: string;
    updated_at: string;
  } | null;
  assignments: Array<{
    id: string;
    shipment_request_id: string;
    carrier_id: string;
    carrier_name: string | null;
    carrier_phone: string | null;
    vehicle_id: string | null;
    vehicle_plate: string | null;
    trip_offer_id: string | null;
    status: string;
    selected_by_user_id: string;
    confirmed_by_user_id: string | null;
    confirmed_at: string | null;
    confirmation_notes: string | null;
    requires_human_review: boolean;
    created_at: string;
    updated_at: string;
  }>;
  active_trip: {
    id: string;
    shipment_request_id: string;
    assignment_id: string;
    carrier_id: string;
    carrier_name: string | null;
    carrier_phone: string | null;
    driver_id: string | null;
    vehicle_id: string | null;
    vehicle_plate: string | null;
    status: string;
    planned_start_at: string | null;
    planned_end_at: string | null;
    started_at: string | null;
    completed_at: string | null;
    cancelled_at: string | null;
    incident_notes: string | null;
    closure_notes: string | null;
    requires_human_review: boolean;
    created_at: string;
    updated_at: string;
  } | null;
  trips: Array<{
    id: string;
    shipment_request_id: string;
    assignment_id: string;
    carrier_id: string;
    carrier_name: string | null;
    carrier_phone: string | null;
    driver_id: string | null;
    vehicle_id: string | null;
    vehicle_plate: string | null;
    status: string;
    planned_start_at: string | null;
    planned_end_at: string | null;
    started_at: string | null;
    completed_at: string | null;
    cancelled_at: string | null;
    incident_notes: string | null;
    closure_notes: string | null;
    requires_human_review: boolean;
    created_at: string;
    updated_at: string;
  }>;
  events: Array<{
    event_id: string;
    event_type: string;
    occurred_at: string;
    actor_type: string;
    actor_id: string | null;
    entity_type: string;
    entity_id: string;
    summary: string;
    previous_state: string | null;
    new_state: string | null;
    related_entity_ids: Record<string, string>;
    source: string;
  }>;
};

export type ManualShipmentInterestResult = {
  shipment_id: string;
  shipment_status: string;
  trip_offer_id: string;
  trip_offer_status: string;
  carrier_id: string;
  carrier_notification_status: string | null;
  producer_notification_status: string | null;
  event_types: string[];
};

export type ManualShipmentAssignmentResult = {
  shipment_id: string;
  shipment_status: string;
  trip_offer_id: string;
  assignment_id: string;
  assignment_status: string;
  trip_id: string;
  trip_status: string;
  carrier_id: string;
  carrier_notification_status: string | null;
  producer_notification_status: string | null;
  event_types: string[];
};

export type TripOperatorActionResult = {
  shipment_id: string;
  shipment_status: string;
  trip_id: string;
  trip_status: string;
  carrier_notification_status: string | null;
  producer_notification_status: string | null;
  event_types: string[];
};

export type Trip = {
  id: string;
  test_run_id?: string | null;
  status: string;
  shipment_request_id: string;
  carrier_id: string;
  driver_id: string | null;
  vehicle_id: string | null;
  carrier_name: string | null;
  origin: string | null;
  destination: string | null;
  planned_start_at: string | null;
  updated_at: string;
};

export type TripPayload = {
  status?: string;
  planned_start_at?: string | null;
  planned_end_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  cancelled_at?: string | null;
  incident_notes?: string | null;
  closure_notes?: string | null;
  requires_human_review?: boolean;
};

export type JourneyStatus = {
  shipment_id: string;
  shipment_status: string;
  trip_id: string | null;
  trip_status: string | null;
  assignment_id: string | null;
  assignment_status: string | null;
  origin: string | null;
  destination: string | null;
  cargo_category: string | null;
  cargo_type: string | null;
  quantity_unit: string | null;
  livestock_type: string | null;
  quantity_estimate: string | number | null;
  operational_notes: string | null;
  interested_offers_count: number;
  counterparty_id: string | null;
  counterparty_name: string | null;
  counterparty_phone: string | null;
  planned_start_at: string | null;
  completed_at: string | null;
  created_at: string;
};

export type ProducerDashboard = {
  phone_number: string;
  total_shipments: number;
  active_shipments: number;
  active_trips: number;
  completed_trips: number;
  pending_interested_offers: number;
  current_operations: JourneyStatus[];
  past_operations: JourneyStatus[];
};

export type CarrierDashboard = {
  carrier_id: string;
  carrier_name: string;
  carrier_phone: string | null;
  total_offers: number;
  open_offers: number;
  active_trips: number;
  completed_trips: number;
  cancelled_trips: number;
  current_operations: JourneyStatus[];
  past_operations: JourneyStatus[];
};

export type CarrierOnboardingPending = {
  carrier_id: string;
  onboarding_id: string | null;
  name: string;
  contact_phone: string | null;
  phone: string | null;
  email: string | null;
  company_name: string | null;
  cuit: string | null;
  validation_status: string;
  onboarding_status: string | null;
  missing_fields: string[];
  documents_count: number;
  pending_documents_count: number;
  created_at: string;
  submitted_at: string | null;
};

export type CarrierListItem = {
  id: string;
  name: string;
  contact_phone: string | null;
  phone: string | null;
  email: string | null;
  company_name: string | null;
  cuit: string | null;
  truck_count: number | null;
  truck_types: string[];
  truck_body_type: string | null;
  is_validated: boolean;
  validation_status: string;
  onboarding_status: string | null;
  missing_fields: string[];
  vehicles_count: number;
  documents_count: number;
  pending_documents_count: number;
  created_at: string;
  updated_at: string;
};

export type CarrierDocument = {
  id: string;
  entity_type: "carrier" | "driver" | "vehicle";
  entity_id: string;
  document_type: string;
  has_file: boolean;
  provider?: string | null;
  provider_media_id?: string | null;
  mime_type?: string | null;
  file_name?: string | null;
  uploaded_by_phone?: string | null;
  status: string;
  notes: string | null;
  reviewed_by_user_id?: string | null;
  reviewed_at?: string | null;
  rejection_reason?: string | null;
  valid_from?: string | null;
  expires_at?: string | null;
  supersedes_document_id?: string | null;
  created_at: string;
  updated_at?: string | null;
  uploaded_at?: string;
};

export type CarrierVehicle = {
  id: string;
  vehicle_type: string | null;
  capacity_estimate: unknown;
  plate_number: string | null;
  body_type: string | null;
  status: string;
  validation_status: string;
  updated_at: string;
  documents: CarrierDocument[];
};

export type CarrierDriver = {
  id: string;
  name: string;
  phone: string | null;
  license_category: string | null;
  status: string;
  validation_status: string;
  reviewed_by_user_id: string | null;
  reviewed_at: string | null;
  rejection_reason: string | null;
  updated_at: string;
  documents: CarrierDocument[];
};

export type CarrierDetail = {
  carrier: {
    id: string;
    name: string;
    contact_phone: string | null;
    normalized_phone_number: string | null;
    email: string | null;
    company_name: string | null;
    cuit: string | null;
    truck_count: number | null;
    truck_types: string[];
    truck_body_type: string | null;
    is_validated: boolean;
    validation_status: string;
    validated_at: string | null;
    rejected_at: string | null;
    rejection_reason: string | null;
    reviewed_by_user_id: string | null;
    created_at: string;
    updated_at: string;
  };
  onboarding: {
    id: string;
    carrier_id: string;
    status: string;
    required_fields: string[];
    missing_fields: string[];
    submitted_at: string | null;
    reviewed_by_user_id: string | null;
    reviewed_at: string | null;
    rejection_reason: string | null;
  };
  capture_progress: {
    step: string | null;
    captured_vehicle_count: number;
    declared_vehicle_count: number;
  };
  vehicles: CarrierVehicle[];
  drivers: CarrierDriver[];
  documents: CarrierDocument[];
  events: Array<{
    event_id: string;
    event_type: string;
    occurred_at: string;
    actor_type: string;
    actor_id: string | null;
    entity_type: string;
    entity_id: string;
    summary: string;
  }>;
};

export type CarrierPayload = {
  name: string;
  phone: string | null;
  email: string | null;
  company_name: string | null;
  cuit: string | null;
  truck_count: number | null;
  truck_types: string[];
  truck_body_type: string | null;
};

export type VehiclePayload = {
  plate_number: string | null;
  vehicle_type: string | null;
  body_type: string | null;
  capacity: string | null;
  status: string | null;
};

export type DocumentPayload = {
  document_type: string;
  entity_type: "carrier" | "driver" | "vehicle";
  entity_id: string | null;
  external_uri: string | null;
  file_name: string | null;
  mime_type: string | null;
  notes: string | null;
  storage_uri?: string | null;
  valid_from?: string | null;
  expires_at?: string | null;
  supersedes_document_id?: string | null;
};

export type WhatsappAllowlistContact = {
  id: string;
  phone_number: string;
  normalized_phone_number: string;
  label: string | null;
  environment: string;
  provider: string;
  status: string;
  notes: string | null;
  created_by_user_id: string | null;
  updated_by_user_id: string | null;
  created_at: string;
  updated_at: string;
};

export type WhatsappAllowlistPayload = {
  phone_number: string;
  label: string | null;
  environment: string;
  provider: string;
  status: string;
  notes: string | null;
};

export type RouteAvailability = {
  id: string;
  carrier_id: string;
  test_run_id: string | null;
  origin: string;
  destination: string;
  stops: string[];
  window_start: string | null;
  window_end: string | null;
  capacity: string | null;
  capacity_unit: string | null;
  cargo_types: string[];
  equipment_types: string[];
  status: string;
  committed_shipment_id: string | null;
};

export type RouteAvailabilityPayload = Omit<RouteAvailability, "id" | "status" | "committed_shipment_id">;

export type RouteAvailabilityMatch = {
  availability: RouteAvailability;
  segment_origin: string;
  segment_destination: string;
  reasons: string[];
};

export type GeographicCatalogEntry = {
  id: string;
  kind: "PROVINCE" | "DEPARTMENT" | "LOCALITY";
  name: string;
  normalized_name: string;
  parent_id: string | null;
  parent_name: string | null;
  georef_id: string | null;
  aliases: string[];
  source: string;
  active: boolean;
};

export type CargoCategory = {
  code: string;
  name: string;
  aliases: string[];
  active: boolean;
  sort_order: number;
};

export type CargoType = {
  code: string;
  category_code: string;
  category_name: string;
  name: string;
  aliases: string[];
  active: boolean;
  sort_order: number;
};

export type CargoCatalog = { categories: CargoCategory[]; types: CargoType[] };

export type RoutePoint = { id?: string; label: string; latitude: number | null; longitude: number | null; precision?: string };
export type RoutingRow<T> = { id: string; entity_id: string; test_run_id: string | null; status: string; due_at?: string | null; data: T };
export type RoutePreferenceData = { points: RoutePoint[]; cargo_categories: string[]; cargo_types: string[]; equipment_types: string[]; opt_in: boolean };
export type RoutePreferenceInput = { origin: string; destination: string; stops: string[]; cargo_categories: string[]; equipment_types: string[]; opt_in: boolean; active: boolean };
export type TrackingView = {
  trip_id: string; shipment_request_id: string; status: string;
  tracking: { driver_id?: string; confirmed_at?: string; route_status?: string; route_error?: string; points?: RoutePoint[]; route?: { polyline: string; distance_meters: number; duration_seconds: number }; latest_report_id?: string; route_calculated_at?: string };
  checkpoints: RoutingRow<{ stage: string; requested_at: string }>[];
  reports: RoutingRow<{ latitude: number; longitude: number; occurred_at: string }>[];
};
