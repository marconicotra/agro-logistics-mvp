import { useEffect, useState } from "react";

import { api } from "../api/client";
import { DataTable, type Column } from "../components/DataTable";
import { MetricCard } from "../components/MetricCard";
import { PageState } from "../components/PageState";
import { StatusBadge } from "../components/StatusBadge";
import { display, formatDate } from "../format";
import type { NotificationOutboxItem, NotificationOutboxPage } from "../types";

const PAGE_SIZE = 50;
const FILTERS = [
  { value: "", label: "Todos" },
  { value: "PENDING", label: "Pendientes" },
  { value: "RETRY", label: "Reintento" },
  { value: "RECONCILE_REQUIRED", label: "Conciliación" },
  { value: "FAILED", label: "Fallidos" },
  { value: "CANCELLED", label: "Cancelados" },
  { value: "CONFIGURATION_MISMATCH", label: "Cuenta cambiada" },
  { value: "ACCEPTED", label: "Aceptados" }
];

function notificationTypeLabel(value: string | null): string {
  const labels: Record<string, string> = {
    CONVERSATION_REPLY: "Respuesta de conversación",
    NEW_LOAD_ALERT: "Nueva carga",
    REMINDER: "Recordatorio",
    MANUAL_MESSAGE: "Mensaje manual",
    TRIP_PLANNED: "Viaje planificado"
  };
  return value ? labels[value] ?? value : "-";
}

export function NotificationOutbox() {
  const [page, setPage] = useState<NotificationOutboxPage | null>(null);
  const [filter, setFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);

  const load = () => {
    setLoading(true);
    setError(null);
    api
      .notificationOutbox(filter || undefined, PAGE_SIZE, offset)
      .then(setPage)
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, [filter, offset]);
  useEffect(() => {
    api.currentOperator().then((operator) => setIsAdmin(operator.role === "admin")).catch(() => setIsAdmin(false));
  }, []);

  const reconcile = async (row: NotificationOutboxItem, resolution: "ACCEPTED" | "RETRY_NOT_SENT") => {
    const evidence = window.prompt("Referencia del registro que verificaste en Kapso (sin pegar mensajes ni secretos):");
    if (!evidence) return;
    if (resolution === "RETRY_NOT_SENT" && !window.confirm("Confirmaste que Kapso no aceptó el envío. ¿Autorizar un nuevo intento?")) return;
    setActionError(null);
    try {
      await api.reconcileNotification(row.id, resolution, evidence.trim());
      load();
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "No se pudo conciliar el envío");
    }
  };

  const columns: Column<NotificationOutboxItem>[] = [
    { key: "status", header: "Estado", render: (row) => <StatusBadge status={row.status} /> },
    { key: "type", header: "Aviso", render: (row) => notificationTypeLabel(row.notification_type) },
    {
      key: "entity",
      header: "Operación",
      render: (row) => [row.entity_type, row.entity_id].filter(Boolean).join(" · ") || "-"
    },
    { key: "provider", header: "Proveedor", render: (row) => row.provider },
    { key: "attempts", header: "Intentos", render: (row) => row.attempts },
    { key: "created", header: "Creado", render: (row) => formatDate(row.created_at) },
    { key: "available", header: "Próximo intento", render: (row) => formatDate(row.available_at) },
    { key: "error", header: "Código de error", render: (row) => display(row.last_error_code) },
    {
      key: "reconcile",
      header: "Conciliar",
      render: (row) => isAdmin && row.status === "RECONCILE_REQUIRED" ? <div className="row-actions">
        <button type="button" className="small-button" onClick={() => reconcile(row, "ACCEPTED")}>Kapso aceptó</button>
        <button type="button" className="small-button danger" onClick={() => reconcile(row, "RETRY_NOT_SENT")}>No se envió</button>
      </div> : "-"
    }
  ];

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>Notificaciones</h1>
          <p>Estado del despacho de avisos salientes. No muestra teléfonos ni el contenido de los mensajes.</p>
        </div>
        <button type="button" className="secondary-button" onClick={load}>
          Actualizar
        </button>
      </header>

      <div className="state-box outbox-guidance">
        Los avisos pendientes necesitan el worker activo. Los casos de conciliación requieren verificar Kapso
        antes de tomar una decisión; esta pantalla no reenvía mensajes.
      </div>
      {actionError ? <div className="state-box error-feedback">{actionError}</div> : null}

      <div className="metric-grid outbox-metrics">
        <MetricCard label="Pendientes" value={page?.counts.PENDING ?? 0} />
        <MetricCard label="Reintentos" value={page?.counts.RETRY ?? 0} />
        <MetricCard label="Conciliación manual" value={page?.counts.RECONCILE_REQUIRED ?? 0} />
        <MetricCard label="Fallidos" value={page?.counts.FAILED ?? 0} />
        <MetricCard label="Cuenta cambiada" value={page?.counts.CONFIGURATION_MISMATCH ?? 0} />
      </div>

      <div className="filters" role="group" aria-label="Filtrar notificaciones por estado">
        {FILTERS.map((item) => (
          <button
            key={item.value || "ALL"}
            type="button"
            className={`filter-button ${filter === item.value ? "active" : ""}`}
            onClick={() => {
              setFilter(item.value);
              setOffset(0);
            }}
          >
            {item.label}
          </button>
        ))}
      </div>

      <PageState
        loading={loading}
        error={error}
        empty={!page || page.items.length === 0}
        emptyTitle="No hay notificaciones para este filtro"
        onRefresh={load}
      >
        <DataTable columns={columns} rows={page?.items ?? []} getRowKey={(row) => row.id} />
        <div className="outbox-pagination">
          <span>
            {offset + 1}–{Math.min(offset + PAGE_SIZE, page?.total ?? 0)} de {page?.total ?? 0}
          </span>
          <div className="header-actions">
            <button
              type="button"
              className="secondary-button"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              Anterior
            </button>
            <button
              type="button"
              className="secondary-button"
              disabled={offset + PAGE_SIZE >= (page?.total ?? 0)}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Siguiente
            </button>
          </div>
        </div>
      </PageState>
    </section>
  );
}
