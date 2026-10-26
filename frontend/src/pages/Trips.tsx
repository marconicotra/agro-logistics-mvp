import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { DataTable, type Column } from "../components/DataTable";
import { PageState } from "../components/PageState";
import { PaginationBar } from "../components/PaginationBar";
import { StatusBadge } from "../components/StatusBadge";
import { display, formatDate } from "../format";
import type { CarrierDetail, Trip, TripPayload } from "../types";
import { statusLabel } from "../labels";

const statuses = ["", "PLANNED", "IN_TRANSIT", "COMPLETED", "CANCELLED", "FAILED"];
function toDateTimeLocal(value: string | null | undefined) {
  if (!value) return "";
  return value.slice(0, 16);
}

function fromDateTimeLocal(value: string) {
  return value ? new Date(value).toISOString() : null;
}

export function Trips() {
  const [searchParams, setSearchParams] = useSearchParams();
  const status = searchParams.get("status") ?? "";
  const limit = Number(searchParams.get("limit") || "25");
  const offset = Number(searchParams.get("offset") || "0");
  const [rows, setRows] = useState<Trip[]>([]);
  const [total, setTotal] = useState(0);
  const [editingTrip, setEditingTrip] = useState<Trip | null>(null);
  const [editForm, setEditForm] = useState<TripPayload>({});
  const [crewOptions, setCrewOptions] = useState<CarrierDetail | null>(null);
  const [crewDriverId, setCrewDriverId] = useState("");
  const [crewVehicleId, setCrewVehicleId] = useState("");
  const [busyTripId, setBusyTripId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    setNotice(null);
    api
      .tripsPage(status || undefined, limit, offset)
      .then((page) => { setRows(page.items); setTotal(page.total); })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  };

  const changePage = (nextOffset: number, nextLimit = limit) => {
    const next = new URLSearchParams(searchParams);
    next.set("limit", String(nextLimit));
    next.set("offset", String(nextOffset));
    setSearchParams(next);
  };

  const openEditTrip = (trip: Trip) => {
    setEditingTrip(trip);
    setCrewOptions(null);
    setCrewDriverId(trip.driver_id ?? "");
    setCrewVehicleId(trip.vehicle_id ?? "");
    api.carrierDetail(trip.carrier_id).then(setCrewOptions).catch((reason: Error) => setError(reason.message));
    setEditForm({
      planned_start_at: toDateTimeLocal(trip.planned_start_at),
      incident_notes: "",
      closure_notes: "",
      requires_human_review: false
    });
  };

  const saveTrip = async () => {
    if (!editingTrip) return;
    setBusyTripId(editingTrip.id);
    setError(null);
    try {
      await api.updateTrip(editingTrip.id, {
        ...editForm,
        planned_start_at: fromDateTimeLocal(String(editForm.planned_start_at ?? "")),
        planned_end_at: fromDateTimeLocal(String(editForm.planned_end_at ?? "")),
        started_at: fromDateTimeLocal(String(editForm.started_at ?? "")),
        completed_at: fromDateTimeLocal(String(editForm.completed_at ?? "")),
        cancelled_at: fromDateTimeLocal(String(editForm.cancelled_at ?? ""))
      });
      setEditingTrip(null);
      setNotice(`Viaje ${editingTrip.id} editado.`);
      setLoading(true);
      api
        .tripsPage(status || undefined, limit, offset)
        .then((page) => { setRows(page.items); setTotal(page.total); })
        .catch((reason: Error) => setError(reason.message))
        .finally(() => setLoading(false));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No pude guardar el viaje.");
    } finally {
      setBusyTripId(null);
    }
  };

  const saveCrew = async () => {
    if (!editingTrip || !crewDriverId || !crewVehicleId) return;
    setBusyTripId(editingTrip.id);
    setError(null);
    try {
      await api.assignTripCrew(editingTrip.id, crewDriverId, crewVehicleId);
      setNotice(`Conductor y unidad asignados al viaje ${editingTrip.id}.`);
      setEditingTrip(null);
      load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No pude asignar conductor y unidad.");
    } finally {
      setBusyTripId(null);
    }
  };

  const deleteTrip = async (tripId: string) => {
    if (!window.confirm(`¿Borrar el viaje ${tripId}? Se conserva trazabilidad interna.`)) {
      return;
    }
    setBusyTripId(tripId);
    setError(null);
    try {
      await api.deleteTrip(tripId);
      setNotice(`Viaje ${tripId} borrado del backoffice.`);
      setRows((current) => current.filter((row) => row.id !== tripId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No pude borrar el viaje.");
    } finally {
      setBusyTripId(null);
    }
  };

  useEffect(load, [status, limit, offset]);

  const columns = useMemo<Column<Trip>[]>(
    () => [
      { key: "id", header: "Viaje", render: (row) => <Link className="inline-link" to={`/shipments/${row.shipment_request_id}`}>Abrir carga asociada →</Link> },
      { key: "status", header: "Estado", render: (row) => <StatusBadge status={row.status} /> },
      {
        key: "shipment",
        header: "Carga",
        render: (row) => (
          <Link to={`/shipments/${row.shipment_request_id}`} className="inline-link">
            {row.shipment_request_id}
          </Link>
        )
      },
      {
        key: "carrier",
        header: "Transportista",
        render: (row) => `${display(row.carrier_name)} (${row.carrier_id})`
      },
      { key: "driver", header: "Conductor", render: (row) => display(row.driver_id) },
      { key: "vehicle", header: "Unidad", render: (row) => display(row.vehicle_id) },
      { key: "origin", header: "Origen", render: (row) => display(row.origin) },
      { key: "destination", header: "Destino", render: (row) => display(row.destination) },
      { key: "planned", header: "Inicio planificado", render: (row) => formatDate(row.planned_start_at) },
      { key: "updated", header: "Actualizado", render: (row) => formatDate(row.updated_at) },
      {
        key: "actions",
        header: "Operación",
        render: (row) => (
          <div className="row-actions inline-actions">
            <Link to={`/trips/${row.id}/tracking${row.test_run_id ? `?test_run_id=${encodeURIComponent(row.test_run_id)}` : ""}`}>📍 Seguimiento</Link>
            <button
              type="button"
              className="secondary-button"
              disabled={busyTripId === row.id}
              onClick={() => openEditTrip(row)}
            >
              Editar
            </button>
            <button
              type="button"
              className="danger-button"
              disabled={busyTripId === row.id}
              onClick={() => void deleteTrip(row.id)}
            >
              Borrar
            </button>
          </div>
        )
      }
    ],
    [busyTripId]
  );

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>Viajes</h1>
          <p>Consulta de viajes por estado operativo.</p>
        </div>
        <button type="button" className="secondary-button" onClick={load}>
          Actualizar
        </button>
      </header>
      <div className="filters">
        {statuses.map((item) => (
          <button
            key={item || "all"}
            type="button"
            className={item === status ? "filter-button active" : "filter-button"}
            onClick={() => setSearchParams(item ? { status: item } : {})}
          >
            {item ? statusLabel(item) : "Todos"}
          </button>
        ))}
      </div>
      {notice ? <div className="state-box">{notice}</div> : null}
      {editingTrip ? (
        <div className="panel form-panel edit-panel">
          <div className="panel-header">
            <div>
              <h2>Editar viaje {editingTrip.id}</h2>
              <p className="panel-subtitle">Correcciones operativas con evento de auditoría.</p>
            </div>
            <button type="button" className="secondary-button" onClick={() => setEditingTrip(null)}>
              Cerrar
            </button>
          </div>
          <div className="form-grid compact-grid">
            <div className="field">
              <span>Estado actual</span>
              <StatusBadge status={editingTrip.status} />
            </div>
            <label className="field">
              <span>Inicio planificado</span>
              <input
                className="text-input"
                type="datetime-local"
                value={String(editForm.planned_start_at ?? "")}
                onChange={(event) =>
                  setEditForm((current) => ({ ...current, planned_start_at: event.target.value }))
                }
              />
            </label>
            <label className="field">
              <span>Fin planificado</span>
              <input
                className="text-input"
                type="datetime-local"
                value={String(editForm.planned_end_at ?? "")}
                onChange={(event) =>
                  setEditForm((current) => ({ ...current, planned_end_at: event.target.value }))
                }
              />
            </label>
            <label className="field">
              <span>Inicio real</span>
              <input
                className="text-input"
                type="datetime-local"
                value={String(editForm.started_at ?? "")}
                onChange={(event) => setEditForm((current) => ({ ...current, started_at: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>Completado</span>
              <input
                className="text-input"
                type="datetime-local"
                value={String(editForm.completed_at ?? "")}
                onChange={(event) =>
                  setEditForm((current) => ({ ...current, completed_at: event.target.value }))
                }
              />
            </label>
            <label className="field">
              <span>Cancelado</span>
              <input
                className="text-input"
                type="datetime-local"
                value={String(editForm.cancelled_at ?? "")}
                onChange={(event) =>
                  setEditForm((current) => ({ ...current, cancelled_at: event.target.value }))
                }
              />
            </label>
            <label className="field wide-field">
              <span>Notas de incidencia</span>
              <textarea
                className="text-input text-area"
                value={editForm.incident_notes ?? ""}
                onChange={(event) =>
                  setEditForm((current) => ({ ...current, incident_notes: event.target.value }))
                }
              />
            </label>
            <label className="field wide-field">
              <span>Notas de cierre</span>
              <textarea
                className="text-input text-area"
                value={editForm.closure_notes ?? ""}
                onChange={(event) =>
                  setEditForm((current) => ({ ...current, closure_notes: event.target.value }))
                }
              />
            </label>
          </div>
          <div className="check-row">
            <label>
              <input
                type="checkbox"
                checked={Boolean(editForm.requires_human_review)}
                onChange={(event) =>
                  setEditForm((current) => ({ ...current, requires_human_review: event.target.checked }))
                }
              />
              Requiere revisión
            </label>
          </div>
          <div className="form-grid compact-grid">
            <label className="field">
              <span>Conductor aprobado</span>
              <select className="text-input" value={crewDriverId} onChange={(event) => setCrewDriverId(event.target.value)}>
                <option value="">Seleccionar conductor</option>
                {(crewOptions?.drivers ?? []).map((driver) => (
                  <option key={driver.id} value={driver.id} disabled={driver.validation_status !== "APPROVED"}>
                    {driver.name} · {driver.validation_status}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Unidad aprobada</span>
              <select className="text-input" value={crewVehicleId} onChange={(event) => setCrewVehicleId(event.target.value)}>
                <option value="">Seleccionar unidad</option>
                {(crewOptions?.vehicles ?? []).map((vehicle) => (
                  <option
                    key={vehicle.id}
                    value={vehicle.id}
                    disabled={vehicle.validation_status !== "APPROVED" || vehicle.status !== "ACTIVE"}
                  >
                    {vehicle.plate_number ?? vehicle.id} · {vehicle.validation_status}
                  </option>
                ))}
              </select>
            </label>
            <div className="panel-actions form-actions-full">
              <button
                type="button"
                className="secondary-button"
                disabled={busyTripId === editingTrip.id || !crewDriverId || !crewVehicleId}
                onClick={() => void saveCrew()}
              >
                Asignar conductor y unidad
              </button>
            </div>
          </div>
          <div className="panel-actions">
            <button
              type="button"
              className="primary-button"
              disabled={busyTripId === editingTrip.id}
              onClick={() => void saveTrip()}
            >
              Guardar cambios
            </button>
          </div>
        </div>
      ) : null}
      <PageState
        loading={loading}
        error={error}
        empty={rows.length === 0}
        emptyTitle="No hay viajes para este filtro"
        onRefresh={load}
      >
        <><PaginationBar total={total} limit={limit} offset={offset} onPageChange={changePage} noun="viajes" /><DataTable columns={columns} rows={rows} getRowKey={(row) => row.id} /></>
      </PageState>
    </section>
  );
}
