import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { PageState } from "../components/PageState";
import { StatusBadge } from "../components/StatusBadge";
import { PaginationBar } from "../components/PaginationBar";
import type { CarrierListItem, RouteAvailability, RouteAvailabilityMatch } from "../types";

export function RouteAvailabilities() {
  const [searchParams, setSearchParams] = useSearchParams();
  const limit = Number(searchParams.get("limit") || "25");
  const offset = Number(searchParams.get("offset") || "0");
  const [rows, setRows] = useState<RouteAvailability[]>([]);
  const [total, setTotal] = useState(0);
  const [carriers, setCarriers] = useState<CarrierListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [matches, setMatches] = useState<RouteAvailabilityMatch[]>([]);
  const [form, setForm] = useState({
    carrier_id: "", test_run_id: "", origin: "", destination: "", stops: "",
    window_start: "", window_end: "", capacity: "", capacity_unit: "",
    cargo_types: "", equipment_types: ""
  });
  const [query, setQuery] = useState({
    origin: "", destination: "", shipment_at: "", cargo_type: "",
    quantity: "", quantity_unit: "", equipment_type: ""
  });

  const refresh = () => {
    setLoading(true);
    Promise.all([api.routeAvailabilitiesPage(limit, offset), api.carriers({ limit: 100 })])
      .then(([availabilityPage, carrierRows]) => {
        setRows(availabilityPage.items);
        setTotal(availabilityPage.total);
        setCarriers(carrierRows);
        setForm((current) => ({ ...current, carrier_id: current.carrier_id || carrierRows[0]?.id || "" }));
      })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  };

  useEffect(refresh, [limit, offset]);

  const changePage = (nextOffset: number, nextLimit = limit) => {
    const next = new URLSearchParams(searchParams);
    next.set("limit", String(nextLimit)); next.set("offset", String(nextOffset));
    setSearchParams(next);
  };

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.createRouteAvailability({
        carrier_id: form.carrier_id,
        test_run_id: form.test_run_id.trim() || null,
        origin: form.origin.trim(),
        destination: form.destination.trim(),
        stops: form.stops.split(",").map((item) => item.trim()).filter(Boolean),
        window_start: form.window_start ? new Date(form.window_start).toISOString() : null,
        window_end: form.window_end ? new Date(form.window_end).toISOString() : null,
        capacity: form.capacity || null,
        capacity_unit: form.capacity ? form.capacity_unit || null : null,
        cargo_types: form.cargo_types.split(",").map((item) => item.trim()).filter(Boolean),
        equipment_types: form.equipment_types.split(",").map((item) => item.trim()).filter(Boolean)
      });
      setForm((current) => ({ ...current, origin: "", destination: "", stops: "", capacity: "", cargo_types: "", equipment_types: "" }));
      refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No se pudo guardar la disponibilidad");
    } finally {
      setSaving(false);
    }
  };

  const updateStatus = async (item: RouteAvailability, status: "ACTIVE" | "CLOSED" | "CANCELLED") => {
    setError(null);
    try {
      await api.updateRouteAvailabilityStatus(item.id, status);
      refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No se pudo cambiar el estado");
    }
  };

  const search = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    try {
      setMatches(await api.matchRouteAvailabilities({
        origin: query.origin.trim(), destination: query.destination.trim(),
        shipment_at: query.shipment_at ? new Date(query.shipment_at).toISOString() : null,
        cargo_type: query.cargo_type.trim() || null,
        quantity: query.quantity || null, quantity_unit: query.quantity_unit || null,
        equipment_type: query.equipment_type.trim() || null
      }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No se pudo buscar coincidencias");
    }
  };

  return (
    <section className="page">
      <header className="page-header">
        <div><h1>Recorridos disponibles</h1><p>Rutas que los transportistas dijeron que pueden hacer.</p></div>
        <button type="button" className="secondary-button" onClick={refresh}>Actualizar</button>
      </header>
      {error ? <div className="state-box error"><strong>No se pudo completar la operación</strong><span>{error}</span></div> : null}

      <details className="panel form-disclosure">
        <summary>＋ Nueva disponibilidad</summary>
        <div className="disclosure-body"><h2>Registrar recorrido disponible</h2>
        <p>Primero queda como borrador. Confirmá los datos con el transportista antes de activarlo.</p>
        <form className="form-grid" onSubmit={submit}>
          <label>Transportista<select required value={form.carrier_id} onChange={(event) => setForm({ ...form, carrier_id: event.target.value })}>
            <option value="">Seleccionar</option>{carriers.map((carrier) => <option key={carrier.id} value={carrier.id}>{carrier.name} · {carrier.id}</option>)}
          </select></label>
          <label>Origen<input required value={form.origin} onChange={(event) => setForm({ ...form, origin: event.target.value })} /></label>
          <label>Destino<input required value={form.destination} onChange={(event) => setForm({ ...form, destination: event.target.value })} /></label>
          <label>Paradas intermedias (separadas por coma)<input value={form.stops} onChange={(event) => setForm({ ...form, stops: event.target.value })} /></label>
          <label>Desde<input type="datetime-local" value={form.window_start} onChange={(event) => setForm({ ...form, window_start: event.target.value })} /></label>
          <label>Hasta<input type="datetime-local" value={form.window_end} onChange={(event) => setForm({ ...form, window_end: event.target.value })} /></label>
          <label>Capacidad declarada<input type="number" min="0.001" step="any" value={form.capacity} onChange={(event) => setForm({ ...form, capacity: event.target.value })} /></label>
          <label>Unidad de capacidad<select value={form.capacity_unit} onChange={(event) => setForm({ ...form, capacity_unit: event.target.value })}>
            <option value="">Seleccionar</option><option value="TON">Toneladas</option><option value="KG">Kilogramos</option><option value="HEAD">Cabezas</option><option value="TRUCKLOAD">Camiones</option>
          </select></label>
          <label>Tipos de carga admitidos<input placeholder="soja, maíz" value={form.cargo_types} onChange={(event) => setForm({ ...form, cargo_types: event.target.value })} /></label>
          <label>Equipos admitidos<input placeholder="granelero, jaula" value={form.equipment_types} onChange={(event) => setForm({ ...form, equipment_types: event.target.value })} /></label>
          {import.meta.env.VITE_SHOW_QA_FIELDS === "true" ? <label>Escenario QA<input value={form.test_run_id} onChange={(event) => setForm({ ...form, test_run_id: event.target.value })} /></label> : null}
          <button className="primary-button" disabled={saving || !form.carrier_id}>{saving ? "Guardando…" : "Guardar borrador"}</button>
        </form>
        </div>
      </details>

      <details className="panel form-disclosure">
        <summary>⌕ Buscar coincidencias de recorrido</summary>
        <div className="disclosure-body"><h2>Buscar recorridos</h2>
        <p>Buscar no confirma un viaje ni guarda capacidad.</p>
        <form className="form-grid" onSubmit={search}>
          <label>Origen<input required value={query.origin} onChange={(event) => setQuery({ ...query, origin: event.target.value })} /></label>
          <label>Destino<input required value={query.destination} onChange={(event) => setQuery({ ...query, destination: event.target.value })} /></label>
          <label>Fecha solicitada<input type="datetime-local" value={query.shipment_at} onChange={(event) => setQuery({ ...query, shipment_at: event.target.value })} /></label>
          <label>Tipo de carga<input value={query.cargo_type} onChange={(event) => setQuery({ ...query, cargo_type: event.target.value })} /></label>
          <label>Cantidad<input type="number" min="0" step="any" value={query.quantity} onChange={(event) => setQuery({ ...query, quantity: event.target.value })} /></label>
          <label>Unidad<select value={query.quantity_unit} onChange={(event) => setQuery({ ...query, quantity_unit: event.target.value })}>
            <option value="">Sin confirmar</option><option value="TON">Toneladas</option><option value="KG">Kilogramos</option><option value="HEAD">Cabezas</option><option value="TRUCKLOAD">Camiones</option>
          </select></label>
          <label>Equipo requerido<input value={query.equipment_type} onChange={(event) => setQuery({ ...query, equipment_type: event.target.value })} /></label>
          <button className="primary-button">Buscar</button>
        </form>
        {matches.map((match) => <article className="availability-match" key={match.availability.id}>
          <strong>{match.segment_origin} → {match.segment_destination}</strong>
          <span>Transportista: {carriers.find((carrier) => carrier.id === match.availability.carrier_id)?.name ?? match.availability.carrier_id}</span>
          <ul>{match.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
        </article>)}
        {matches.length === 0 ? <p>Sin coincidencias para la consulta actual.</p> : null}
        </div>
      </details>

      <section className="panel">
        <h2>Recorridos cargados</h2>
        <PageState loading={loading} error={null} empty={!loading && rows.length === 0} emptyTitle="No hay disponibilidades" onRefresh={refresh}>
        <PaginationBar total={total} limit={limit} offset={offset} onPageChange={changePage} noun="disponibilidades" />
        {rows.map((item) => <article className="availability-row" key={item.id}>
          <div><strong>{item.origin} → {item.stops.length ? `${item.stops.join(" → ")} → ` : ""}{item.destination}</strong>
            <span>{carriers.find((carrier) => carrier.id === item.carrier_id)?.name ?? item.carrier_id}</span>
            <span>{item.capacity ? `${item.capacity} ${item.capacity_unit}` : "Capacidad sin declarar"} · {item.cargo_types.join(", ") || "carga por confirmar"}</span>
          </div>
          <StatusBadge status={item.status} />
          <div className="header-actions">
            {item.status === "DRAFT" ? <button className="secondary-button" onClick={() => updateStatus(item, "ACTIVE")}>Activar</button> : null}
            {item.status === "ACTIVE" ? <><button className="secondary-button" onClick={() => updateStatus(item, "CLOSED")}>Cerrar</button><button className="secondary-button" onClick={() => updateStatus(item, "CANCELLED")}>Cancelar</button></> : null}
          </div>
        </article>)}
        </PageState>
      </section>
    </section>
  );
}
