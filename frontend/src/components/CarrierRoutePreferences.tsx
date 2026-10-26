import { useCallback, useEffect, useState } from "react";
import { routingApi } from "../api/client";
import type { RoutePreferenceData, RoutePreferenceInput, RoutingRow } from "../types";
const empty: RoutePreferenceInput = {origin:"",destination:"",stops:[],cargo_categories:[],equipment_types:[],opt_in:false,active:true};
export function CarrierRoutePreferences({carrierId, scope = ""}: {carrierId: string; scope?: string}) {
  const [context,setContext] = useState(scope);
  const [items,setItems] = useState<RoutingRow<RoutePreferenceData>[]>([]);
  const [form,setForm] = useState<RoutePreferenceInput | null>(null);
  const [editing,setEditing] = useState<string | undefined>();
  const [error,setError] = useState<string | null>(null);
  const [busy,setBusy] = useState(false);
  const [stops,setStops] = useState("");
  const load = useCallback(() => routingApi.preferences(carrierId,context).then(p => setItems(p.items)).catch((e: Error) => setError(e.message)),[carrierId,context]);
  useEffect(() => {void load();},[load]);
  const edit = (row?: RoutingRow<RoutePreferenceData>) => {
    setEditing(row?.id);setError(null);
    setStops(row?.data.points.slice(1,-1).map(p=>p.label).join("; ") ?? "");
    setForm(row ? {origin:row.data.points[0].label,destination:row.data.points[row.data.points.length-1]?.label ?? "",stops:[],cargo_categories:row.data.cargo_categories,equipment_types:row.data.equipment_types,opt_in:row.data.opt_in,active:row.status === "ACTIVE"} : {...empty});
  };
  const save = async () => {
    if(!form) return;
    setBusy(true);setError(null);
    try {await routingApi.savePreference(carrierId,{...form,stops:stops.split(";").map(s=>s.trim()).filter(Boolean)},context,editing);setForm(null);await load();} catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  };
  return <section className="panel wide"><div className="panel-header"><h2>Rutas habituales</h2><button className="secondary-button" onClick={()=>edit()}>Agregar ruta</button></div>
    <p>Rutas que suele hacer para recibir oportunidades. No confirman un viaje.</p>
    {import.meta.env.VITE_SHOW_QA_FIELDS === "true" ? <label>Escenario QA<input className="text-input" value={context} onChange={e=>{setContext(e.target.value);setForm(null);}} /></label> : null}{error ? <p role="alert" className="state-box error">{error}</p>:null}
    {!items.length ? <p>No hay recorridos habituales declarados en este contexto.</p> : <ul>{items.map(r=><li key={r.id}>{r.data.points.map(p=>p.label).join(" → ")} · {r.status === "ACTIVE" ? "Activo" : "Pausado"} · Avisos {r.data.opt_in ? "habilitados" : "deshabilitados"} <button className="secondary-button" onClick={()=>edit(r)}>Editar</button></li>)}</ul>}
    {form ? <form onSubmit={e=>{e.preventDefault();void save();}}><div className="form-grid">
      <label className="field">Origen, localidad y provincia<input className="text-input" required value={form.origin} onChange={e=>setForm({...form,origin:e.target.value})}/></label>
      <label className="field">Destino, localidad y provincia<input className="text-input" required value={form.destination} onChange={e=>setForm({...form,destination:e.target.value})}/></label>
      <label className="field">Paradas en orden, separadas por punto y coma<input className="text-input" value={stops} onChange={e=>setStops(e.target.value)}/></label>
      <label className="field">Equipo<input className="text-input" value={form.equipment_types.join(", ")} onChange={e=>setForm({...form,equipment_types:e.target.value.split(",").map(s=>s.trim()).filter(Boolean)})}/></label>
      <label className="field">Categoría<select className="text-input" required value={form.cargo_categories[0] ?? ""} onChange={e=>setForm({...form,cargo_categories:[e.target.value]})}><option value="">Elegir categoría</option><option value="LIVESTOCK">Hacienda</option><option value="GRAIN">Granos</option></select></label>
      <label><input type="checkbox" checked={form.opt_in} onChange={e=>setForm({...form,opt_in:e.target.checked})}/>Autoriza recibir oportunidades compatibles</label>
      <label><input type="checkbox" checked={form.active} onChange={e=>setForm({...form,active:e.target.checked})}/>Recorrido activo</label>
    </div><div className="row-actions"><button className="primary-button" type="submit" disabled={busy}>Guardar recorrido</button><button className="secondary-button" type="button" onClick={()=>{if(window.confirm("¿Descartar los cambios del recorrido?")) setForm(null);}}>Cancelar</button></div></form> : null}
  </section>;
}
