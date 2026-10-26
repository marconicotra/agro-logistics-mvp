import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { DataTable, type Column } from "../components/DataTable";
import { PageState } from "../components/PageState";
import { StatusBadge } from "../components/StatusBadge";
import { PaginationBar } from "../components/PaginationBar";
import { display, formatDate } from "../format";
import type { OpenConversation } from "../types";
import { entityLabel } from "../labels";

export function Conversations() {
  const [searchParams, setSearchParams] = useSearchParams();
  const needsOperator = searchParams.get("needs_operator") === "true";
  const ambiguousOnly = searchParams.get("ambiguous") === "true";
  const limit = Number(searchParams.get("limit") || "25");
  const offset = Number(searchParams.get("offset") || "0");
  const [rows, setRows] = useState<OpenConversation[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    api
      .openConversationsPage({ limit, offset, needsOperator: needsOperator || undefined, ambiguousOnly: ambiguousOnly || undefined })
      .then((page) => { setRows(page.items); setTotal(page.total); })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, [needsOperator, ambiguousOnly, limit, offset]);

  const changePage = (nextOffset: number, nextLimit = limit) => {
    const next = new URLSearchParams(searchParams);
    next.set("limit", String(nextLimit));
    next.set("offset", String(nextOffset));
    setSearchParams(next);
  };

  const columns: Column<OpenConversation>[] = [
    {
      key: "id",
      header: "Conversación",
      render: (row) => <Link className="inline-link" to={`/conversations/${encodeURIComponent(row.id)}`}>Abrir chat →</Link>
    },
    { key: "participant", header: "Contacto", render: (row) => display(row.participant_phone) },
    { key: "channel", header: "Canal", render: (row) => entityLabel(row.channel) },
    { key: "message", header: "Último mensaje", render: (row) => display(row.last_message_preview) },
    { key: "activity", header: "Última actividad", render: (row) => formatDate(row.last_activity_at) },
    { key: "status", header: "Estado", render: (row) => <StatusBadge status={row.status} /> },
    {
      key: "handoff",
      header: "Soporte",
      render: (row) => (row.needs_operator ? <StatusBadge status="REQUIERE_OPERADOR" /> : "-")
    },
    {
      key: "related",
      header: "Relacionado",
      render: (row) =>
        row.related_entity_type && row.related_entity_id
          ? `${entityLabel(row.related_entity_type)}: ${row.related_entity_id}`
          : "-"
    }
  ];

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>{ambiguousOnly ? "Ubicaciones por revisar" : needsOperator ? "Conversaciones para revisar" : "Conversaciones abiertas"}</h1>
          <p>Chats recientes. Abrí uno para ver qué pasó.</p>
        </div>
        <button type="button" className="secondary-button" onClick={load}>
          Actualizar
        </button>
      </header>
      <PageState
        loading={loading}
        error={error}
        empty={rows.length === 0}
        emptyTitle="No hay conversaciones abiertas"
        onRefresh={load}
      >
        <>
          <PaginationBar total={total} limit={limit} offset={offset} onPageChange={changePage} noun="conversaciones" />
          <DataTable columns={columns} rows={rows} getRowKey={(row) => row.id} />
        </>
      </PageState>
    </section>
  );
}
