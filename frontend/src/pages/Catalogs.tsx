import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { CargoCatalog, CargoCategory, CargoType, GeographicCatalogEntry } from "../types";

type GeoKind = GeographicCatalogEntry["kind"];
const kindLabel: Record<GeoKind, string> = { PROVINCE: "Provincia", DEPARTMENT: "Partido / departamento", LOCALITY: "Localidad" };
const aliases = (value: string) => value.split(",").map((part) => part.trim()).filter(Boolean);
const sourceLabel = (source: string) => source === "GEOREF"
  ? "Georef"
  : source === "JAUREGUI_LORDA"
    ? "Importación heredada · revisar"
    : "Manual";

export function Catalogs() {
  const [tab, setTab] = useState<"geography" | "cargo">("geography");
  const [admin, setAdmin] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [kind, setKind] = useState<GeoKind>("LOCALITY");
  const [search, setSearch] = useState("");
  const [parentFilter, setParentFilter] = useState("");
  const [province, setProvince] = useState("");
  const [geo, setGeo] = useState<GeographicCatalogEntry[]>([]);
  const [provinces, setProvinces] = useState<GeographicCatalogEntry[]>([]);
  const [departments, setDepartments] = useState<GeographicCatalogEntry[]>([]);
  const [showGeoForm, setShowGeoForm] = useState(false);
  const [showCategoryForm, setShowCategoryForm] = useState(false);
  const [showTypeForm, setShowTypeForm] = useState(false);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [cargo, setCargo] = useState<CargoCatalog>({ categories: [], types: [] });
  const [editingGeo, setEditingGeo] = useState<GeographicCatalogEntry | null>(null);
  const [geoForm, setGeoForm] = useState({ kind: "LOCALITY" as GeoKind, name: "", parent_id: "", aliases: "", active: true });
  const [editingCategory, setEditingCategory] = useState<CargoCategory | null>(null);
  const [categoryForm, setCategoryForm] = useState({ code: "", name: "", aliases: "", active: true });
  const [editingType, setEditingType] = useState<CargoType | null>(null);
  const [typeForm, setTypeForm] = useState({ code: "", category_code: "", name: "", aliases: "", active: true });

  const loadGeo = async () => {
    const page = await api.geographicCatalog({ kind, parent_id: parentFilter || undefined, search: search || undefined, active: null, limit: 50, offset });
    setGeo(page.items); setTotal(page.total);
  };
  const loadCargo = async () => setCargo(await api.cargoCatalog(true));
  const load = async () => {
    setError("");
    try { if (tab === "geography") await loadGeo(); else await loadCargo(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "No se pudo cargar el catálogo."); }
  };
  useEffect(() => {
    Promise.all([
      api.currentOperator(),
      api.geographicCatalog({ kind: "PROVINCE", active: true, limit: 100 }),
      api.cargoCatalog(true)
    ]).then(([operator, provincePage, cargoData]) => {
      setAdmin(operator.role === "admin"); setProvinces(provincePage.items); setCargo(cargoData);
    }).catch((reason: Error) => setError(reason.message)).finally(() => setLoading(false));
  }, []);
  useEffect(() => { if (!loading) void load(); }, [tab, kind, parentFilter, search, offset, loading]);
  useEffect(() => {
    if (geoForm.kind !== "LOCALITY" || !province) { setDepartments([]); return; }
    api.geographicCatalog({ kind: "DEPARTMENT", parent_id: province, active: true, limit: 200 })
      .then((page) => setDepartments(page.items)).catch((reason: Error) => setError(reason.message));
  }, [geoForm.kind, province]);

  const save = async (action: () => Promise<unknown>, success: string) => {
    setBusy(true); setError(""); setMessage("");
    try {
      await action(); setMessage(success); await load();
      setEditingGeo(null); setGeoForm({ kind, name: "", parent_id: "", aliases: "", active: true });
      setEditingCategory(null); setEditingType(null);
      setShowGeoForm(false); setShowCategoryForm(false); setShowTypeForm(false);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "No se pudo guardar."); }
    finally { setBusy(false); }
  };

  if (loading) return <div className="state-box">Cargando catálogos...</div>;
  return <section className="page-stack">
    <header className="page-header"><div><h1>Listas del sistema</h1><p>Localidades y tipos de carga que usa el sistema.</p></div></header>
    {error ? <div className="notice error" role="alert">{error}</div> : null}{message ? <div className="notice success" role="status">{message}</div> : null}
    <div className="tabs"><button className={tab === "geography" ? "tab active" : "tab"} onClick={() => setTab("geography")}>📍 Provincias, partidos y localidades</button><button className={tab === "cargo" ? "tab active" : "tab"} onClick={() => setTab("cargo")}>📦 Categorías y tipos de carga</button></div>
    {tab === "geography" ? <>
      <div className="panel filter-bar">
        <label className="field"><span>Tipo</span><select className="text-input" value={kind} onChange={(event) => { setKind(event.target.value as GeoKind); setParentFilter(""); setOffset(0); }}>
          {Object.entries(kindLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select></label>
        {kind !== "PROVINCE" ? <label className="field"><span>Provincia</span><select className="text-input" value={parentFilter} onChange={(event) => { setParentFilter(event.target.value); setOffset(0); }}><option value="">Todas</option>{provinces.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label> : null}
        <label className="field"><span>Buscar</span><input className="text-input" value={search} onChange={(event) => { setSearch(event.target.value); setOffset(0); }} /></label>
        {admin ? <button className="primary-button" onClick={() => { setEditingGeo(null); setGeoForm({ kind, name: "", parent_id: "", aliases: "", active: true }); setProvince(parentFilter); setShowGeoForm(true); }}>＋ Agregar</button> : null}
      </div>
      {admin && showGeoForm ? <form className="panel form-grid" onSubmit={(event) => {
        event.preventDefault();
        const payload = { kind: geoForm.kind, name: geoForm.name, parent_id: geoForm.parent_id || null, aliases: aliases(geoForm.aliases) };
        if (editingGeo) void save(() => api.updateGeographicEntry(editingGeo.id, { name: payload.name, aliases: payload.aliases, active: geoForm.active }), "Entrada actualizada.");
        else void save(() => api.createGeographicEntry(payload), "Entrada agregada.");
      }}>
        <h2>{editingGeo ? "Editar entrada" : "Nueva entrada"}</h2>
        {!editingGeo ? <label className="field"><span>Tipo</span><select className="text-input" value={geoForm.kind} onChange={(event) => setGeoForm({ ...geoForm, kind: event.target.value as GeoKind, parent_id: "" })}>{Object.entries(kindLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label> : null}
        {!editingGeo && geoForm.kind === "PROVINCE" ? null : !editingGeo && geoForm.kind === "DEPARTMENT" ? <label className="field"><span>Provincia</span><select className="text-input" required value={geoForm.parent_id} onChange={(event) => setGeoForm({ ...geoForm, parent_id: event.target.value })}><option value="">Elegí provincia</option>{provinces.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label> : null}
        {!editingGeo && geoForm.kind === "LOCALITY" ? <><label className="field"><span>Provincia</span><select className="text-input" required value={province} onChange={(event) => { setProvince(event.target.value); setGeoForm({ ...geoForm, parent_id: event.target.value }); }}><option value="">Elegí provincia</option>{provinces.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label className="field"><span>Partido / departamento (opcional)</span><select className="text-input" value={geoForm.parent_id || province} onChange={(event) => setGeoForm({ ...geoForm, parent_id: event.target.value || province })}><option value={province}>Sin partido específico</option>{departments.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label></> : null}
        <label className="field"><span>Nombre</span><input className="text-input" required value={geoForm.name} onChange={(event) => setGeoForm({ ...geoForm, name: event.target.value })} /></label>
        <label className="field"><span>Alias separados por coma</span><input className="text-input" value={geoForm.aliases} onChange={(event) => setGeoForm({ ...geoForm, aliases: event.target.value })} /></label>
        {editingGeo ? <label className="checkbox-field"><input type="checkbox" checked={geoForm.active} onChange={(event) => setGeoForm({ ...geoForm, active: event.target.checked })} /> Activa</label> : null}
        <div className="form-actions"><button className="primary-button" disabled={busy}>Guardar</button><button type="button" className="secondary-button" onClick={() => { setEditingGeo(null); setShowGeoForm(false); setGeoForm({ kind, name: "", parent_id: "", aliases: "", active: true }); }}>Cancelar</button></div>
      </form> : null}
      <div className="panel table-panel"><div className="panel-heading"><h2>{kindLabel[kind]}</h2><span>{total} registros</span></div><div className="table-wrap">
        <table className="data-table"><thead><tr><th>Nombre</th><th>Superior</th><th>Alias</th><th>Fuente</th><th>Estado</th>{admin ? <th /> : null}</tr></thead><tbody>
          {geo.map((row) => <tr key={row.id}><td>{row.name}</td><td>{row.parent_name || "—"}</td><td>{row.aliases.join(", ") || "—"}</td><td>{sourceLabel(row.source)}</td><td>{row.active ? "Activa" : "Inactiva"}</td>{admin ? <td><button className="text-button" onClick={() => { setEditingGeo(row); setGeoForm({ kind: row.kind, name: row.name, parent_id: row.parent_id || "", aliases: row.aliases.join(", "), active: row.active }); setShowGeoForm(true); setProvince(row.kind === "LOCALITY" ? (row.parent_id || "") : ""); }}>Editar</button></td> : null}</tr>)}
          {!geo.length ? <tr><td colSpan={admin ? 6 : 5}>No hay registros para estos filtros.</td></tr> : null}</tbody></table></div>
        <div className="pagination-actions"><button className="secondary-button" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 50))}>Anterior</button><span>{total ? offset + 1 : 0}–{Math.min(offset + geo.length, total)} de {total}</span><button className="secondary-button" disabled={offset + 50 >= total} onClick={() => setOffset(offset + 50)}>Siguiente</button></div>
      </div>
    </> : <div className="catalog-columns">
      <div className="panel table-panel"><div className="panel-heading"><h2>Categorías</h2>{admin ? <button className="primary-button" onClick={() => { setEditingCategory(null); setCategoryForm({ code: "", name: "", aliases: "", active: true }); setShowCategoryForm(true); }}>＋ Nueva</button> : null}</div>
        {admin && showCategoryForm ? <form className="compact-form" onSubmit={(event) => { event.preventDefault(); const payload = { name: categoryForm.name, aliases: aliases(categoryForm.aliases), active: categoryForm.active }; void save(() => editingCategory ? api.updateCargoCategory(editingCategory.code, payload) : api.createCargoCategory({ ...payload, code: categoryForm.code.toUpperCase(), sort_order: 0 }), "Categoría guardada."); }}>
          {!editingCategory ? <label className="field"><span>Código</span><input className="text-input" required pattern="[A-Z][A-Z0-9_]*" value={categoryForm.code} onChange={(event) => setCategoryForm({ ...categoryForm, code: event.target.value.toUpperCase() })} /></label> : <strong>{editingCategory.code}</strong>}
          <label className="field"><span>Nombre</span><input className="text-input" required value={categoryForm.name} onChange={(event) => setCategoryForm({ ...categoryForm, name: event.target.value })} /></label><label className="field"><span>Alias</span><input className="text-input" value={categoryForm.aliases} onChange={(event) => setCategoryForm({ ...categoryForm, aliases: event.target.value })} /></label><label className="checkbox-field"><input type="checkbox" checked={categoryForm.active} onChange={(event) => setCategoryForm({ ...categoryForm, active: event.target.checked })} /> Activa</label><button className="primary-button" disabled={busy}>Guardar</button><button type="button" className="secondary-button" onClick={() => { setEditingCategory(null); setShowCategoryForm(false); setCategoryForm({ code: "", name: "", aliases: "", active: true }); }}>Cancelar</button>
        </form> : null}
        <div className="table-wrap"><table className="data-table"><thead><tr><th>Código</th><th>Nombre</th><th>Estado</th>{admin ? <th /> : null}</tr></thead><tbody>{cargo.categories.map((row) => <tr key={row.code}><td>{row.code}</td><td>{row.name}</td><td>{row.active ? "Activa" : "Inactiva"}</td>{admin ? <td><button className="text-button" onClick={() => { setEditingCategory(row); setCategoryForm({ code: row.code, name: row.name, aliases: row.aliases.join(", "), active: row.active }); setShowCategoryForm(true); }}>Editar</button></td> : null}</tr>)}</tbody></table></div>
      </div>
      <div className="panel table-panel"><div className="panel-heading"><h2>Tipos de carga</h2>{admin ? <button className="primary-button" onClick={() => { setEditingType(null); setTypeForm({ code: "", category_code: cargo.categories[0]?.code || "", name: "", aliases: "", active: true }); setShowTypeForm(true); }}>＋ Nuevo</button> : null}</div>
        {admin && showTypeForm ? <form className="compact-form" onSubmit={(event) => { event.preventDefault(); const payload = { category_code: typeForm.category_code, name: typeForm.name, aliases: aliases(typeForm.aliases), active: typeForm.active }; void save(() => editingType ? api.updateCargoType(editingType.code, payload) : api.createCargoType({ ...payload, code: typeForm.code.toLowerCase().replace(/\s+/g, "_"), sort_order: 0 }), "Tipo de carga guardado."); }}>
          {!editingType ? <label className="field"><span>Código</span><input className="text-input" required pattern="[a-z][a-z0-9_]*" value={typeForm.code} onChange={(event) => setTypeForm({ ...typeForm, code: event.target.value.toLowerCase().replace(/\s+/g, "_") })} /></label> : <strong>{editingType.code}</strong>}
          <label className="field"><span>Categoría</span><select className="text-input" value={typeForm.category_code} onChange={(event) => setTypeForm({ ...typeForm, category_code: event.target.value })}>{cargo.categories.filter((row) => row.active).map((row) => <option key={row.code} value={row.code}>{row.name}</option>)}</select></label><label className="field"><span>Nombre</span><input className="text-input" required value={typeForm.name} onChange={(event) => setTypeForm({ ...typeForm, name: event.target.value })} /></label><label className="field"><span>Alias</span><input className="text-input" value={typeForm.aliases} onChange={(event) => setTypeForm({ ...typeForm, aliases: event.target.value })} /></label><label className="checkbox-field"><input type="checkbox" checked={typeForm.active} onChange={(event) => setTypeForm({ ...typeForm, active: event.target.checked })} /> Activo</label><button className="primary-button" disabled={busy}>Guardar</button><button type="button" className="secondary-button" onClick={() => { setEditingType(null); setShowTypeForm(false); setTypeForm({ code: "", category_code: "", name: "", aliases: "", active: true }); }}>Cancelar</button>
        </form> : null}
        <div className="table-wrap"><table className="data-table"><thead><tr><th>Tipo</th><th>Categoría</th><th>Alias</th><th>Estado</th>{admin ? <th /> : null}</tr></thead><tbody>{cargo.types.map((row) => <tr key={row.code}><td>{row.name}</td><td>{row.category_name}</td><td>{row.aliases.join(", ") || "—"}</td><td>{row.active ? "Activo" : "Inactivo"}</td>{admin ? <td><button className="text-button" onClick={() => { setEditingType(row); setTypeForm({ code: row.code, category_code: row.category_code, name: row.name, aliases: row.aliases.join(", "), active: row.active }); setShowTypeForm(true); }}>Editar</button></td> : null}</tr>)}</tbody></table></div>
      </div>
    </div>}
    {!admin ? <p className="muted-note">Solo un administrador puede modificar estos catálogos.</p> : null}
  </section>;
}
