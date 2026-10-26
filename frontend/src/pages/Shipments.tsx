import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { DataTable, type Column } from "../components/DataTable";
import { PageState } from "../components/PageState";
import { PaginationBar } from "../components/PaginationBar";
import { StatusBadge } from "../components/StatusBadge";
import { display, formatDate, loadLabel } from "../format";
import type { CarrierListItem, ShipmentDetail, ShipmentPayload, UnassignedShipment } from "../types";

const shipmentStatuses = [
  "DRAFT",
  "INCOMPLETE",
  "PENDING_OPERATOR_REVIEW",
  "VALIDATED",
  "PUBLISHED",
  "MATCHING",
  "ASSIGNED",
  "CANCELLED",
  "CLOSED"
];

function toDateTimeLocal(value: string | null | undefined) {
  if (!value) return "";
  return value.slice(0, 16);
}

function fromDateTimeLocal(value: string) {
  return value ? new Date(value).toISOString() : null;
}

export function Shipments() {
  const [searchParams, setSearchParams] = useSearchParams();
  const limit = Number(searchParams.get("limit") || "25");
  const offset = Number(searchParams.get("offset") || "0");
  const [rows, setRows] = useState<UnassignedShipment[]>([]);
  const [total, setTotal] = useState(0);
  const [carriers, setCarriers] = useState<CarrierListItem[]>([]);
  const [selectedCarrierByShipment, setSelectedCarrierByShipment] = useState<Record<string, string>>({});
  const [busyShipmentId, setBusyShipmentId] = useState<string | null>(null);
  const [editingShipment, setEditingShipment] = useState<ShipmentDetail["shipment"] | null>(null);
  const [editForm, setEditForm] = useState<ShipmentPayload>({});
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = (options?: { preserveNotice?: boolean }) => {
    setLoading(true);
    setError(null);
    if (!options?.preserveNotice) {
      setNotice(null);
    }
    Promise.all([
      api.unassignedShipmentsPage(limit, offset),
      api.carriers({ is_validated: true, limit: 100 })
    ])
      .then(([shipmentPage, validatedCarriers]) => {
        const shipments = shipmentPage.items;
        setRows(shipments);
        setTotal(shipmentPage.total);
        setCarriers(validatedCarriers);
        setSelectedCarrierByShipment((current) => {
          const next = { ...current };
          for (const shipment of shipments) {
            if (!next[shipment.id] && validatedCarriers.length > 0) {
              next[shipment.id] = validatedCarriers[0].id;
            }
          }
          return next;
        });
      })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  };

  const changePage = (nextOffset: number, nextLimit = limit) => {
    const next = new URLSearchParams(searchParams);
    next.set("limit", String(nextLimit));
    next.set("offset", String(nextOffset));
    setSearchParams(next);
  };

  const openEditShipment = async (shipmentId: string) => {
    setBusyShipmentId(shipmentId);
    setError(null);
    setNotice(null);
    try {
      const detail = await api.shipmentDetail(shipmentId);
      const shipment = detail.shipment;
      setEditingShipment(shipment);
      setEditForm({
        status: shipment.status,
        producer_phone_number: shipment.producer_phone_number ?? "",
        origin: shipment.origin ?? "",
        destination: shipment.destination ?? "",
        cargo_category: shipment.cargo_category ?? "",
        cargo_type: shipment.cargo_type ?? "",
        quantity_unit: shipment.quantity_unit ?? "",
        livestock_type: shipment.livestock_type ?? "",
        quantity_estimate: shipment.quantity_estimate ?? "",
        weight_per_head_kg: shipment.weight_per_head_kg ?? "",
        operational_notes: shipment.operational_notes ?? "",
        date_window_start: toDateTimeLocal(shipment.date_window_start),
        date_window_end: toDateTimeLocal(shipment.date_window_end),
        requires_human_review: shipment.requires_human_review,
        has_ambiguous_location: shipment.has_ambiguous_location,
        has_estimated_values: shipment.has_estimated_values
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No pude cargar la carga.");
    } finally {
      setBusyShipmentId(null);
    }
  };

  const saveShipment = async () => {
    if (!editingShipment) return;
    setBusyShipmentId(editingShipment.id);
    setError(null);
    try {
      await api.updateShipment(editingShipment.id, {
        ...editForm,
        quantity_estimate: editForm.quantity_estimate === "" ? null : editForm.quantity_estimate,
        weight_per_head_kg: editForm.weight_per_head_kg === "" ? null : editForm.weight_per_head_kg,
        date_window_start: fromDateTimeLocal(String(editForm.date_window_start ?? "")),
        date_window_end: fromDateTimeLocal(String(editForm.date_window_end ?? ""))
      });
      setEditingShipment(null);
      setNotice(`Carga ${editingShipment.id} editada.`);
      load({ preserveNotice: true });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No pude guardar la carga.");
    } finally {
      setBusyShipmentId(null);
    }
  };

  const deleteShipment = async (shipmentId: string) => {
    if (!window.confirm(`¿Borrar la carga ${shipmentId}? Se conserva trazabilidad interna.`)) {
      return;
    }
    setBusyShipmentId(shipmentId);
    setError(null);
    setNotice(null);
    try {
      await api.deleteShipment(shipmentId);
      setNotice(`Carga ${shipmentId} borrada del backoffice.`);
      load({ preserveNotice: true });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No pude borrar la carga.");
    } finally {
      setBusyShipmentId(null);
    }
  };

  useEffect(() => { load(); }, [limit, offset]);

  const runShipmentAction = async (
    shipmentId: string,
    action: "interest" | "assign"
  ) => {
    const carrierId = selectedCarrierByShipment[shipmentId];
    if (!carrierId) {
      setError("Elegí un transportista validado antes de ejecutar la acción.");
      return;
    }
    setBusyShipmentId(shipmentId);
    setError(null);
    setNotice(null);
    try {
      if (action === "interest") {
        const result = await api.registerManualInterest(shipmentId, carrierId);
        setNotice(
          `Interés manual registrado para ${result.carrier_id}. Carrier: ${result.carrier_notification_status ?? "n/a"}. Productor: ${result.producer_notification_status ?? "n/a"}.`
        );
      } else {
        const result = await api.assignShipmentManually(shipmentId, carrierId);
        setNotice(
          `Viaje ${result.trip_id} asignado a ${result.carrier_id}. Carrier: ${result.carrier_notification_status ?? "n/a"}. Productor: ${result.producer_notification_status ?? "n/a"}.`
        );
      }
      load({ preserveNotice: true });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No pude completar la acción.");
    } finally {
      setBusyShipmentId(null);
    }
  };

  const columns: Column<UnassignedShipment>[] = [
    {
      key: "id",
      header: "ID",
      render: (row) => (
        <Link to={`/shipments/${row.id}`} className="inline-link">
          {row.id}
        </Link>
      )
    },
    { key: "origin", header: "Origen", render: (row) => display(row.origin) },
    { key: "destination", header: "Destino", render: (row) => display(row.destination) },
    { key: "cargo", header: "Carga", render: (row) => loadLabel(row) },
    { key: "status", header: "Estado", render: (row) => <StatusBadge status={row.status} /> },
    { key: "created", header: "Creada", render: (row) => formatDate(row.created_at) },
    { key: "age", header: "Antigüedad", render: (row) => `${row.age_hours} h` },
    {
      key: "offers",
      header: "Ofertas / interesados",
      render: (row) => `${row.offers_count} / ${row.interested_carriers_count}`
    },
    {
      key: "actions",
      header: "Operación",
      render: (row) => (
        <div className="shipment-actions-cell">
          <Link to={`/shipments/${row.id}`} className="secondary-link-button">
            Ver detalle
          </Link>
          <div className="shipment-actions-buttons">
            <button
              type="button"
              className="secondary-button"
              disabled={busyShipmentId === row.id}
              onClick={() => void openEditShipment(row.id)}
            >
              Editar
            </button>
            <button
              type="button"
              className="danger-button"
              disabled={busyShipmentId === row.id}
              onClick={() => void deleteShipment(row.id)}
            >
              Borrar
            </button>
          </div>
          <select
            className="text-input"
            value={selectedCarrierByShipment[row.id] ?? ""}
            onChange={(event) =>
              setSelectedCarrierByShipment((current) => ({
                ...current,
                [row.id]: event.target.value
              }))
            }
          >
            {carriers.length === 0 ? (
              <option value="">Sin transportistas validados</option>
            ) : (
              carriers.map((carrier) => (
                <option key={carrier.id} value={carrier.id}>
                  {carrier.name} ({carrier.id})
                </option>
              ))
            )}
          </select>
          <div className="shipment-actions-buttons">
            <button
              type="button"
              className="secondary-button"
              disabled={busyShipmentId === row.id || carriers.length === 0}
              onClick={() => void runShipmentAction(row.id, "interest")}
            >
              Marcar interesado
            </button>
            <button
              type="button"
              className="primary-button"
              disabled={busyShipmentId === row.id || carriers.length === 0}
              onClick={() => void runShipmentAction(row.id, "assign")}
            >
              Asignar viaje
            </button>
          </div>
        </div>
      )
    }
  ];

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>Cargas sin transportista</h1>
          <p>Cargas publicadas que todavía no tienen transportista confirmado.</p>
        </div>
        <button type="button" className="secondary-button" onClick={() => load()}>
          Actualizar
        </button>
      </header>
      {notice ? <div className="state-box">{notice}</div> : null}
      {editingShipment ? (
        <div className="panel form-panel edit-panel">
          <div className="panel-header">
            <div>
              <h2>Editar carga {editingShipment.id}</h2>
              <p className="panel-subtitle">Los cambios quedan guardados en el historial.</p>
            </div>
            <button type="button" className="secondary-button" onClick={() => setEditingShipment(null)}>
              Cerrar
            </button>
          </div>
          <div className="form-grid compact-grid">
            <label className="field">
              <span>Estado</span>
              <select
                className="text-input"
                value={editForm.status ?? ""}
                onChange={(event) => setEditForm((current) => ({ ...current, status: event.target.value }))}
              >
                {shipmentStatuses.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Teléfono productor</span>
              <input
                className="text-input"
                value={editForm.producer_phone_number ?? ""}
                onChange={(event) =>
                  setEditForm((current) => ({ ...current, producer_phone_number: event.target.value }))
                }
              />
            </label>
            <label className="field">
              <span>Origen</span>
              <input
                className="text-input"
                value={editForm.origin ?? ""}
                onChange={(event) => setEditForm((current) => ({ ...current, origin: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>Destino</span>
              <input
                className="text-input"
                value={editForm.destination ?? ""}
                onChange={(event) =>
                  setEditForm((current) => ({ ...current, destination: event.target.value }))
                }
              />
            </label>
            <label className="field">
              <span>Categoría</span>
              <select
                className="text-input"
                value={editForm.cargo_category ?? ""}
                onChange={(event) =>
                  setEditForm((current) => ({ ...current, cargo_category: event.target.value }))
                }
              >
                <option value="">Sin dato</option>
                <option value="LIVESTOCK">Hacienda</option>
                <option value="GRAIN">Granos</option>
              </select>
            </label>
            <label className="field">
              <span>Tipo de carga</span>
              <input
                className="text-input"
                value={editForm.cargo_type ?? ""}
                onChange={(event) => setEditForm((current) => ({ ...current, cargo_type: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>Unidad</span>
              <input
                className="text-input"
                value={editForm.quantity_unit ?? ""}
                onChange={(event) =>
                  setEditForm((current) => ({ ...current, quantity_unit: event.target.value }))
                }
              />
            </label>
            <label className="field">
              <span>Cantidad estimada</span>
              <input
                className="text-input"
                type="number"
                step="0.01"
                value={editForm.quantity_estimate ?? ""}
                onChange={(event) =>
                  setEditForm((current) => ({ ...current, quantity_estimate: event.target.value }))
                }
              />
            </label>
            <label className="field">
              <span>Pesaje por cabeza (kg)</span>
              <input
                className="text-input"
                type="number"
                min="0"
                step="0.01"
                value={editForm.weight_per_head_kg ?? ""}
                onChange={(event) =>
                  setEditForm((current) => ({ ...current, weight_per_head_kg: event.target.value }))
                }
              />
            </label>
            <label className="field">
              <span>Inicio ventana</span>
              <input
                className="text-input"
                type="datetime-local"
                value={String(editForm.date_window_start ?? "")}
                onChange={(event) =>
                  setEditForm((current) => ({ ...current, date_window_start: event.target.value }))
                }
              />
            </label>
            <label className="field">
              <span>Fin ventana</span>
              <input
                className="text-input"
                type="datetime-local"
                value={String(editForm.date_window_end ?? "")}
                onChange={(event) =>
                  setEditForm((current) => ({ ...current, date_window_end: event.target.value }))
                }
              />
            </label>
            <label className="field wide-field">
              <span>Notas operativas</span>
              <textarea
                className="text-input text-area"
                value={editForm.operational_notes ?? ""}
                onChange={(event) =>
                  setEditForm((current) => ({ ...current, operational_notes: event.target.value }))
                }
              />
            </label>
          </div>
          <div className="check-row">
            <label>
              <input
                type="checkbox"
                checked={Boolean(editForm.requires_human_review)}
                onChange={(event) =>
                  setEditForm((current) => ({ ...current, requires_human_review: event.target.checked }))
                }
              />
              Requiere revisión
            </label>
            <label>
              <input
                type="checkbox"
                checked={Boolean(editForm.has_ambiguous_location)}
                onChange={(event) =>
                  setEditForm((current) => ({ ...current, has_ambiguous_location: event.target.checked }))
                }
              />
              Ubicación ambigua
            </label>
            <label>
              <input
                type="checkbox"
                checked={Boolean(editForm.has_estimated_values)}
                onChange={(event) =>
                  setEditForm((current) => ({ ...current, has_estimated_values: event.target.checked }))
                }
              />
              Valores estimados
            </label>
          </div>
          <div className="panel-actions">
            <button
              type="button"
              className="primary-button"
              disabled={busyShipmentId === editingShipment.id}
              onClick={() => void saveShipment()}
            >
              Guardar cambios
            </button>
          </div>
        </div>
      ) : null}
      <PageState
        loading={loading}
        error={error}
        empty={rows.length === 0}
        emptyTitle="No hay cargas sin asignar"
        onRefresh={() => load()}
      >
        <><PaginationBar total={total} limit={limit} offset={offset} onPageChange={changePage} noun="cargas" /><DataTable columns={columns} rows={rows} getRowKey={(row) => row.id} /></>
      </PageState>
    </section>
  );
}
