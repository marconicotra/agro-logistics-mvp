const STATUS_LABELS: Record<string, string> = {
  APPROVED: "Aprobado", ASSIGNED: "Asignada", ACTIVE: "Activa", BLOCKED: "Bloqueado",
  CANCELLED: "Cancelado", CLOSED: "Cerrado", COMPLETED: "Completado", COMMITTED: "Comprometida",
  CONFIGURATION_MISMATCH: "Revisar configuración", CONFIRMED: "Confirmado", DECLARED: "Declarado",
  DRAFT: "Borrador", FAILED: "Fallido", INCOMPLETE: "Incompleta", IN_PROGRESS: "En curso",
  IN_TRANSIT: "En tránsito", INTERESTED: "Interesado", LOADING: "En carga", LOADING_PENDING: "Carga pendiente",
  MATCHING: "Buscando transportista", MAINTENANCE: "En mantenimiento", NOT_AVAILABLE: "No disponible",
  PENDING: "Pendiente", PENDING_CONFIRMATION: "Pendiente de confirmación", PENDING_OPERATOR_REVIEW: "Pendiente de revisión",
  PENDING_REVIEW: "Pendiente de revisión", PROCESSING: "En proceso", PROPOSED: "Propuesto", PUBLISHED: "Publicada",
  RECONCILE_REQUIRED: "Requiere conciliación", REJECTED: "Rechazado", REMINDER_SENT: "Recordatorio enviado",
  RETRY: "Reintento programado", SUSPENDED: "Suspendido", VALIDATED: "Validada", WAITING_DATA: "Esperando datos",
  PLANNED: "Planificado", DECLINED: "No puede", IN_REVIEW: "En revisión", PENDING_APPROVAL: "Pendiente de aprobación",
  EN_OPERACION: "En operación", DISPONIBLE: "Disponible", PARTIALLY_ASSIGNED: "Asignada parcialmente",
  CANCELED: "Cancelado", CREATED: "Creado", REVIEW_REQUIRED: "Requiere revisión",
  WAITING_DOCUMENTS: "Esperando documentación", EXPIRED: "Vencida", DRAFT_QA: "Borrador de prueba",
  REQUIERE_OPERADOR: "Requiere operador", UBICACION_AMBIGUA: "Ubicación por confirmar", SIN_ALERTAS: "Sin alertas",
  VALORES_ESTIMADOS: "Valores estimados", OPEN: "Abierta", RESOLVED: "Resuelta", RETRY_NOT_SENT: "No enviado",
  NEW: "Nuevo", INACTIVE: "Inactivo", DISABLED: "Deshabilitado"
};

const ENTITY_LABELS: Record<string, string> = {
  AGENT: "Agente", Agent: "Agente", CARRIER: "Transportista", Carrier: "Transportista",
  PRODUCER: "Productor", Producer: "Productor", SYSTEM: "Sistema", OPERATOR: "Operador",
  outbound: "Saliente", inbound: "Entrante", status: "Estado", text: "Texto", interactive: "Opción interactiva",
  document: "Documento", image: "Imagen", audio: "Audio", video: "Video", kapso: "WhatsApp (Kapso)", whatsapp: "WhatsApp",
  ShipmentRequest: "Carga", TripOffer: "Oferta", Assignment: "Asignación", Trip: "Viaje"
};

export function statusLabel(value?: string | null): string {
  if (!value) return "Sin dato";
  return STATUS_LABELS[value.toUpperCase()] ?? value.replace(/_/g, " ").toLocaleLowerCase("es-AR");
}

export function entityLabel(value?: string | null): string {
  if (!value) return "Sin dato";
  return ENTITY_LABELS[value] ?? STATUS_LABELS[value.toUpperCase()] ?? value.replace(/_/g, " ").toLocaleLowerCase("es-AR");
}

export function errorLabel(value: string): string {
  const statusCode = value.match(/^(\d{3})\s/);
  if (statusCode) {
    const code = Number(statusCode[1]);
    if (code === 401) return "Tu sesión venció o necesitás iniciar sesión nuevamente.";
    if (code === 403) return "Tu usuario no tiene permisos para realizar esta acción.";
    if (code === 404) return "No encontramos ese registro. Actualizá la página y volvé a intentar.";
    if (code === 409) return "El registro cambió o la acción no está disponible en su estado actual.";
    if (code === 422) return "Revisá los datos ingresados e intentá nuevamente.";
    if (code >= 500) return "El servidor no pudo completar la operación. Volvé a intentar en unos minutos.";
  }
  const known: Record<string, string> = {
    "Failed to fetch": "No se pudo conectar con el servidor.",
    "NetworkError when attempting to fetch resource.": "No se pudo conectar con el servidor.",
    "Backoffice access not granted": "Tu usuario no tiene permiso para acceder al panel.",
    "Administrator role required": "Esta acción requiere permisos de administración.",
    "No pude cargar la carga.": "No se pudo cargar la carga. Volvé a intentar."
  };
  return known[value] ?? value;
}
