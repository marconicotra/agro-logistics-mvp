import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import { DataTable, type Column } from "../components/DataTable";
import { PageState } from "../components/PageState";
import { ShipmentDispatch } from "../components/ShipmentDispatch";
import { RouteMapCard } from "../components/RouteMapCard";
import { StatusBadge } from "../components/StatusBadge";
import { display, formatDate, loadLabel } from "../format";
import type {
  CarrierListItem,
  ShipmentDetail as ShipmentDetailType,
  UnassignedShipment
} from "../types";

export function ShipmentDetail() {
  const { shipmentId } = useParams();
  const [detail, setDetail] = useState<ShipmentDetailType | null>(null);
  const [carriers, setCarriers] = useState<CarrierListItem[]>([]);
  const [selectedCarrierId, setSelectedCarrierId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    if (!shipmentId) return;
    setLoading(true);
    setError(null);
    Promise.all([
      api.shipmentDetail(shipmentId),
      api.carriers({ is_validated: true, limit: 100 })
    ])
      .then(([shipmentDetail, validatedCarriers]) => {
        setDetail(shipmentDetail);
        setCarriers(validatedCarriers);
        setSelectedCarrierId((current) => current || validatedCarriers[0]?.id || "");
      })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, [shipmentId]);

  const runAction = async (action: "interest" | "assign") => {
    if (!shipmentId) return;
    if (!selectedCarrierId) {
      setError("Elegí un transportista validado antes de ejecutar la acción.");
      return;
    }
    setBusy(true);
    setError(null);
    setFeedback(null);
    try {
      if (action === "interest") {
        const result = await api.registerManualInterest(shipmentId, selectedCarrierId);
        setFeedback(
          `Interés manual registrado para ${result.carrier_id}. Carrier: ${result.carrier_notification_status ?? "n/a"}. Productor: ${result.producer_notification_status ?? "n/a"}.`
        );
      } else {
        const result = await api.assignShipmentManually(shipmentId, selectedCarrierId);
        setFeedback(
          `Viaje ${result.trip_id} asignado a ${result.carrier_id}. Carrier: ${result.carrier_notification_status ?? "n/a"}. Productor: ${result.producer_notification_status ?? "n/a"}.`
        );
      }
      load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No pude completar la acción.");
    } finally {
      setBusy(false);
    }
  };

  const runTripAction = async (action: "start" | "transit" | "complete" | "cancel") => {
    if (!detail?.active_trip) return;
    setBusy(true);
    setError(null);
    setFeedback(null);
    try {
      if (action === "start") {
        const result = await api.startTrip(detail.active_trip.id, "Inicio registrado desde backoffice");
        setFeedback(
          `Viaje ${result.trip_id} iniciado. Carrier: ${result.carrier_notification_status ?? "n/a"}. Productor: ${result.producer_notification_status ?? "n/a"}.`
        );
      } else if (action === "transit") {
        const result = await api.markTripInTransit(detail.active_trip.id, "En tránsito desde backoffice");
        setFeedback(
          `Viaje ${result.trip_id} en tránsito. Carrier: ${result.carrier_notification_status ?? "n/a"}. Productor: ${result.producer_notification_status ?? "n/a"}.`
        );
      } else if (action === "complete") {
        const result = await api.completeTrip(detail.active_trip.id, "Viaje completado desde backoffice");
        setFeedback(
          `Viaje ${result.trip_id} completado. Carrier: ${result.carrier_notification_status ?? "n/a"}. Productor: ${result.producer_notification_status ?? "n/a"}.`
        );
      } else {
        const reason = window.prompt("Motivo de cancelación");
        if (!reason) {
          setBusy(false);
          return;
        }
        const result = await api.cancelTripFromBackoffice(detail.active_trip.id, reason);
        setFeedback(
          `Viaje ${result.trip_id} cancelado. Carrier: ${result.carrier_notification_status ?? "n/a"}. Productor: ${result.producer_notification_status ?? "n/a"}.`
        );
      }
      load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No pude actualizar el viaje.");
    } finally {
      setBusy(false);
    }
  };

  const offersColumns = useMemo<
    Column<ShipmentDetailType["offers"][number]>[]
  >(
    () => [
      {
        key: "carrier",
        header: "Transportista",
        render: (row) => (
          <div>
            <strong>{display(row.carrier_name)}</strong>
            <div className="muted-line">
              <Link to={`/carriers/${row.carrier_id}`} className="inline-link">
                {row.carrier_id}
              </Link>
              {row.carrier_phone ? ` · ${row.carrier_phone}` : ""}
            </div>
          </div>
        )
      },
      { key: "response", header: "Respuesta", render: (row) => <StatusBadge status={row.response_type} /> },
      { key: "status", header: "Estado", render: (row) => <StatusBadge status={row.status} /> },
      {
        key: "vehicle",
        header: "Vehículo",
        render: (row) => display(row.vehicle_plate ?? row.vehicle_id)
      },
      {
        key: "availability",
        header: "Disponibilidad",
        render: (row) => formatDateRange(row.availability_window_start, row.availability_window_end)
      },
      { key: "confidence", header: "Confianza", render: (row) => display(row.confidence) },
      {
        key: "message",
        header: "Mensaje",
        render: (row) => (
          <div className="table-note">
            <div>{display(row.source_message_preview)}</div>
            <small>{row.source_message_id ?? "-"}</small>
          </div>
        )
      },
      { key: "updated", header: "Actualizado", render: (row) => formatDate(row.updated_at) }
    ],
    []
  );

  const assignmentColumns = useMemo<
    Column<ShipmentDetailType["assignments"][number]>[]
  >(
    () => [
      {
        key: "id",
        header: "Assignment",
        render: (row) => (
          <div className="table-note">
            <strong>{row.id}</strong>
            <small>{row.trip_offer_id ?? "-"}</small>
          </div>
        )
      },
      {
        key: "carrier",
        header: "Transportista",
        render: (row) => (
          <div>
            <strong>{display(row.carrier_name)}</strong>
            <div className="muted-line">{display(row.vehicle_plate ?? row.vehicle_id)}</div>
          </div>
        )
      },
      { key: "status", header: "Estado", render: (row) => <StatusBadge status={row.status} /> },
      { key: "selected", header: "Seleccionado por", render: (row) => row.selected_by_user_id },
      { key: "confirmed", header: "Confirmado", render: (row) => formatDate(row.confirmed_at) },
      { key: "updated", header: "Actualizado", render: (row) => formatDate(row.updated_at) }
    ],
    []
  );

  const tripColumns = useMemo<
    Column<ShipmentDetailType["trips"][number]>[]
  >(
    () => [
      { key: "id", header: "Viaje", render: (row) => row.id },
      { key: "status", header: "Estado", render: (row) => <StatusBadge status={row.status} /> },
      {
        key: "carrier",
        header: "Transportista",
        render: (row) => (
          <div>
            <strong>{display(row.carrier_name)}</strong>
            <div className="muted-line">{display(row.vehicle_plate ?? row.vehicle_id)}</div>
          </div>
        )
      },
      { key: "planned", header: "Planificado", render: (row) => formatDateRange(row.planned_start_at, row.planned_end_at) },
      { key: "started", header: "Inicio", render: (row) => formatDate(row.started_at) },
      { key: "finished", header: "Cierre", render: (row) => formatDate(row.completed_at ?? row.cancelled_at) }
    ],
    []
  );

  return (
    <section className="page">
      <PageState
        loading={loading}
        error={error}
        empty={!detail}
        emptyTitle="No encontré la carga"
        onRefresh={load}
      >
        {detail ? (
          <>
            <header className="page-header">
              <div>
                <Link to="/shipments" className="inline-link back-link">
                  Volver a cargas
                </Link>
                <h1>Detalle de carga</h1>
                <p>{detail.shipment.id}</p>
                {detail.shipment.test_run_id ? (
                  <p className="muted">Escenario QA: {detail.shipment.test_run_id}</p>
                ) : null}
              </div>
              <div className="header-actions">
                <StatusBadge status={detail.shipment.status} />
                <button type="button" className="secondary-button" onClick={load}>
                  Actualizar
                </button>
              </div>
            </header>
            <ShipmentDispatch shipmentId={detail.shipment.id} scope={detail.shipment.test_run_id ?? ""} />


            {feedback ? <div className="feedback">{feedback}</div> : null}

            <section className="metric-section">
              <div className="metric-grid">
                <div className="metric-card">
                  <span>Interesados / ofertas</span>
                  <strong>{`${detail.offers.filter((item) => item.response_type === "INTERESTED").length} / ${detail.offers.length}`}</strong>
                </div>
                <div className="metric-card">
                  <span>Assignments</span>
                  <strong>{detail.assignments.length}</strong>
                </div>
                <div className="metric-card">
                  <span>Viajes</span>
                  <strong>{detail.trips.length}</strong>
                </div>
                <div className="metric-card">
                  <span>Eventos auditados</span>
                  <strong>{detail.events.length}</strong>
                </div>
              </div>
            </section>

            <div className="detail-grid">
              <section className="panel">
                <div className="panel-header">
                  <div>
                    <h2>Datos de la carga</h2>
                    <p className="panel-subtitle">Qué se lleva, desde dónde y hasta dónde.</p>
                  </div>
                </div>
                <dl className="detail-list">
                  <dt>Carga</dt>
                  <dd>{loadLabel(detail.shipment as unknown as UnassignedShipment)}</dd>
                  <dt>Origen</dt>
                  <dd>{display(detail.shipment.origin)}</dd>
                  <dt>Destino</dt>
                  <dd>{display(detail.shipment.destination)}</dd>
                  <dt>Ventana</dt>
                  <dd>{formatDateRange(detail.shipment.date_window_start, detail.shipment.date_window_end)}</dd>
                  <dt>Productor</dt>
                  <dd>{display(detail.shipment.producer_phone_number)}</dd>
                  <dt>Creada</dt>
                  <dd>{formatDate(detail.shipment.created_at)}</dd>
                  <dt>Actualizada</dt>
                  <dd>{formatDate(detail.shipment.updated_at)}</dd>
                  <dt>Mensaje fuente</dt>
                  <dd>{display(detail.shipment.source_message_preview)}</dd>
                  <dt>Notas</dt>
                  <dd>{display(detail.shipment.operational_notes)}</dd>
                </dl>
                {detail.shipment.producer_phone_number ? (
                  <div className="panel-actions">
                    <Link
                      to={`/producer-status?phone_number=${encodeURIComponent(detail.shipment.producer_phone_number)}`}
                      className="secondary-link-button"
                    >
                      Vista productor
                    </Link>
                  </div>
                ) : null}
              </section>

              <section className="panel">
                <div className="panel-header">
                  <div>
                    <h2>Datos para revisar</h2>
                    <p className="panel-subtitle">Faltantes o datos que pueden necesitar confirmación.</p>
                  </div>
                </div>
                <div className="chip-row">
                  {detail.shipment.requires_human_review ? <StatusBadge status="REQUIERE_OPERADOR" /> : null}
                  {detail.shipment.has_ambiguous_location ? <StatusBadge status="UBICACION_AMBIGUA" /> : null}
                  {detail.shipment.has_estimated_values ? <StatusBadge status="VALORES_ESTIMADOS" /> : null}
                  {!detail.shipment.requires_human_review &&
                  !detail.shipment.has_ambiguous_location &&
                  !detail.shipment.has_estimated_values ? (
                    <StatusBadge status="SIN_ALERTAS" />
                  ) : null}
                </div>
                <dl className="detail-list">
                  <dt>Faltantes críticos</dt>
                  <dd>{detail.shipment.missing_critical_fields.length ? detail.shipment.missing_critical_fields.join(", ") : "-"}</dd>
                  <dt>Confianza campos</dt>
                  <dd>{formatConfidence(detail.shipment.field_confidence)}</dd>
                  <dt>Categoría</dt>
                  <dd>{display(detail.shipment.cargo_category)}</dd>
                  <dt>Tipo</dt>
                  <dd>{display(detail.shipment.cargo_type ?? detail.shipment.livestock_type)}</dd>
                </dl>
              </section>

              <section className="panel wide">
                <div className="panel-header">
                  <div>
                    <h2>Ayuda del operador</h2>
                    <p className="panel-subtitle">Podés registrar interés o asignar un viaje.</p>
                  </div>
                </div>
                <div className="shipment-operation-bar">
                  <select
                    className="text-input"
                    value={selectedCarrierId}
                    onChange={(event) => setSelectedCarrierId(event.target.value)}
                  >
                    {carriers.length === 0 ? (
                      <option value="">Sin transportistas validados</option>
                    ) : (
                      carriers.map((carrier) => (
                        <option key={carrier.id} value={carrier.id}>
                          {carrier.name} ({carrier.id})
                        </option>
                      ))
                    )}
                  </select>
                  <div className="shipment-actions-buttons">
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={busy || carriers.length === 0}
                      onClick={() => void runAction("interest")}
                    >
                      Marcar interesado
                    </button>
                    <button
                      type="button"
                      className="primary-button"
                      disabled={busy || carriers.length === 0}
                      onClick={() => void runAction("assign")}
                    >
                      Asignar viaje
                    </button>
                  </div>
                </div>
              </section>

              <section className="panel">
                <div className="panel-header">
                  <div>
                    <h2>Transportista elegido</h2>
                    <p className="panel-subtitle">Estado de la confirmación.</p>
                  </div>
                </div>
                {detail.active_assignment ? (
                  <ShipmentAssignmentSummary assignment={detail.active_assignment} />
                ) : (
                  <div className="state-box">Todavía no hay assignment activo para esta carga.</div>
                )}
              </section>

              <section className="panel">
                <div className="panel-header">
                  <div>
                    <h2>Viaje activo</h2>
                    <p className="panel-subtitle">Estado y recorrido del viaje.</p>
                  </div>
                </div>
                {detail.active_trip ? (
                  <>
                    <Link to={`/trips/${detail.active_trip.id}/tracking${detail.shipment.test_run_id ? `?test_run_id=${encodeURIComponent(detail.shipment.test_run_id)}` : ""}`} className="inline-link">📍 Abrir seguimiento en mapa</Link>
                    <ShipmentTripSummary
                      trip={detail.active_trip}
                      origin={detail.shipment.origin}
                      destination={detail.shipment.destination}
                    />
                    <div className="panel-actions">
                      {detail.active_trip.status === "PLANNED" || detail.active_trip.status === "REMINDER_SENT" ? (
                        <button
                          type="button"
                          className="secondary-button"
                          disabled={busy}
                          onClick={() => void runTripAction("start")}
                        >
                          Iniciar viaje
                        </button>
                      ) : null}
                      {["PLANNED", "REMINDER_SENT", "LOADING_PENDING", "LOADING"].includes(detail.active_trip.status) ? (
                        <button
                          type="button"
                          className="secondary-button"
                          disabled={busy}
                          onClick={() => void runTripAction("transit")}
                        >
                          Marcar en tránsito
                        </button>
                      ) : null}
                      {["PLANNED", "REMINDER_SENT", "LOADING_PENDING", "LOADING", "IN_TRANSIT", "DELIVERED"].includes(
                        detail.active_trip.status
                      ) ? (
                        <button
                          type="button"
                          className="primary-button"
                          disabled={busy}
                          onClick={() => void runTripAction("complete")}
                        >
                          Completar viaje
                        </button>
                      ) : null}
                      {!["COMPLETED", "CANCELLED"].includes(detail.active_trip.status) ? (
                        <button
                          type="button"
                          className="danger-button"
                          disabled={busy}
                          onClick={() => void runTripAction("cancel")}
                        >
                          Cancelar viaje
                        </button>
                      ) : null}
                      <Link
                        to={`/carrier-status/${detail.active_trip.carrier_id}`}
                        className="secondary-link-button"
                      >
                        Vista transportista
                      </Link>
                    </div>
                  </>
                ) : (
                  <div className="state-box">Todavía no hay viaje creado o activo para esta carga.</div>
                )}
              </section>

              <section className="panel wide">
                <div className="panel-header">
                  <div>
                    <h2>Respuestas</h2>
                    <p className="panel-subtitle">Qué contestó cada transportista.</p>
                  </div>
                </div>
                {detail.offers.length > 0 ? (
                  <DataTable columns={offersColumns} rows={detail.offers} getRowKey={(row) => row.id} />
                ) : (
                  <div className="state-box">Todavía no hay ofertas ni interesados registrados.</div>
                )}
              </section>

              <section className="panel wide">
                <div className="panel-header">
                  <div>
                    <h2>Historial de confirmaciones</h2>
                    <p className="panel-subtitle">Cambios y confirmaciones anteriores.</p>
                  </div>
                </div>
                {detail.assignments.length > 0 ? (
                  <DataTable columns={assignmentColumns} rows={detail.assignments} getRowKey={(row) => row.id} />
                ) : (
                  <div className="state-box">No hay assignments registrados.</div>
                )}
              </section>

              <section className="panel wide">
                <div className="panel-header">
                  <div>
                    <h2>Viajes anteriores</h2>
                    <p className="panel-subtitle">Viajes relacionados con esta carga.</p>
                  </div>
                </div>
                {detail.trips.length > 0 ? (
                  <DataTable columns={tripColumns} rows={detail.trips} getRowKey={(row) => row.id} />
                ) : (
                  <div className="state-box">No hay viajes registrados todavía.</div>
                )}
              </section>

              <section className="panel wide">
                <div className="panel-header">
                  <div>
                    <h2>Qué pasó</h2>
                    <p className="panel-subtitle">Historial de cambios y acciones.</p>
                  </div>
                </div>
                {detail.events.length > 0 ? (
                  <ol className="timeline-list">
                    {detail.events.map((event) => (
                      <li key={event.event_id} className="timeline-item">
                        <div className="timeline-marker" />
                        <div className="timeline-content">
                          <div className="timeline-topline">
                            <div className="timeline-title-group">
                              <strong>{event.summary}</strong>
                              <div className="timeline-meta">
                                <StatusBadge status={event.event_type} />
                                <span>{event.entity_type}</span>
                              </div>
                            </div>
                            <time>{formatDate(event.occurred_at)}</time>
                          </div>
                          <div className="timeline-body">
                            <div className="timeline-actor">
                              Actor: {event.actor_type}
                              {event.actor_id ? ` · ${event.actor_id}` : ""}
                              {event.source ? ` · ${event.source}` : ""}
                            </div>
                            {event.previous_state || event.new_state ? (
                              <div className="timeline-transition">
                                Estado: {display(event.previous_state)} {" -> "} {display(event.new_state)}
                              </div>
                            ) : null}
                            {Object.keys(event.related_entity_ids).length > 0 ? (
                              <div className="timeline-related">
                                {Object.entries(event.related_entity_ids).map(([key, value]) => (
                                  <span key={key} className="timeline-related-chip">
                                    {key}: {value}
                                  </span>
                                ))}
                              </div>
                            ) : null}
                          </div>
                        </div>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <div className="state-box">No hay eventos auditados para esta carga.</div>
                )}
              </section>
            </div>
          </>
        ) : null}
      </PageState>
    </section>
  );
}

function ShipmentAssignmentSummary({
  assignment
}: {
  assignment: NonNullable<ShipmentDetailType["active_assignment"]>;
}) {
  return (
    <dl className="detail-list">
      <dt>Estado</dt>
      <dd><StatusBadge status={assignment.status} /></dd>
      <dt>Transportista</dt>
      <dd>
        <Link to={`/carriers/${assignment.carrier_id}`} className="inline-link">
          {display(assignment.carrier_name)}
        </Link>
      </dd>
      <dt>Teléfono</dt>
      <dd>{display(assignment.carrier_phone)}</dd>
      <dt>Vehículo</dt>
      <dd>{display(assignment.vehicle_plate ?? assignment.vehicle_id)}</dd>
      <dt>Oferta origen</dt>
      <dd>{display(assignment.trip_offer_id)}</dd>
      <dt>Seleccionado por</dt>
      <dd>{assignment.selected_by_user_id}</dd>
      <dt>Confirmado</dt>
      <dd>{formatDate(assignment.confirmed_at)}</dd>
      <dt>Notas</dt>
      <dd>{display(assignment.confirmation_notes)}</dd>
    </dl>
  );
}

function ShipmentTripSummary({
  trip,
  origin,
  destination
}: {
  trip: NonNullable<ShipmentDetailType["active_trip"]>;
  origin: string | null;
  destination: string | null;
}) {
  return (
    <>
      <RouteMapCard origin={origin} destination={destination} status={trip.status} eyebrow="Seguimiento" />
      <dl className="detail-list">
        <dt>Estado</dt>
        <dd><StatusBadge status={trip.status} /></dd>
        <dt>Transportista</dt>
        <dd>
          <Link to={`/carriers/${trip.carrier_id}`} className="inline-link">
            {display(trip.carrier_name)}
          </Link>
        </dd>
        <dt>Conductor</dt>
        <dd>{display(trip.driver_id)}</dd>
        <dt>Vehículo</dt>
        <dd>{display(trip.vehicle_plate ?? trip.vehicle_id)}</dd>
        <dt>Inicio planificado</dt>
        <dd>{formatDate(trip.planned_start_at)}</dd>
        <dt>Fin planificado</dt>
        <dd>{formatDate(trip.planned_end_at)}</dd>
        <dt>Inicio real</dt>
        <dd>{formatDate(trip.started_at)}</dd>
        <dt>Cierre</dt>
        <dd>{formatDate(trip.completed_at ?? trip.cancelled_at)}</dd>
        <dt>Incidentes</dt>
        <dd>{display(trip.incident_notes)}</dd>
        <dt>Cierre operativo</dt>
        <dd>{display(trip.closure_notes)}</dd>
      </dl>
    </>
  );
}

function formatDateRange(start?: string | null, end?: string | null) {
  if (!start && !end) return "-";
  if (start && end) return `${formatDate(start)} -> ${formatDate(end)}`;
  return formatDate(start ?? end);
}

function formatConfidence(confidence: Record<string, string>) {
  const entries = Object.entries(confidence);
  if (entries.length === 0) return "-";
  return entries.map(([key, value]) => `${key}: ${value}`).join(" · ");
}
