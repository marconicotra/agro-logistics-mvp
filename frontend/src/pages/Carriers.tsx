import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { DataTable, type Column } from "../components/DataTable";
import { PageState } from "../components/PageState";
import { StatusBadge } from "../components/StatusBadge";
import { PaginationBar } from "../components/PaginationBar";
import { display, formatDate } from "../format";
import type { CarrierListItem } from "../types";

type CarrierFilterKey = "ALL" | "PENDING" | "REVIEW" | "APPROVED" | "REJECTED" | "SUSPENDED";

const FILTERS: Array<{ key: CarrierFilterKey; label: string; validationStatus?: string }> = [
  { key: "ALL", label: "Todos" },
  { key: "PENDING", label: "Pendientes" },
  { key: "REVIEW", label: "En revisión" },
  { key: "APPROVED", label: "Validados", validationStatus: "APPROVED" },
  { key: "REJECTED", label: "Rechazados", validationStatus: "REJECTED" },
  { key: "SUSPENDED", label: "Suspendidos", validationStatus: "SUSPENDED" }
];

export function Carriers() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [rows, setRows] = useState<CarrierListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const requestedFilter = searchParams.get("filter");
  const limit = Number(searchParams.get("limit") || "25");
  const offset = Number(searchParams.get("offset") || "0");
  const activeFilter: CarrierFilterKey = ["PENDING", "REVIEW", "APPROVED", "REJECTED", "SUSPENDED"].includes(requestedFilter ?? "") ? requestedFilter as CarrierFilterKey : "ALL";

  const currentFilter = useMemo(
    () => FILTERS.find((item) => item.key === activeFilter) ?? FILTERS[0],
    [activeFilter]
  );

  const load = () => {
    setLoading(true);
    setError(null);
    api
      .carriersPage({
        search: search || undefined,
        validation_status: activeFilter === "PENDING" ? undefined : currentFilter.validationStatus,
        pending_only: activeFilter === "PENDING" ? true : undefined,
        onboarding_pending_only: activeFilter === "REVIEW" ? true : undefined,
        limit,
        offset
      })
      .then((page) => { setRows(page.items); setTotal(page.total); })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, [activeFilter, search, limit, offset]);

  const changePage = (nextOffset: number, nextLimit = limit) => {
    const next = new URLSearchParams(searchParams);
    next.set("limit", String(nextLimit));
    next.set("offset", String(nextOffset));
    setSearchParams(next);
  };

  const columns: Column<CarrierListItem>[] = [
    { key: "name", header: "Nombre", render: (row) => row.name },
    { key: "phone", header: "Teléfono", render: (row) => display(row.phone) },
    { key: "email", header: "Correo electrónico", render: (row) => display(row.email) },
    { key: "company", header: "Empresa", render: (row) => display(row.company_name) },
    { key: "cuit", header: "CUIT", render: (row) => display(row.cuit) },
    {
      key: "validation",
      header: "Validación",
      render: (row) => <StatusBadge status={row.validation_status} />
    },
    {
      key: "onboarding",
      header: "Alta",
      render: (row) => <StatusBadge status={row.onboarding_status} />
    },
    {
      key: "missing",
      header: "Faltantes",
      render: (row) => display(row.missing_fields)
    },
    {
      key: "vehicles",
      header: "Vehículos",
      render: (row) => `${row.vehicles_count} / ${display(row.truck_count)}`
    },
    {
      key: "documents",
      header: "Docs pendientes",
      render: (row) => `${row.pending_documents_count} / ${row.documents_count}`
    },
    { key: "created", header: "Alta", render: (row) => formatDate(row.created_at) },
    {
      key: "action",
      header: "Perfil",
      render: (row) => (
        <Link className="inline-link" to={`/carriers/${row.id}`}>
          Ver detalle
        </Link>
      )
    }
  ];

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>Transportistas</h1>
          <p>Buscá transportistas y revisá sus datos.</p>
        </div>
        <div className="header-actions">
          <button type="button" className="secondary-button" onClick={load}>
            Actualizar
          </button>
          <Link className="primary-link-button" to="/carriers/new">
            Nuevo transportista
          </Link>
        </div>
      </header>

      <div className="filters">
        {FILTERS.map((filter) => (
          <button
            key={filter.key}
            type="button"
            className={`filter-button ${activeFilter === filter.key ? "active" : ""}`}
            onClick={() => setSearchParams(filter.key === "ALL" ? {} : { filter: filter.key })}
          >
            {filter.label}
          </button>
        ))}
      </div>

      <form
        className="toolbar"
        onSubmit={(event) => {
          event.preventDefault();
          setSearch(searchInput.trim());
          changePage(0);
        }}
      >
        <input
          className="text-input search-input"
          value={searchInput}
          onChange={(event) => setSearchInput(event.target.value)}
          placeholder="Nombre, empresa, CUIT o patente"
        />
        <button type="submit" className="secondary-button">
          Buscar
        </button>
        <button
          type="button"
          className="secondary-button"
          onClick={() => {
            setSearchInput("");
            setSearch("");
          }}
        >
          Limpiar
        </button>
      </form>

      <PageState
        loading={loading}
        error={error}
        empty={rows.length === 0}
        emptyTitle="No hay transportistas para este filtro"
        onRefresh={load}
      >
        <>
          <PaginationBar total={total} limit={limit} offset={offset} onPageChange={changePage} noun="transportistas" />
          <DataTable className="carrier-list" columns={columns} rows={rows} getRowKey={(row) => row.id} />
        </>
      </PageState>
    </section>
  );
}
