import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import { PageState } from "../components/PageState";
import { RouteMapCard } from "../components/RouteMapCard";
import { StatusBadge } from "../components/StatusBadge";
import { display, formatDate, loadLabel } from "../format";
import type { CarrierDashboard, JourneyStatus } from "../types";

export function CarrierStatus() {
  const { carrierId = "" } = useParams();
  const navigate = useNavigate();
  const [carrierInput, setCarrierInput] = useState(carrierId);
  const [dashboard, setDashboard] = useState<CarrierDashboard | null>(null);
  const [loading, setLoading] = useState(Boolean(carrierId));
  const [error, setError] = useState<string | null>(null);

  const load = (id: string) => {
    if (!id) return;
    setLoading(true);
    setError(null);
    api
      .carrierDashboard(id)
      .then(setDashboard)
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (carrierId) {
      setCarrierInput(carrierId);
      load(carrierId);
    }
  }, [carrierId]);

  const metrics = useMemo(
    () =>
      dashboard
        ? [
            { label: "Ofertas totales", value: dashboard.total_offers },
            { label: "Ofertas abiertas", value: dashboard.open_offers },
            { label: "Viajes activos", value: dashboard.active_trips },
            { label: "Completados", value: dashboard.completed_trips },
            { label: "Cancelados", value: dashboard.cancelled_trips }
          ]
        : [],
    [dashboard]
  );

  return (
    <section className="portal-page">
      <header className="portal-header">
        <div>
            <span className="portal-eyebrow">Vista del transportista</span>
          <h1>Estado de viajes y oportunidades</h1>
          <p>Seguimiento operativo de viajes actuales y del historial reciente.</p>
        </div>
      </header>

      <section className="panel portal-search-panel">
        <div className="panel-header">
          <div>
            <h2>Buscar por transportista</h2>
            <p className="panel-subtitle">Ingresá el código de transportista para abrir la vista operativa.</p>
          </div>
        </div>
        <div className="portal-search-bar">
          <input
            className="text-input"
            value={carrierInput}
            onChange={(event) => setCarrierInput(event.target.value)}
            placeholder="car_..."
          />
          <button
            type="button"
            className="primary-button"
            onClick={() => navigate(carrierInput ? `/carrier-status/${carrierInput}` : "/carrier-status")}
          >
            Ver estado
          </button>
        </div>
      </section>

      <PageState
        loading={loading}
        error={error}
        empty={!dashboard}
        emptyTitle="Ingresá un transportista para ver su estado"
        onRefresh={() => (carrierId ? load(carrierId) : undefined)}
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

            <section className="panel portal-identity-panel">
              <div className="journey-card-header">
                <div>
                  <h2>{dashboard.carrier_name}</h2>
                  <p className="panel-subtitle">
                    {dashboard.carrier_id} · {display(dashboard.carrier_phone)}
                  </p>
                </div>
                <StatusBadge status={dashboard.active_trips > 0 ? "EN_OPERACION" : "DISPONIBLE"} />
              </div>
            </section>

            <section className="portal-section">
              <div className="panel-header">
                <div>
                  <h2>Viajes actuales</h2>
                  <p className="panel-subtitle">Operaciones en preparación, carga o tránsito.</p>
                </div>
              </div>
              <div className="journey-grid">
                {dashboard.current_operations.length > 0 ? (
                  dashboard.current_operations.map((operation) => (
                    <CarrierJourneyCard key={`${operation.shipment_id}-${operation.trip_id ?? "trip"}`} operation={operation} />
                  ))
                ) : (
                  <div className="state-box">No hay viajes activos para este transportista.</div>
                )}
              </div>
            </section>

            <section className="portal-section">
              <div className="panel-header">
                <div>
                  <h2>Historial de viajes</h2>
                  <p className="panel-subtitle">Últimas operaciones completadas o canceladas.</p>
                </div>
              </div>
              <div className="journey-grid">
                {dashboard.past_operations.length > 0 ? (
                  dashboard.past_operations.map((operation) => (
                    <CarrierJourneyCard key={`${operation.shipment_id}-${operation.trip_id ?? "past"}`} operation={operation} />
                  ))
                ) : (
                  <div className="state-box">Todavía no hay historial de viajes para mostrar.</div>
                )}
              </div>
            </section>
          </>
        ) : null}
      </PageState>
    </section>
  );
}

function CarrierJourneyCard({ operation }: { operation: JourneyStatus }) {
  return (
    <article className="panel journey-card">
      <RouteMapCard origin={operation.origin} destination={operation.destination} status={operation.trip_status ?? operation.shipment_status} eyebrow="Viaje" />
      <div className="journey-card-header">
        <div>
          <strong>{loadLabel(operation)}</strong>
          <div className="muted-line">{operation.trip_id ?? operation.shipment_id}</div>
        </div>
        <StatusBadge status={operation.trip_status ?? operation.shipment_status} />
      </div>
      <dl className="detail-list compact-detail-list">
        <dt>Productor</dt>
        <dd>{display(operation.counterparty_name)}</dd>
        <dt>Teléfono</dt>
        <dd>{display(operation.counterparty_phone)}</dd>
        <dt>Planificado</dt>
        <dd>{formatDate(operation.planned_start_at)}</dd>
        <dt>Cierre</dt>
        <dd>{formatDate(operation.completed_at)}</dd>
        <dt>Notas</dt>
        <dd>{display(operation.operational_notes)}</dd>
      </dl>
    </article>
  );
}
