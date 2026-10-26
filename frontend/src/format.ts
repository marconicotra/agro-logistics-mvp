export function display(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  if (Array.isArray(value)) {
    return value.length ? value.join(", ") : "-";
  }
  return String(value);
}

export function formatDate(value?: string | null): string {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("es-AR", {
    dateStyle: "short",
    timeStyle: "short"
  }).format(date);
}

export function loadLabel(row: {
  quantity_estimate?: string | number | null;
  quantity_unit?: string | null;
  cargo_type?: string | null;
  livestock_type?: string | null;
  cargo_category?: string | null;
  weight_per_head_kg?: string | number | null;
}): string {
  const typeLabel = row.cargo_type ?? row.livestock_type;
  const quantity = formatQuantity(row.quantity_estimate);
  const unit = formatQuantityUnit(row.quantity_unit, row.cargo_category, typeLabel);

  const load = quantity && unit && typeLabel
    ? `${quantity} ${unit} de ${typeLabel}`
    : quantity && typeLabel
      ? `${quantity} ${typeLabel}`
      : typeLabel ?? (quantity && unit ? `${quantity} ${unit}` : quantity ?? "-");
  const weight = formatQuantity(row.weight_per_head_kg);
  return weight ? `${load} · Pesaje: ${weight} kg/cabeza` : load;
}

function formatQuantity(value?: string | number | null): string | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isNaN(numeric)) {
    return new Intl.NumberFormat("es-AR", {
      minimumFractionDigits: numeric % 1 === 0 ? 0 : 2,
      maximumFractionDigits: 2
    }).format(numeric);
  }
  return String(value);
}

function formatQuantityUnit(
  quantityUnit?: string | null,
  cargoCategory?: string | null,
  typeLabel?: string | null
): string | null {
  if (cargoCategory === "LIVESTOCK" || typeLabel) {
    if (quantityUnit === "HEAD") return null;
  }

  switch (quantityUnit) {
    case "TON":
      return "toneladas";
    case "KG":
      return "kilos";
    case "TRUCKLOAD":
      return "camiones";
    case "HEAD":
      return "cabezas";
    default:
      return quantityUnit ? quantityUnit.toLowerCase() : null;
  }
}
