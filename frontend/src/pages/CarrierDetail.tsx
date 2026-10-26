import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { CarrierRoutePreferences } from "../components/CarrierRoutePreferences";
import { api } from "../api/client";
import { DataTable, type Column } from "../components/DataTable";
import { PageState } from "../components/PageState";
import { StatusBadge } from "../components/StatusBadge";
import { display, formatDate } from "../format";
import type {
  CarrierDetail as CarrierDetailType,
  CarrierDriver,
  CarrierDocument,
  CarrierPayload,
  CarrierVehicle,
  DocumentPayload,
  VehiclePayload
} from "../types";

const EMPTY_CARRIER_FORM: CarrierPayload = {
  name: "",
  phone: "",
  email: "",
  company_name: "",
  cuit: "",
  truck_count: null,
  truck_types: [],
  truck_body_type: ""
};

const EMPTY_VEHICLE_FORM: VehiclePayload = {
  plate_number: "",
  vehicle_type: "",
  body_type: "",
  capacity: "",
  status: "ACTIVE"
};

const EMPTY_DOCUMENT_FORM: DocumentPayload = {
  document_type: "",
  entity_type: "carrier",
  entity_id: null,
  external_uri: "",
  file_name: "",
  mime_type: "",
  notes: "",
  valid_from: "",
  expires_at: "",
  supersedes_document_id: null
};

export function CarrierDetail() {
  const { carrierId } = useParams();
  const [detail, setDetail] = useState<CarrierDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editingCarrier, setEditingCarrier] = useState(false);
  const [carrierForm, setCarrierForm] = useState<CarrierPayload>(EMPTY_CARRIER_FORM);
  const [carrierTruckTypesInput, setCarrierTruckTypesInput] = useState("");
  const [vehicleForm, setVehicleForm] = useState<VehiclePayload>(EMPTY_VEHICLE_FORM);
  const [driverForm, setDriverForm] = useState({ name: "", phone: "", license_category: "" });
  const [editingVehicleId, setEditingVehicleId] = useState<string | null>(null);
  const [documentForm, setDocumentForm] = useState<DocumentPayload>(EMPTY_DOCUMENT_FORM);
  const [editingDocumentId, setEditingDocumentId] = useState<string | null>(null);

  const syncCarrierForm = (payload: CarrierDetailType) => {
    setCarrierForm({
      name: payload.carrier.name,
      phone: payload.carrier.normalized_phone_number ?? payload.carrier.contact_phone ?? "",
      email: payload.carrier.email ?? "",
      company_name: payload.carrier.company_name ?? "",
      cuit: payload.carrier.cuit ?? "",
      truck_count: payload.carrier.truck_count ?? null,
      truck_types: payload.carrier.truck_types,
      truck_body_type: payload.carrier.truck_body_type ?? ""
    });
    setCarrierTruckTypesInput(payload.carrier.truck_types.join(", "));
  };

  const load = () => {
    if (!carrierId) return;
    setLoading(true);
    setLoadError(null);
    api
      .carrierDetail(carrierId)
      .then((payload) => {
        setDetail(payload);
        syncCarrierForm(payload);
      })
      .catch((reason: Error) => setLoadError(reason.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, [carrierId]);

  const runAction = async (action: () => Promise<unknown>, successMessage: string) => {
    setBusy(true);
    setActionError(null);
    setFeedback(null);
    try {
      await action();
      setFeedback(successMessage);
      await api.carrierDetail(carrierId ?? "").then((payload) => {
        setDetail(payload);
        syncCarrierForm(payload);
      });
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Acción fallida");
    } finally {
      setBusy(false);
    }
  };

  const carrierStatus = detail?.carrier.validation_status ?? "DRAFT";
  const allDocuments = detail
    ? [
        ...detail.documents,
        ...detail.drivers.flatMap((driver) => driver.documents ?? []),
        ...detail.vehicles.flatMap((vehicle) => vehicle.documents ?? [])
      ]
    : [];

  const documentColumns: Column<CarrierDocument>[] = [
    {
      key: "owner",
      header: "Asociado a",
      render: (row) =>
        row.entity_type === "carrier"
          ? "Transportista"
          : row.entity_type === "driver"
            ? detail?.drivers.find((driver) => driver.id === row.entity_id)?.name ?? "Conductor"
            : detail?.vehicles.find((vehicle) => vehicle.id === row.entity_id)?.plate_number ?? "Vehículo"
    },
    { key: "type", header: "Tipo", render: (row) => row.document_type },
    { key: "file", header: "Archivo", render: (row) => <DocumentLink carrierId={carrierId ?? ""} document={row} /> },
    { key: "mime", header: "MIME", render: (row) => display(row.mime_type) },
    { key: "provider", header: "Provider", render: (row) => display(row.provider) },
    { key: "status", header: "Estado", render: (row) => <StatusBadge status={row.status} /> },
    { key: "validity", header: "Vigencia", render: (row) => row.expires_at ?? "Sin fecha informada" },
    { key: "notes", header: "Notas", render: (row) => display(row.notes) },
    {
      key: "actions",
      header: "Acciones",
      render: (row) => (
        <div className="row-actions">
          <button type="button" className="small-button" disabled={busy} onClick={() => startDocumentEdit(row)}>
            Editar
          </button>
          {row.status === "PENDING" ? (
            <>
              <button type="button" className="small-button" disabled={busy} onClick={() => approveDocument(row.id)}>
                Aprobar
              </button>
              <button
                type="button"
                className="small-button danger"
                disabled={busy}
                onClick={() => rejectDocument(row.id)}
              >
                Rechazar
              </button>
            </>
          ) : null}
        </div>
      )
    }
  ];

  const vehicleColumns = useMemo<Column<CarrierVehicle>[]>(
    () => [
      { key: "plate", header: "Patente", render: (row) => display(row.plate_number) },
      { key: "type", header: "Tipo", render: (row) => display(row.vehicle_type) },
      { key: "body", header: "Carrocería", render: (row) => display(row.body_type) },
      { key: "capacity", header: "Capacidad", render: (row) => display(row.capacity_estimate) },
      { key: "status", header: "Estado", render: (row) => <StatusBadge status={row.status} /> },
      { key: "review", header: "Homologación", render: (row) => <StatusBadge status={row.validation_status} /> },
      {
        key: "actions",
        header: "Acciones",
        render: (row) => (
          <div className="row-actions">
            <button type="button" className="small-button" disabled={busy} onClick={() => startVehicleEdit(row)}>
              Editar
            </button>
            {row.validation_status !== "APPROVED" ? (
              <button
                type="button"
                className="small-button"
                disabled={busy}
                onClick={() => approveVehicle(row.id)}
              >
                Aprobar unidad
              </button>
            ) : null}
            <button
              type="button"
              className="small-button danger"
              disabled={busy}
              onClick={() => deleteVehicle(row.id)}
            >
              Desactivar
            </button>
          </div>
        )
      }
    ],
    [busy]
  );

  const approveCarrier = () => {
    if (!carrierId) return;
    void runAction(() => api.approveCarrier(carrierId, "Aprobado desde backoffice"), "Transportista aprobado");
  };

  const approveVehicle = (vehicleId: string) => {
    if (!carrierId) return;
    const notes = window.prompt("Dejá constancia de qué documentación de la unidad revisaste");
    if (!notes?.trim()) return;
    void runAction(
      () => api.approveCarrierVehicle(carrierId, vehicleId, notes),
      "Unidad aprobada para operar"
    );
  };

  const approveDriver = (driverId: string) => {
    if (!carrierId) return;
    const notes = window.prompt("Dejá constancia de qué datos y documentación del conductor revisaste");
    if (!notes?.trim()) return;
    void runAction(
      () => api.approveCarrierDriver(carrierId, driverId, notes),
      "Conductor aprobado para operar"
    );
  };

  const rejectDriver = (driverId: string) => {
    if (!carrierId) return;
    const reason = window.prompt("Motivo de rechazo del conductor");
    if (!reason) return;
    void runAction(() => api.rejectCarrierDriver(carrierId, driverId, reason), "Conductor rechazado");
  };

  const addDriver = () => {
    if (!carrierId) return;
    void runAction(
      () => api.createCarrierDriver(carrierId, {
        name: driverForm.name,
        phone: emptyToNull(driverForm.phone),
        license_category: emptyToNull(driverForm.license_category)
      }),
      "Conductor agregado"
    );
    setDriverForm({ name: "", phone: "", license_category: "" });
  };

  const driverColumns: Column<CarrierDriver>[] = [
    { key: "name", header: "Conductor", render: (row) => row.name },
    { key: "phone", header: "Teléfono", render: (row) => display(row.phone) },
    { key: "license", header: "Categoría licencia", render: (row) => display(row.license_category) },
    { key: "review", header: "Revisión", render: (row) => <StatusBadge status={row.validation_status} /> },
    {
      key: "actions",
      header: "Acciones",
      render: (row) => (
        <div className="row-actions">
          {row.validation_status !== "APPROVED" ? (
            <button type="button" className="small-button" disabled={busy} onClick={() => approveDriver(row.id)}>
              Aprobar
            </button>
          ) : null}
          {row.validation_status !== "REJECTED" ? (
            <button type="button" className="small-button danger" disabled={busy} onClick={() => rejectDriver(row.id)}>
              Rechazar
            </button>
          ) : null}
        </div>
      )
    }
  ];

  const rejectCarrier = () => {
    if (!carrierId) return;
    const reason = window.prompt("Motivo de rechazo");
    if (!reason) return;
    void runAction(() => api.rejectCarrier(carrierId, reason), "Transportista rechazado");
  };

  const suspendCarrier = () => {
    if (!carrierId) return;
    const reason = window.prompt("Motivo de suspensión");
    if (!reason) return;
    void runAction(() => api.suspendCarrier(carrierId, reason), "Transportista suspendido");
  };

  const markCarrierInReview = () => {
    if (!carrierId) return;
    const notes = window.prompt("Notas para volver a revisión") ?? "";
    void runAction(() => api.markCarrierInReview(carrierId, notes), "Transportista enviado a revisión");
  };

  const saveCarrier = () => {
    if (!carrierId) return;
    void runAction(
      () =>
        api.updateCarrier(carrierId, {
          ...carrierForm,
          phone: emptyToNull(carrierForm.phone),
          email: emptyToNull(carrierForm.email),
          company_name: emptyToNull(carrierForm.company_name),
          cuit: emptyToNull(carrierForm.cuit),
          truck_count: carrierForm.truck_count ?? null,
          truck_types: parseCommaList(carrierTruckTypesInput),
          truck_body_type: emptyToNull(carrierForm.truck_body_type)
        }),
      "Datos del transportista actualizados"
    );
    setEditingCarrier(false);
  };

  const startVehicleEdit = (vehicle: CarrierVehicle) => {
    setEditingVehicleId(vehicle.id);
    setVehicleForm({
      plate_number: vehicle.plate_number ?? "",
      vehicle_type: vehicle.vehicle_type ?? "",
      body_type: vehicle.body_type ?? "",
      capacity: vehicle.capacity_estimate ? String(vehicle.capacity_estimate) : "",
      status: vehicle.status
    });
  };

  const resetVehicleForm = () => {
    setEditingVehicleId(null);
    setVehicleForm(EMPTY_VEHICLE_FORM);
  };

  const saveVehicle = () => {
    if (!carrierId) return;
    const payload = {
      ...vehicleForm,
      plate_number: emptyToNull(vehicleForm.plate_number),
      vehicle_type: emptyToNull(vehicleForm.vehicle_type),
      body_type: emptyToNull(vehicleForm.body_type),
      capacity: emptyToNull(vehicleForm.capacity),
      status: emptyToNull(vehicleForm.status)
    };
    const action = editingVehicleId
      ? () => api.updateVehicle(carrierId, editingVehicleId, payload)
      : () => api.createVehicle(carrierId, payload);
    void runAction(action, editingVehicleId ? "Vehículo actualizado" : "Vehículo agregado");
    resetVehicleForm();
  };

  const deleteVehicle = (vehicleId: string) => {
    if (!carrierId) return;
    void runAction(() => api.deleteVehicle(carrierId, vehicleId), "Vehículo desactivado");
  };

  const startDocumentEdit = (document: CarrierDocument) => {
    setEditingDocumentId(document.id);
    setDocumentForm({
      document_type: document.document_type,
      entity_type: document.entity_type,
      entity_id: document.entity_id,
      external_uri: "",
      file_name: document.file_name ?? "",
      mime_type: document.mime_type ?? "",
      notes: document.notes ?? "",
      valid_from: document.valid_from ?? "",
      expires_at: document.expires_at ?? "",
      supersedes_document_id: document.supersedes_document_id ?? null
    });
  };

  const resetDocumentForm = () => {
    setEditingDocumentId(null);
    setDocumentForm(EMPTY_DOCUMENT_FORM);
  };

  const saveDocument = () => {
    if (!carrierId) return;
    const payload = {
      ...documentForm,
      external_uri: emptyToNull(documentForm.external_uri),
      file_name: emptyToNull(documentForm.file_name),
      mime_type: emptyToNull(documentForm.mime_type),
      notes: emptyToNull(documentForm.notes),
      valid_from: emptyToNull(documentForm.valid_from ?? ""),
      expires_at: emptyToNull(documentForm.expires_at ?? ""),
      supersedes_document_id: documentForm.supersedes_document_id ?? null
    };
    const action = editingDocumentId
      ? () => api.updateCarrierDocument(carrierId, editingDocumentId, payload)
      : () => api.createCarrierDocument(carrierId, payload);
    void runAction(action, editingDocumentId ? "Documento actualizado" : "Documento agregado");
    resetDocumentForm();
  };

  const approveDocument = (documentId: string) => {
    if (!carrierId) return;
    void runAction(() => api.approveDocument(carrierId, documentId, "Documento aprobado"), "Documento aprobado");
  };

  const rejectDocument = (documentId: string) => {
    if (!carrierId) return;
    const reason = window.prompt("Motivo de rechazo del documento");
    if (!reason) return;
    void runAction(() => api.rejectDocument(carrierId, documentId, reason), "Documento rechazado");
  };

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <Link className="inline-link" to="/carriers">
            Volver a transportistas
          </Link>
          <h1>Detalle de transportista</h1>
          <p>{carrierId}</p>
        </div>
        <button type="button" className="secondary-button" onClick={load}>
          Actualizar
        </button>
      </header>

      {feedback ? <div className="feedback">{feedback}</div> : null}
      {actionError ? <div className="feedback error-feedback">{actionError}</div> : null}

      <PageState
        loading={loading}
        error={loadError}
        empty={!detail}
        emptyTitle="No se encontró el transportista"
        onRefresh={load}
      >
        {detail ? (
          <div className="detail-grid">
            <section className="panel">
              <div className="panel-header">
                <h2>Datos del transportista</h2>
                <div className="panel-header-actions">
                  <StatusBadge status={detail.carrier.validation_status} />
                  <button
                    type="button"
                    className="small-button"
                    disabled={busy}
                    onClick={() => setEditingCarrier((current) => !current)}
                  >
                    {editingCarrier ? "Cancelar edición" : "Editar datos"}
                  </button>
                </div>
              </div>
              {editingCarrier ? (
                <div className="form-grid compact-grid">
                  <label className="field">
                    <span>Nombre</span>
                    <input
                      className="text-input"
                      value={carrierForm.name}
                      onChange={(event) =>
                        setCarrierForm((current) => ({ ...current, name: event.target.value }))
                      }
                    />
                  </label>
                  <label className="field">
                    <span>Teléfono</span>
                    <input
                      className="text-input"
                      value={carrierForm.phone ?? ""}
                      onChange={(event) =>
                        setCarrierForm((current) => ({ ...current, phone: event.target.value }))
                      }
                    />
                  </label>
                  <label className="field">
                    <span>Email</span>
                    <input
                      className="text-input"
                      value={carrierForm.email ?? ""}
                      onChange={(event) =>
                        setCarrierForm((current) => ({ ...current, email: event.target.value }))
                      }
                    />
                  </label>
                  <label className="field">
                    <span>Empresa</span>
                    <input
                      className="text-input"
                      value={carrierForm.company_name ?? ""}
                      onChange={(event) =>
                        setCarrierForm((current) => ({ ...current, company_name: event.target.value }))
                      }
                    />
                  </label>
                  <label className="field">
                    <span>CUIT</span>
                    <input
                      className="text-input"
                      value={carrierForm.cuit ?? ""}
                      onChange={(event) =>
                        setCarrierForm((current) => ({ ...current, cuit: event.target.value }))
                      }
                    />
                  </label>
                  <label className="field">
                    <span>Cantidad camiones</span>
                    <input
                      className="text-input"
                      type="number"
                      min="0"
                      value={carrierForm.truck_count ?? ""}
                      onChange={(event) =>
                        setCarrierForm((current) => ({
                          ...current,
                          truck_count: event.target.value ? Number(event.target.value) : null
                        }))
                      }
                    />
                  </label>
                  <label className="field">
                    <span>Tipos de camión</span>
                    <input
                      className="text-input"
                      value={carrierTruckTypesInput}
                      onChange={(event) => setCarrierTruckTypesInput(event.target.value)}
                    />
                  </label>
                  <label className="field">
                    <span>Carrocería / jaula</span>
                    <input
                      className="text-input"
                      value={carrierForm.truck_body_type ?? ""}
                      onChange={(event) =>
                        setCarrierForm((current) => ({ ...current, truck_body_type: event.target.value }))
                      }
                    />
                  </label>
                  <div className="panel-actions form-actions-full">
                    <button type="button" className="primary-button" disabled={busy} onClick={saveCarrier}>
                      Guardar cambios
                    </button>
                  </div>
                </div>
              ) : (
                <dl className="detail-list">
                  <Detail label="Nombre" value={detail.carrier.name} />
                  <Detail
                    label="Teléfono"
                    value={detail.carrier.normalized_phone_number ?? detail.carrier.contact_phone}
                  />
                  <Detail label="Email" value={detail.carrier.email} />
                  <Detail label="Empresa" value={detail.carrier.company_name} />
                  <Detail label="CUIT" value={detail.carrier.cuit} />
                  <Detail label="Cantidad camiones" value={detail.carrier.truck_count} />
                  <Detail label="Tipos camiones" value={detail.carrier.truck_types} />
                  <Detail label="Carrocería / jaula" value={detail.carrier.truck_body_type} />
                  <Detail label="Actualizado" value={formatDate(detail.carrier.updated_at)} />
                </dl>
              )}
            </section>

            <section className="panel">
              <div className="panel-header">
                <h2>Homologación</h2>
                <StatusBadge status={detail.onboarding.status} />
              </div>
              <dl className="detail-list">
                <Detail label="Paso actual de WhatsApp" value={captureStepLabel(detail.capture_progress.step)} />
                <Detail
                  label="Unidades cargadas / declaradas"
                  value={`${detail.capture_progress.captured_vehicle_count} / ${detail.capture_progress.declared_vehicle_count}`}
                />
                <Detail label="Datos requeridos" value={detail.onboarding.required_fields} />
                <Detail label="Datos faltantes" value={detail.onboarding.missing_fields} />
                <Detail label="Enviado" value={formatDate(detail.onboarding.submitted_at)} />
                <Detail label="Revisado" value={formatDate(detail.onboarding.reviewed_at)} />
                <Detail label="Motivo de rechazo" value={detail.onboarding.rejection_reason} />
              </dl>
              <div className="panel-actions">
                <button type="button" className="primary-button" disabled={busy} onClick={approveCarrier}>
                  Aprobar transportista
                </button>
                <button type="button" className="danger-button" disabled={busy} onClick={rejectCarrier}>
                  Rechazar transportista
                </button>
                {carrierStatus === "APPROVED" ? (
                  <button type="button" className="secondary-button" disabled={busy} onClick={suspendCarrier}>
                    Suspender
                  </button>
                ) : (
                  <button type="button" className="secondary-button" disabled={busy} onClick={markCarrierInReview}>
                    Marcar en revisión
                  </button>
                )}
              </div>
            </section>

            {carrierId ? <CarrierRoutePreferences carrierId={carrierId} /> : null}
            <section className="panel wide">
              <div className="panel-header">
                <h2>Vehículos</h2>
                <button type="button" className="small-button" disabled={busy} onClick={resetVehicleForm}>
                  Nuevo vehículo
                </button>
              </div>
              {detail.vehicles.length ? (
                <DataTable rows={detail.vehicles} getRowKey={(row) => row.id} columns={vehicleColumns} />
              ) : (
                <div className="state-box">No hay vehículos cargados</div>
              )}
              <div className="form-grid compact-grid">
                <label className="field">
                  <span>Patente</span>
                  <input
                    className="text-input"
                    value={vehicleForm.plate_number ?? ""}
                    onChange={(event) =>
                      setVehicleForm((current) => ({ ...current, plate_number: event.target.value }))
                    }
                  />
                </label>
                <label className="field">
                  <span>Tipo</span>
                  <input
                    className="text-input"
                    value={vehicleForm.vehicle_type ?? ""}
                    onChange={(event) =>
                      setVehicleForm((current) => ({ ...current, vehicle_type: event.target.value }))
                    }
                  />
                </label>
                <label className="field">
                  <span>Carrocería</span>
                  <input
                    className="text-input"
                    value={vehicleForm.body_type ?? ""}
                    onChange={(event) =>
                      setVehicleForm((current) => ({ ...current, body_type: event.target.value }))
                    }
                  />
                </label>
                <label className="field">
                  <span>Capacidad</span>
                  <input
                    className="text-input"
                    value={vehicleForm.capacity ?? ""}
                    onChange={(event) =>
                      setVehicleForm((current) => ({ ...current, capacity: event.target.value }))
                    }
                  />
                </label>
                <label className="field">
                  <span>Estado</span>
                  <select
                    className="text-input"
                    value={vehicleForm.status ?? "ACTIVE"}
                    onChange={(event) =>
                      setVehicleForm((current) => ({ ...current, status: event.target.value }))
                    }
                  >
                    <option value="ACTIVE">ACTIVE</option>
                    <option value="MAINTENANCE">MAINTENANCE</option>
                    <option value="INACTIVE">INACTIVE</option>
                  </select>
                </label>
                <div className="panel-actions form-actions-full">
                  <button type="button" className="primary-button" disabled={busy} onClick={saveVehicle}>
                    {editingVehicleId ? "Guardar vehículo" : "Agregar vehículo"}
                  </button>
                  {editingVehicleId ? (
                    <button type="button" className="secondary-button" disabled={busy} onClick={resetVehicleForm}>
                      Cancelar
                    </button>
                  ) : null}
                </div>
              </div>
            </section>

            <section className="panel wide">
              <div className="panel-header">
                <h2>Conductores</h2>
                <span>La aprobación es individual y no se hereda al resto de la flota.</span>
              </div>
              {detail.drivers.length ? (
                <DataTable rows={detail.drivers} getRowKey={(row) => row.id} columns={driverColumns} />
              ) : (
                <div className="state-box">No hay conductores cargados</div>
              )}
              <div className="form-grid compact-grid">
                <label className="field">
                  <span>Nombre y apellido</span>
                  <input
                    className="text-input"
                    value={driverForm.name}
                    onChange={(event) => setDriverForm((current) => ({ ...current, name: event.target.value }))}
                  />
                </label>
                <label className="field">
                  <span>Teléfono</span>
                  <input
                    className="text-input"
                    value={driverForm.phone}
                    onChange={(event) => setDriverForm((current) => ({ ...current, phone: event.target.value }))}
                  />
                </label>
                <label className="field">
                  <span>Categoría de licencia</span>
                  <input
                    className="text-input"
                    value={driverForm.license_category}
                    onChange={(event) =>
                      setDriverForm((current) => ({ ...current, license_category: event.target.value }))
                    }
                  />
                </label>
                <div className="panel-actions form-actions-full">
                  <button
                    type="button"
                    className="primary-button"
                    disabled={busy || !driverForm.name.trim()}
                    onClick={addDriver}
                  >
                    Agregar conductor
                  </button>
                </div>
              </div>
            </section>

            <section className="panel wide">
              <div className="panel-header">
                <h2>Documentos</h2>
                <button type="button" className="small-button" disabled={busy} onClick={resetDocumentForm}>
                  Nuevo documento
                </button>
              </div>
              {allDocuments.length ? (
                <DataTable rows={allDocuments} getRowKey={(row) => row.id} columns={documentColumns} />
              ) : (
                <div className="state-box">No hay documentos cargados</div>
              )}
              <div className="form-grid compact-grid">
                <label className="field">
                  <span>Asociar a</span>
                  <select
                    className="text-input"
                    value={`${documentForm.entity_type}:${documentForm.entity_id ?? carrierId ?? ""}`}
                    disabled={Boolean(editingDocumentId)}
                    onChange={(event) => {
                      const [entity_type, entity_id] = event.target.value.split(":", 2) as [
                        "carrier" | "driver" | "vehicle",
                        string
                      ];
                      setDocumentForm((current) => ({ ...current, entity_type, entity_id }));
                    }}
                  >
                    <option value={`carrier:${carrierId ?? ""}`}>Transportista</option>
                    {detail.drivers.map((driver) => (
                      <option key={driver.id} value={`driver:${driver.id}`}>Conductor · {driver.name}</option>
                    ))}
                    {detail.vehicles.map((vehicle) => (
                      <option key={vehicle.id} value={`vehicle:${vehicle.id}`}>
                        Unidad · {vehicle.plate_number ?? vehicle.id}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>Tipo documento</span>
                  <input
                    className="text-input"
                    value={documentForm.document_type}
                    onChange={(event) =>
                      setDocumentForm((current) => ({ ...current, document_type: event.target.value }))
                    }
                  />
                </label>
                <label className="field">
                  <span>URL externa</span>
                  <input
                    className="text-input"
                    value={documentForm.external_uri ?? ""}
                    onChange={(event) =>
                      setDocumentForm((current) => ({ ...current, external_uri: event.target.value }))
                    }
                  />
                </label>
                <label className="field">
                  <span>Nombre archivo</span>
                  <input
                    className="text-input"
                    value={documentForm.file_name ?? ""}
                    onChange={(event) =>
                      setDocumentForm((current) => ({ ...current, file_name: event.target.value }))
                    }
                  />
                </label>
                <label className="field">
                  <span>Válido desde (declarado)</span>
                  <input className="text-input" type="date" value={documentForm.valid_from ?? ""} onChange={(event) => setDocumentForm((current) => ({ ...current, valid_from: event.target.value || null }))} />
                </label>
                <label className="field">
                  <span>Vence el (declarado)</span>
                  <input className="text-input" type="date" value={documentForm.expires_at ?? ""} onChange={(event) => setDocumentForm((current) => ({ ...current, expires_at: event.target.value || null }))} />
                </label>
                <label className="field">
                  <span>Renueva documento anterior</span>
                  <select
                    className="text-input"
                    value={documentForm.supersedes_document_id ?? ""}
                    onChange={(event) => setDocumentForm((current) => ({ ...current, supersedes_document_id: event.target.value || null }))}
                  >
                    <option value="">Sin vínculo de renovación</option>
                    {allDocuments
                      .filter((item) => item.id !== editingDocumentId
                        && item.entity_type === documentForm.entity_type
                        && item.entity_id === (documentForm.entity_id ?? carrierId))
                      .map((item) => <option key={item.id} value={item.id}>{item.document_type} · {item.id}</option>)}
                  </select>
                </label>
                <label className="field">
                  <span>Tipo de archivo (MIME)</span>
                  <input
                    className="text-input"
                    value={documentForm.mime_type ?? ""}
                    onChange={(event) =>
                      setDocumentForm((current) => ({ ...current, mime_type: event.target.value }))
                    }
                  />
                </label>
                <label className="field field-wide">
                  <span>Notas</span>
                  <textarea
                    className="text-input text-area"
                    value={documentForm.notes ?? ""}
                    onChange={(event) =>
                      setDocumentForm((current) => ({ ...current, notes: event.target.value }))
                    }
                  />
                </label>
                <div className="panel-actions form-actions-full">
                  <button type="button" className="primary-button" disabled={busy} onClick={saveDocument}>
                    {editingDocumentId ? "Guardar documento" : "Agregar documento manual"}
                  </button>
                  {editingDocumentId ? (
                    <button type="button" className="secondary-button" disabled={busy} onClick={resetDocumentForm}>
                      Cancelar
                    </button>
                  ) : null}
                </div>
              </div>
            </section>

            <section className="panel wide">
              <h2>Eventos</h2>
              {detail.events.length ? (
                <DataTable
                  rows={detail.events}
                  getRowKey={(row) => row.event_id}
                  columns={[
                    { key: "type", header: "Tipo", render: (row) => row.event_type },
                    { key: "at", header: "Fecha", render: (row) => formatDate(row.occurred_at) },
                    { key: "actor", header: "Actor", render: (row) => `${row.actor_type} ${display(row.actor_id)}` },
                    { key: "summary", header: "Resumen", render: (row) => row.summary }
                  ]}
                />
              ) : (
                <div className="state-box">No hay eventos para mostrar</div>
              )}
            </section>
          </div>
        ) : null}
      </PageState>
    </section>
  );
}

function Detail({ label, value }: { label: string; value: unknown }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{display(value)}</dd>
    </>
  );
}

function DocumentLink({ carrierId, document }: { carrierId: string; document: CarrierDocument }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!document.has_file) return <>Archivo no disponible</>;
  return (
    <span>
      <button
        type="button"
        className="small-button"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            await api.downloadCarrierDocument(carrierId, document.id, document.file_name ?? document.id);
          } catch (reason) {
            setError(reason instanceof Error ? reason.message : "No se pudo descargar el archivo");
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Descargando…" : "Descargar"}
      </button>
      {error ? <span role="alert"> {error}</span> : null}
    </span>
  );
}

function parseCommaList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function emptyToNull(value: string | null): string | null {
  if (value === null) {
    return null;
  }
  const cleaned = value.trim();
  return cleaned || null;
}

function captureStepLabel(step: string | null): string {
  const labels: Record<string, string> = {
    carrier_name: "Nombre del transportista",
    email: "Email",
    company_name: "Empresa",
    cuit: "CUIT",
    truck_count: "Cantidad de unidades",
    vehicle_plate: "Patente de unidad",
    vehicle_type: "Tipo de unidad",
    vehicle_body_type: "Carrocería",
    driver_name: "Nombre del conductor",
    driver_phone: "Teléfono del conductor",
    license_category: "Categoría de licencia",
    driver_license_upload: "Adjunto de licencia",
    add_another_vehicle: "Continuar con otra unidad",
    review_confirmation: "Resumen para confirmar",
    edit_field: "Selección del dato a corregir",
    edit_value: "Corrección en curso",
    complete: "Captura finalizada"
  };
  return step ? labels[step] ?? step : "No iniciada por WhatsApp";
}
