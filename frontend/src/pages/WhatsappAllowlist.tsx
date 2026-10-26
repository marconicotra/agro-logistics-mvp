import { useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import { DataTable, type Column } from "../components/DataTable";
import { PageState } from "../components/PageState";
import { StatusBadge } from "../components/StatusBadge";
import { display, formatDate } from "../format";
import type { WhatsappAllowlistContact, WhatsappAllowlistPayload } from "../types";
import { statusLabel } from "../labels";

const EMPTY_FORM: WhatsappAllowlistPayload = {
  phone_number: "",
  label: "",
  environment: "staging",
  provider: "kapso",
  status: "ACTIVE",
  notes: ""
};

export function WhatsappAllowlist() {
  const [rows, setRows] = useState<WhatsappAllowlistContact[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [environmentFilter, setEnvironmentFilter] = useState("");
  const [providerFilter, setProviderFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<WhatsappAllowlistPayload>(EMPTY_FORM);
  const formDisclosureRef = useRef<HTMLDetailsElement>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    api
      .whatsappAllowlist({
        status: statusFilter || undefined,
        environment: environmentFilter || undefined,
        provider: providerFilter || undefined,
        search: search || undefined,
        limit: 100
      })
      .then(setRows)
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, [statusFilter, environmentFilter, providerFilter, search]);

  const runAction = async (action: () => Promise<unknown>, successMessage: string) => {
    setBusy(true);
    setFeedback(null);
    setError(null);
    try {
      await action();
      setFeedback(successMessage);
      await api
        .whatsappAllowlist({
          status: statusFilter || undefined,
          environment: environmentFilter || undefined,
          provider: providerFilter || undefined,
          search: search || undefined,
          limit: 100
        })
        .then(setRows);
      setForm(EMPTY_FORM);
      setEditingId(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Acción fallida");
    } finally {
      setBusy(false);
    }
  };

  const submitForm = () => {
    const payload = {
      ...form,
      label: emptyToNull(form.label),
      notes: emptyToNull(form.notes)
    };
    const action = editingId
      ? () => api.updateWhatsappAllowlistContact(editingId, payload)
      : () => api.createWhatsappAllowlistContact(payload);
    void runAction(action, editingId ? "Número actualizado" : "Número agregado");
  };

  const startEdit = (row: WhatsappAllowlistContact) => {
    if (formDisclosureRef.current) formDisclosureRef.current.open = true;
    setEditingId(row.id);
    setForm({
      phone_number: row.phone_number,
      label: row.label ?? "",
      environment: row.environment,
      provider: row.provider,
      status: row.status,
      notes: row.notes ?? ""
    });
  };

  const blockRow = (row: WhatsappAllowlistContact) => {
    const reason = window.prompt("Motivo de bloqueo");
    if (!reason) return;
    void runAction(() => api.blockWhatsappAllowlistContact(row.id, reason), "Número bloqueado");
  };

  const reactivateRow = (row: WhatsappAllowlistContact) => {
    void runAction(() => api.reactivateWhatsappAllowlistContact(row.id), "Número reactivado");
  };

  const disableRow = (row: WhatsappAllowlistContact) => {
    void runAction(() => api.disableWhatsappAllowlistContact(row.id), "Número deshabilitado");
  };

  const columns: Column<WhatsappAllowlistContact>[] = [
    { key: "phone", header: "Teléfono", render: (row) => row.phone_number },
    { key: "normalized", header: "Normalizado", render: (row) => row.normalized_phone_number },
    { key: "label", header: "Label", render: (row) => display(row.label) },
    { key: "environment", header: "Ambiente", render: (row) => row.environment },
    { key: "provider", header: "Provider", render: (row) => row.provider },
    { key: "status", header: "Estado", render: (row) => <StatusBadge status={row.status} /> },
    { key: "notes", header: "Notas", render: (row) => display(row.notes) },
    { key: "created", header: "Alta", render: (row) => formatDate(row.created_at) },
    { key: "updated", header: "Actualizado", render: (row) => formatDate(row.updated_at) },
    {
      key: "actions",
      header: "Acciones",
      render: (row) => (
        <div className="row-actions">
          <button type="button" className="small-button" disabled={busy} onClick={() => startEdit(row)}>
            Editar
          </button>
          <button type="button" className="small-button" disabled={busy} onClick={() => blockRow(row)}>
            Bloquear
          </button>
          <button type="button" className="small-button" disabled={busy} onClick={() => reactivateRow(row)}>
            Reactivar
          </button>
          <button type="button" className="small-button danger" disabled={busy} onClick={() => disableRow(row)}>
            Deshabilitar
          </button>
        </div>
      )
    }
  ];

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>Números autorizados</h1>
          <p>Solo estos números pueden usar el asistente en este entorno.</p>
        </div>
        <button type="button" className="secondary-button" onClick={load}>
          Actualizar
        </button>
      </header>

      {feedback ? <div className="feedback">{feedback}</div> : null}

      <div className="toolbar">
        <input
          className="text-input search-input"
          value={searchInput}
          onChange={(event) => setSearchInput(event.target.value)}
          placeholder="Buscar por teléfono o descripción"
        />
        <select className="text-input" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
          <option value="">Todos los estados</option>
          <option value="ACTIVE">{statusLabel("ACTIVE")}</option>
          <option value="BLOCKED">{statusLabel("BLOCKED")}</option>
          <option value="DISABLED">{statusLabel("DISABLED")}</option>
        </select>
        <select
          className="text-input"
          value={environmentFilter}
          onChange={(event) => setEnvironmentFilter(event.target.value)}
        >
          <option value="">Todos los ambientes</option>
          <option value="local">Local</option>
          <option value="staging">Pruebas</option>
          <option value="production">Producción</option>
          <option value="all">Todos</option>
        </select>
        <select
          className="text-input"
          value={providerFilter}
          onChange={(event) => setProviderFilter(event.target.value)}
        >
          <option value="">Todos los canales</option>
          <option value="kapso">Kapso</option>
          <option value="whatsapp">WhatsApp</option>
          <option value="all">Todos</option>
        </select>
        <button type="button" className="secondary-button" onClick={() => setSearch(searchInput.trim())}>
          Buscar
        </button>
      </div>

      <details className="panel form-disclosure" ref={formDisclosureRef}>
        <summary>＋ {editingId ? "Editar número autorizado" : "Agregar número autorizado"}</summary>
        <div className="disclosure-body">
        <h2>{editingId ? "Editar número" : "Nuevo número autorizado"}</h2>
        <div className="form-grid compact-grid">
          <label className="field">
            <span>Teléfono</span>
            <input
              className="text-input"
              value={form.phone_number}
              onChange={(event) => setForm((current) => ({ ...current, phone_number: event.target.value }))}
            />
          </label>
          <label className="field">
            <span>Descripción</span>
            <input
              className="text-input"
              value={form.label ?? ""}
              onChange={(event) => setForm((current) => ({ ...current, label: event.target.value }))}
            />
          </label>
          <label className="field">
            <span>Ambiente</span>
            <select
              className="text-input"
              value={form.environment}
              onChange={(event) => setForm((current) => ({ ...current, environment: event.target.value }))}
            >
              <option value="local">Local</option>
              <option value="staging">Pruebas</option>
              <option value="production">Producción</option>
              <option value="all">Todos</option>
            </select>
          </label>
          <label className="field">
            <span>Canal</span>
            <select
              className="text-input"
              value={form.provider}
              onChange={(event) => setForm((current) => ({ ...current, provider: event.target.value }))}
            >
              <option value="kapso">Kapso</option>
              <option value="whatsapp">WhatsApp</option>
              <option value="all">Todos</option>
            </select>
          </label>
          <label className="field">
            <span>Estado</span>
            <select
              className="text-input"
              value={form.status}
              onChange={(event) => setForm((current) => ({ ...current, status: event.target.value }))}
            >
              <option value="ACTIVE">{statusLabel("ACTIVE")}</option>
              <option value="BLOCKED">{statusLabel("BLOCKED")}</option>
              <option value="DISABLED">{statusLabel("DISABLED")}</option>
            </select>
          </label>
          <label className="field field-wide">
            <span>Notas</span>
            <textarea
              className="text-input text-area"
              value={form.notes ?? ""}
              onChange={(event) => setForm((current) => ({ ...current, notes: event.target.value }))}
            />
          </label>
        </div>
        <div className="panel-actions">
          <button type="button" className="primary-button" disabled={busy} onClick={submitForm}>
            {editingId ? "Guardar cambios" : "Agregar número"}
          </button>
          {editingId ? (
            <button
              type="button"
              className="secondary-button"
              disabled={busy}
              onClick={() => {
                setEditingId(null);
                setForm(EMPTY_FORM);
              }}
            >
              Cancelar
            </button>
          ) : null}
        </div>
        </div>
      </details>

      <PageState
        loading={loading}
        error={error}
        empty={rows.length === 0}
        emptyTitle="No hay números cargados"
        onRefresh={load}
      >
        <DataTable columns={columns} rows={rows} getRowKey={(row) => row.id} />
      </PageState>
    </section>
  );
}

function emptyToNull(value: string | null): string | null {
  if (value === null) return null;
  const cleaned = value.trim();
  return cleaned || null;
}
