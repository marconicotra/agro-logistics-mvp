import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import { PageState } from "../components/PageState";
import { StatusBadge } from "../components/StatusBadge";
import { display, formatDate, loadLabel } from "../format";
import type { ProducerDetail as ProducerDetailType } from "../types";

export function ProducerDetail() {
  const { producerId } = useParams();
  const [detail, setDetail] = useState<ProducerDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    if (!producerId) return;
    setLoading(true);
    setError(null);
    api.producerDetail(producerId).then(setDetail).catch((reason: Error) => setError(reason.message)).finally(() => setLoading(false));
  };

  useEffect(load, [producerId]);
  const producer = detail?.producer;

  return (
    <section className="page">
      <header className="page-header">
        <div><h1>{producer?.name ?? "Productor"}</h1><p>Ficha y actividad vinculada a los datos disponibles.</p></div>
        <Link className="secondary-button" to="/producers">Volver a productores</Link>
      </header>
      <PageState loading={loading} error={error} empty={!detail} emptyTitle="No se encontró el productor" onRefresh={load}>
        {detail ? <>
          <div className="detail-grid">
            <article className="panel"><h2>Perfil</h2><dl className="detail-list">
              <dt>Teléfono</dt><dd>{display(producer?.phone)}</dd>
              <dt>Estado</dt><dd><StatusBadge status={producer?.is_validated ? "APPROVED" : "DECLARED"} /></dd>
              <dt>Ubicación habitual</dt><dd>{display(producer?.usual_location_id)}</dd>
              <dt>Última actividad</dt><dd>{formatDate(producer?.last_activity_at)}</dd>
              <dt>Notas internas</dt><dd>{display(detail.trust_notes)}</dd>
              <dt>Validado</dt><dd>{formatDate(detail.validated_at)}</dd>
            </dl></article>
            <article className="panel"><h2>Actividad</h2><dl className="detail-list">
              <dt>Cargas</dt><dd>{detail.shipments.length}</dd>
              <dt>Interesados</dt><dd>{detail.offers.length}</dd>
              <dt>Viajes</dt><dd>{detail.trips.length}</dd>
              <dt>Conversaciones</dt><dd>{detail.conversation_ids.length}</dd>
            </dl></article>
          </div>
          <article className="panel"><h2>Cargas</h2>{detail.shipments.length ? <div className="table-wrap"><table className="data-table"><thead><tr><th>Carga</th><th>Estado</th><th>Recorrido</th><th>Mercadería</th><th>Fecha</th></tr></thead><tbody>
            {detail.shipments.map((shipment) => <tr key={shipment.id}><td><Link className="inline-link" to={`/shipments/${shipment.id}`}>{shipment.id}</Link></td><td><StatusBadge status={shipment.status} /></td><td>{display(shipment.origin)} → {display(shipment.destination)}</td><td>{loadLabel(shipment)}</td><td>{formatDate(shipment.date_window_start)}</td></tr>)}
          </tbody></table></div> : <p>No hay cargas relacionadas.</p>}</article>
          <article className="panel"><h2>Conversaciones</h2>{detail.conversation_ids.length ? detail.conversation_ids.map((id) => <p key={id}><Link className="inline-link" to={`/conversations/${id}`}>Abrir conversación {id}</Link></p>) : <p>No hay conversaciones relacionadas.</p>}</article>
          <article className="panel"><h2>Viajes</h2>{detail.trips.length ? <div className="table-wrap"><table className="data-table"><thead><tr><th>Viaje</th><th>Carga</th><th>Estado</th><th>Inicio previsto</th></tr></thead><tbody>
            {detail.trips.map((trip) => <tr key={trip.id}><td>{trip.id}</td><td><Link className="inline-link" to={`/shipments/${trip.shipment_request_id}`}>{trip.shipment_request_id}</Link></td><td><StatusBadge status={trip.status} /></td><td>{formatDate(trip.planned_start_at)}</td></tr>)}
          </tbody></table></div> : <p>No hay viajes relacionados.</p>}</article>
          <article className="panel"><h2>Eventos</h2>{detail.events.length ? <ul>{detail.events.map((event) => <li key={event.id}>{formatDate(event.occurred_at)} · {event.summary} <small>({event.actor_type})</small></li>)}</ul> : <p>No hay eventos relacionados.</p>}</article>
        </> : null}</PageState>
    </section>
  );
}
