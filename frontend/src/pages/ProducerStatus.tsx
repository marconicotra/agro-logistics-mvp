import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { PageState } from "../components/PageState";
import { RouteMapCard } from "../components/RouteMapCard";
import { StatusBadge } from "../components/StatusBadge";
import { display, formatDate, loadLabel } from "../format";
import type { JourneyStatus, ProducerDashboard } from "../types";

export function ProducerStatus() {
  const [searchParams, setSearchParams] = useSearchParams();
  const phoneFromQuery = searchParams.get("phone_number") ?? "";
  const [phoneNumber, setPhoneNumber] = useState(phoneFromQuery);
  const [dashboard, setDashboard] = useState<ProducerDashboard | null>(null);
  const [loading, setLoading] = useState(Boolean(phoneFromQuery));
  const [error, setError] = useState<string | null>(null);

  const load = (phone: string) => {
    if (!phone) return;
    setLoading(true);
    setError(null);
    api
      .producerDashboard(phone)
      .then(setDashboard)
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (phoneFromQuery) {
      setPhoneNumber(phoneFromQuery);
      load(phoneFromQuery);
    }
  }, [phoneFromQuery]);

  const metrics = useMemo(
    () =>
      dashboard
        ? [
            { label: "Cargas totales", value: dashboard.total_shipments },
            { label: "Cargas activas", value: dashboard.active_shipments },
            { label: "Viajes activos", value: dashboard.active_trips },
            { label: "Viajes completos", value: dashboard.completed_trips },
            { label: "Interesados pendientes", value: dashboard.pending_interested_offers }
          ]
        : [],
    [dashboard]
  );

  return (
    <section className="portal-page">
      <header className="portal-header">
        <div>
          <span className="portal-eyebrow">Vista del productor</span>
          <h1>Estado de tus cargas y viajes</h1>
          <p>Seguimiento simple de operaciones actuales y cerradas.</p>
        </div>
      </header>

      <section className="panel portal-search-panel">
        <div className="panel-header">
          <div>
            <h2>Buscar por teléfono</h2>
            <p className="panel-subtitle">Usá el mismo número con el que operás por WhatsApp.</p>
          </div>
        </div>
        <div className="portal-search-bar">
          <input
            className="text-input"
            value={phoneNumber}
            onChange={(event) => setPhoneNumber(event.target.value)}
            placeholder="+54911..."
          />
          <button
            type="button"
            className="primary-button"
            onClick={() => setSearchParams(phoneNumber ? { phone_number: phoneNumber } : {})}
          >
            Ver estado
          </button>
        </div>
      </section>

      <PageState
        loading={loading}
        error={error}
        empty={!dashboard}
        emptyTitle="Ingresá tu número para ver el estado"
        onRefresh={() => (phoneFromQuery ? load(phoneFromQuery) : undefined)}
      >
        {dashboard ? (
          <>
            <section className="metric-section">
              <div className="metric-grid">
                {metrics.map((metric) => (
                  <div key={metric.label} className="metric-card">
                    <span>{metric.label}</span>
                    <strong>{metric.value}</strong>
                  </div>
                ))}
              </div>
            </section>

            <section className="portal-section">
              <div className="panel-header">
                <div>
                  <h2>Operaciones actuales</h2>
                  <p className="panel-subtitle">Cargas publicadas, buscando transportista o con viajes en curso.</p>
                </div>
              </div>
              <div className="journey-grid">
                {dashboard.current_operations.length > 0 ? (
                  dashboard.current_operations.map((operation) => (
                    <JourneyCard key={`${operation.shipment_id}-${operation.trip_id ?? "shipment"}`} operation={operation} />
                  ))
                ) : (
                  <div className="state-box">No hay operaciones activas para este número.</div>
                )}
              </div>
            </section>

            <section className="portal-section">
              <div className="panel-header">
                <div>
                  <h2>Historial</h2>
                  <p className="panel-subtitle">Viajes cerrados y operaciones pasadas.</p>
                </div>
              </div>
              <div className="journey-grid">
                {dashboard.past_operations.length > 0 ? (
                  dashboard.past_operations.map((operation) => (
                    <JourneyCard key={`${operation.shipment_id}-${operation.trip_id ?? "past"}`} operation={operation} />
                  ))
                ) : (
                  <div className="state-box">Todavía no hay viajes cerrados en el historial.</div>
                )}
              </div>
            </section>
          </>
        ) : null}
      </PageState>
    </section>
  );
}

function JourneyCard({ operation }: { operation: JourneyStatus }) {
  return (
    <article className="panel journey-card">
      <RouteMapCard origin={operation.origin} destination={operation.destination} status={operation.trip_status ?? operation.shipment_status} eyebrow={operation.trip_id ? "Viaje" : "Carga"} />
      <div className="journey-card-header">
        <div>
          <strong>{loadLabel(operation)}</strong>
          <div className="muted-line">{operation.shipment_id}</div>
        </div>
        <StatusBadge status={operation.trip_status ?? operation.shipment_status} />
      </div>
      <dl className="detail-list compact-detail-list">
        <dt>Interesados</dt>
        <dd>{operation.interested_offers_count}</dd>
        <dt>Transportista</dt>
        <dd>{display(operation.counterparty_name)}</dd>
        <dt>Planificado</dt>
        <dd>{formatDate(operation.planned_start_at)}</dd>
        <dt>Creada</dt>
        <dd>{formatDate(operation.created_at)}</dd>
        <dt>Notas</dt>
        <dd>{display(operation.operational_notes)}</dd>
      </dl>
    </article>
  );
}
