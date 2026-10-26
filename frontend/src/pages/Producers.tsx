import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { DataTable, type Column } from "../components/DataTable";
import { PageState } from "../components/PageState";
import { PaginationBar } from "../components/PaginationBar";
import { display, formatDate } from "../format";
import type { ProducerListItem } from "../types";

export function Producers() {
  const [rows, setRows] = useState<ProducerListItem[]>([]);
  const [searchParams, setSearchParams] = useSearchParams();
  const search = searchParams.get("search") ?? "";
  const limit = Number(searchParams.get("limit") || "25");
  const offset = Number(searchParams.get("offset") || "0");
  const [total, setTotal] = useState(0);
  const [searchInput, setSearchInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    api.producersPage(search, limit, offset).then((page) => { setRows(page.items); setTotal(page.total); }).catch((reason: Error) => setError(reason.message)).finally(() => setLoading(false));
  };

  useEffect(load, [search, limit, offset]);
  useEffect(() => setSearchInput(search), [search]);

  const changePage = (nextOffset: number, nextLimit = limit) => {
    const next = new URLSearchParams(searchParams);
    next.set("limit", String(nextLimit)); next.set("offset", String(nextOffset));
    setSearchParams(next);
  };

  const submitSearch = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSearchParams({ search: searchInput.trim(), limit: "25", offset: "0" });
  };

  const columns: Column<ProducerListItem>[] = [
    { key: "name", header: "Productor", render: (row) => row.name },
    { key: "phone", header: "Teléfono", render: (row) => display(row.phone) },
    { key: "validation", header: "Perfil", render: (row) => row.is_validated ? "Validado" : "Declarado" },
    { key: "loads", header: "Cargas", render: (row) => `${row.active_shipments_count} activas / ${row.shipments_count}` },
    { key: "trips", header: "Viajes", render: (row) => String(row.trips_count) },
    { key: "conversations", header: "Conversaciones", render: (row) => String(row.conversations_count) },
    { key: "activity", header: "Última actividad", render: (row) => formatDate(row.last_activity_at) },
    { key: "action", header: "", render: (row) => <Link className="inline-link" to={`/producers/${row.id}`}>Ver ficha</Link> }
  ];

  return (
    <section className="page">
      <header className="page-header">
        <div><h1>Productores</h1><p>Buscá un productor para ver sus cargas y viajes.</p></div>
        <button type="button" className="secondary-button" onClick={load}>Actualizar</button>
      </header>
      <form className="toolbar" onSubmit={submitSearch}>
        <input className="text-input search-input" value={searchInput} onChange={(event) => setSearchInput(event.target.value)} placeholder="Buscar por nombre o teléfono" />
        <button type="submit" className="secondary-button">Buscar</button>
        <button type="button" className="secondary-button" onClick={() => { setSearchInput(""); setSearchParams({ limit: "25", offset: "0" }); }}>Limpiar</button>
      </form>
      <PageState loading={loading} error={error} empty={!rows.length} emptyTitle="No hay productores registrados" onRefresh={load}>
        <><PaginationBar total={total} limit={limit} offset={offset} onPageChange={changePage} noun="productores" /><DataTable columns={columns} rows={rows} getRowKey={(row) => row.id} /></>
      </PageState>
    </section>
  );
}
