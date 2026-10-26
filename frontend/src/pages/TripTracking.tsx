import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { routingApi } from "../api/client";
import { GoogleRouteMap } from "../components/GoogleRouteMap";
import { formatDate } from "../format";
import { statusLabel } from "../labels";
import type { TrackingView } from "../types";
const stages: Record<string,string> = {DEPARTURE:"Salida",MIDDLE:"Mitad",ARRIVAL:"Llegada",MANUAL:"Control manual",REQUESTED:"Solicitado",RECEIVED:"Recibido",OVERDUE:"Pendiente para soporte",CANCELLED:"Cancelado"};

export function TripTracking() {
  const {tripId = ""} = useParams();
  const [search] = useSearchParams();
  const scope = search.get("test_run_id") ?? "";
  const [data, setData] = useState<TrackingView | null>(null);
  const [key, setKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [side, setSide] = useState<string | null>(null);
  const load = useCallback(async () => { setError(null); try { setData(await routingApi.tracking(tripId,scope)); } catch(e) {setError((e as Error).message);} }, [tripId,scope]);
  useEffect(() => { let active = true; let timer: ReturnType<typeof setTimeout>; const poll = async () => { if(document.visibilityState === "visible") await load(); if(active) timer = setTimeout(() => {void poll();}, 10000); }; routingApi.config().then(c => {if(active) setKey(c.google_maps_browser_key);}).catch((e: Error) => {if(active) setError(e.message);}); void poll(); return () => {active = false; clearTimeout(timer);}; },[load]);
  const action = async (name: string) => { setBusy(true); setError(null); try {await routingApi.action(tripId,name,scope); await load();} catch(e) {setError((e as Error).message);} finally {setBusy(false);} };
  const selectPoint = useCallback((point: {lat:number;lng:number}) => {
    if (!side || !data || !window.confirm(`¿Confirmar este punto como acceso de ${side === "origin" ? "origen" : "destino"}?`)) return;
    setBusy(true);
    routingApi.setPoint(data.shipment_request_id,side,point.lat,point.lng,scope).then(() => {setSide(null);return load();}).catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  }, [side,data,scope,load]);
  const latest = data?.reports.find(r => r.id === data.tracking.latest_report_id);
  return <section className="page"><header className="page-header"><div><h1>Seguimiento del viaje</h1><p>{data ? statusLabel(data.status) : "Cargando viaje…"}{scope ? " · Escenario de prueba" : ""}</p></div><Link to="/trips">Volver a viajes</Link></header>
    {error ? <p className="state-box error" role="alert">{error}</p> : null}
    <div className="row-actions"><button className="secondary-button" onClick={() => void load()} disabled={busy}>Actualizar</button><button className="secondary-button" onClick={() => void action("confirm-driver")} disabled={busy}>Confirmar WhatsApp del chofer asignado</button><button className="secondary-button" onClick={() => void action("request-location")} disabled={busy}>Solicitar ubicación</button><button className="secondary-button" onClick={() => void action("route")} disabled={busy}>Calcular recorrido</button></div>
    {data ? <><p>{data.tracking.confirmed_at ? `Contacto confirmado: ${formatDate(data.tracking.confirmed_at)}` : "Falta confirmar el contacto del chofer."}</p>
    <div className="row-actions"><button className="secondary-button" onClick={() => setSide(side === "origin" ? null : "origin")}>Confirmar acceso de origen en mapa</button><button className="secondary-button" onClick={() => setSide(side === "destination" ? null : "destination")}>Confirmar acceso de destino en mapa</button></div>{side ? <p role="status">Tocá el mapa para indicar el acceso de {side === "origin" ? "origen" : "destino"}.</p> : null}
    <GoogleRouteMap apiKey={key} points={data.tracking.points ?? []} polyline={data.tracking.route?.polyline} latest={latest ? {lat:latest.data.latitude,lng:latest.data.longitude} : undefined} onSelect={selectPoint}/>
    <p>El trazado es orientativo. El camión representa el último punto informado, no una posición continua.</p>
    {data.tracking.route ? <p>📏 {(data.tracking.route.distance_meters/1000).toFixed(1)} km · ⏱️ {Math.round(data.tracking.route.duration_seconds/60)} minutos estimados de conducción, sin descansos.</p> : <p>{data.tracking.route_error ?? "El recorrido todavía no fue calculado."}</p>}
    {latest ? <p>📍 Última ubicación: {formatDate(latest.data.occurred_at)}</p> : null}
    <h2>Controles de ubicación</h2><table className="data-table"><thead><tr><th>Control</th><th>Estado</th><th>Solicitado</th></tr></thead><tbody>{data.checkpoints.map(c => <tr key={c.id}><td>{stages[c.data.stage] ?? "Control"}</td><td>{stages[c.status] ?? c.status}</td><td>{formatDate(c.data.requested_at)}</td></tr>)}</tbody></table>
    {!data.checkpoints.length ? <p>Todavía no hay controles de ubicación.</p> : null}
    <h2>Puntos informados</h2>{data.reports.map(p => <p key={p.id}>{formatDate(p.data.occurred_at)} · {p.data.latitude}, {p.data.longitude}{p.status === "LATE" ? " · Fuera del control vigente" : ""}</p>)}</> : null}
  </section>;
}
