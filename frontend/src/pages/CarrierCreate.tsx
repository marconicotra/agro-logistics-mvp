import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api } from "../api/client";
import type { CarrierPayload } from "../types";

const EMPTY_FORM: CarrierPayload = {
  name: "",
  phone: "",
  email: "",
  company_name: "",
  cuit: "",
  truck_count: 1,
  truck_types: [],
  truck_body_type: ""
};

export function CarrierCreate() {
  const navigate = useNavigate();
  const [form, setForm] = useState<CarrierPayload>(EMPTY_FORM);
  const [truckTypesInput, setTruckTypesInput] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const detail = await api.createCarrier({
        ...form,
        phone: emptyToNull(form.phone),
        email: emptyToNull(form.email),
        company_name: emptyToNull(form.company_name),
        cuit: emptyToNull(form.cuit),
        truck_count: form.truck_count ?? null,
        truck_types: parseCommaList(truckTypesInput),
        truck_body_type: emptyToNull(form.truck_body_type)
      });
      navigate(`/carriers/${detail.carrier.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No se pudo crear el transportista");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <Link className="inline-link" to="/carriers">
            Volver a transportistas
          </Link>
          <h1>Nuevo transportista</h1>
          <p>Cargá los datos del transportista.</p>
        </div>
      </header>

      <section className="panel form-panel">
        {error ? <div className="feedback error-feedback">{error}</div> : null}
        <div className="form-grid">
          <label className="field">
            <span>Nombre</span>
            <input
              className="text-input"
              value={form.name}
              onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
            />
          </label>
          <label className="field">
            <span>Teléfono</span>
            <input
              className="text-input"
              value={form.phone ?? ""}
              onChange={(event) => setForm((current) => ({ ...current, phone: event.target.value }))}
            />
          </label>
          <label className="field">
            <span>Email</span>
            <input
              className="text-input"
              value={form.email ?? ""}
              onChange={(event) => setForm((current) => ({ ...current, email: event.target.value }))}
            />
          </label>
          <label className="field">
            <span>Empresa</span>
            <input
              className="text-input"
              value={form.company_name ?? ""}
              onChange={(event) =>
                setForm((current) => ({ ...current, company_name: event.target.value }))
              }
            />
          </label>
          <label className="field">
            <span>CUIT</span>
            <input
              className="text-input"
              value={form.cuit ?? ""}
              onChange={(event) => setForm((current) => ({ ...current, cuit: event.target.value }))}
            />
          </label>
          <label className="field">
            <span>Cantidad de camiones</span>
            <input
              className="text-input"
              type="number"
              min="0"
              value={form.truck_count ?? ""}
              onChange={(event) =>
                setForm((current) => ({
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
              value={truckTypesInput}
              onChange={(event) => setTruckTypesInput(event.target.value)}
              placeholder="camion, semi, chasis"
            />
          </label>
          <label className="field">
            <span>Carrocería / jaula</span>
            <input
              className="text-input"
              value={form.truck_body_type ?? ""}
              onChange={(event) =>
                setForm((current) => ({ ...current, truck_body_type: event.target.value }))
              }
            />
          </label>
        </div>
        <div className="panel-actions">
          <button type="button" className="primary-button" disabled={submitting} onClick={() => void submit()}>
            Guardar transportista
          </button>
          <Link className="secondary-link-button" to="/carriers">
            Cancelar
          </Link>
        </div>
      </section>
    </section>
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
