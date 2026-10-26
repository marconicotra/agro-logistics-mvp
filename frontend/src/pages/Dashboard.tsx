import { api } from "../api/client";
import { MetricCard } from "../components/MetricCard";
import { PageState } from "../components/PageState";
import type { Overview } from "../types";
import { useEffect, useState } from "react";

export function Dashboard() {
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    api
      .overview()
      .then(setData)
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>Operación</h1>
          <p>Revisá lo que necesita atención y entrá directamente a los registros.</p>
        </div>
        <button type="button" className="secondary-button" onClick={load}>
          ↻ Actualizar
        </button>
      </header>

      <PageState loading={loading} error={error} empty={!data} emptyTitle="Sin métricas" onRefresh={load}>
        {data ? (
          <>
            <section className="metric-section">
              <h2>Necesitan seguimiento</h2>
              <div className="metric-grid dashboard-priority-grid">
                <MetricCard label="Cargas sin asignar" value={data.unassigned_published_shipments} icon="box" to="/shipments" />
                <MetricCard label="Viajes planificados" value={data.planned_trips} icon="truck" to="/trips?status=PLANNED" />
                <MetricCard label="Viajes en curso" value={data.in_progress_trips} icon="map" to="/trips?status=IN_TRANSIT" />
                <MetricCard label="Homologaciones en revisión" value={data.carrier_onboarding_pending_review} icon="users" to="/carriers?filter=REVIEW" />
                <MetricCard label="Conversaciones para revisar" value={data.open_conversations_requiring_operator} icon="chat" to="/conversations?needs_operator=true" />
                <MetricCard label="Avisos fallidos" value={data.failed_notifications} icon="bell" to="/notifications?status=FAILED" />
              </div>
            </section>
            <details className="panel secondary-metrics">
              <summary>Ver todos los indicadores</summary>
              <div className="metric-section"><h2>Conversaciones y cargas</h2><div className="metric-grid">
                <MetricCard label="Conversaciones abiertas" value={data.open_conversations} icon="chat" to="/conversations" />
                <MetricCard label="Ubicaciones por revisar" value={data.ambiguous_conversations} icon="map" to="/conversations?ambiguous=true" />
                <MetricCard label="Cargas publicadas" value={data.published_shipments} icon="box" to="/shipments" />
                <MetricCard label="En búsqueda" value={data.shipments_in_matching} icon="box" to="/shipments" />
                <MetricCard label="Asignadas" value={data.assigned_shipments} icon="box" to="/shipments" />
                <MetricCard label="Demora promedio sin asignar" value={`${data.avg_unassigned_age_hours} h`} icon="bell" to="/shipments" hint="Promedio de las cargas publicadas o en búsqueda que siguen sin asignación." />
              </div></div>
              <div className="metric-section"><h2>Transportistas y documentos</h2><div className="metric-grid">
                <MetricCard label="Transportistas aprobados" value={data.validated_carriers} icon="users" to="/carriers?filter=APPROVED" />
                <MetricCard label="Transportistas pendientes" value={data.pending_validation_carriers} icon="users" to="/carriers?filter=PENDING" />
                <MetricCard label="Documentos pendientes" value={data.pending_documents} icon="shield" to="/carriers?filter=PENDING" />
                <MetricCard label="Documentos aprobados" value={data.approved_documents} icon="shield" to="/carriers" />
                <MetricCard label="Documentos rechazados" value={data.rejected_documents} icon="shield" to="/carriers" />
              </div></div>
            </details>
          </>
        ) : null}
      </PageState>
    </section>
  );
}
