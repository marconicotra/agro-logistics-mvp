import { useEffect, useState } from "react";
import { routingApi } from "../api/client";
import { formatDate } from "../format";
type Dispatch = Awaited<ReturnType<typeof routingApi.dispatch>>;
const labels: Record<string,string> = {AVAILABILITY:"Disponibilidad concreta",PREFERENCE:"Recorrido habitual",QUEUED:"Encolado",ACCEPTED:"Aceptado por proveedor",FAILED:"Falló el aviso",EXCLUDED:"No seleccionado",REVIEW:"Requiere revisión",RECONCILE_REQUIRED:"Pendiente de conciliación",CONFIGURATION_MISMATCH:"Cuenta del canal cambiada",PENDING:"Programada",DONE:"Ejecutada",CANCELLED:"Cancelada",compatible_declared_segment:"Tramo declarado compatible",no_compatible_declared_route:"Sin recorrido declarado compatible",outside_qa_participant:"Fuera del participante QA",missing_contact:"Sin contacto válido",geography_unresolved:"Geografía pendiente",date_unresolved:"Fecha pendiente",cargo_unresolved:"Tipo de carga pendiente",shipment_expired:"Ventana de carga vencida",not_approved:"Sin aprobación"};
export function ShipmentDispatch({shipmentId,scope=""}: {shipmentId:string;scope?:string}) {
 const [editing,setEditing]=useState(false);const [equipment,setEquipment]=useState("");
 const [data,setData]=useState<Dispatch|null>(null);const [error,setError]=useState<string|null>(null);
 useEffect(()=>{let active=true;routingApi.dispatch(shipmentId,scope).then(d=>{if(active)setData(d);}).catch((e:Error)=>{if(active)setError(e.message);});return()=>{active=false;};},[shipmentId,scope]);
 return <section className="panel"><h2>Difusión por recorrido</h2>
 <p>Equipo requerido: {data?.equipment_type ?? "A confirmar"}</p><button className="secondary-button" onClick={()=>{setEquipment(data?.equipment_type??"");setEditing(!editing);}}>Editar equipo requerido</button>
 {editing ? <form onSubmit={e=>{e.preventDefault();routingApi.setRequirements(shipmentId,equipment,scope).then(()=>routingApi.dispatch(shipmentId,scope)).then(d=>{setData(d);setEditing(false);}).catch((err:Error)=>setError(err.message));}}><label>Equipo declarado<input className="text-input" value={equipment} onChange={e=>setEquipment(e.target.value)}/></label><button className="primary-button" type="submit">Guardar requisito</button></form>:null}
{error ? <p role="alert">{error}</p>:null}
 {data?.decisions.length ? <table className="data-table"><thead><tr><th>Transportista</th><th>Etapa</th><th>Resultado</th><th>Motivo</th></tr></thead><tbody>{data.decisions.map(d=><tr key={d.id}><td>{d.data.carrier_id ? <a href={`/carriers/${d.data.carrier_id}`}>Ver transportista</a>:"—"}</td><td>{labels[d.data.stage??""]??"—"}</td><td>{labels[d.status]??"Pendiente"}</td><td>{labels[d.data.reason]??d.data.reason}</td></tr>)}</tbody></table>:<p>Todavía no hay decisiones de difusión registradas para esta carga.</p>}
 {data?.jobs.filter(j=>j.data.action==="EXPAND").map(j=><p key={j.id}>Ampliación a recorridos habituales: {labels[j.status]??"Pendiente"} · {formatDate(j.due_at)}</p>)}
 </section>;
}
