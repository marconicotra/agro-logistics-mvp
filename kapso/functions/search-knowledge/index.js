const KNOWLEDGE_SNIPPETS = [
  {
    source: "faq.md",
    fragment:
      "Para pedir un camion, enviar cantidad, tipo de hacienda, origen, destino, fecha o ventana y contacto operativo.",
  },
  {
    source: "faq.md",
    fragment: "Transportista responde 1 Me interesa, 2 No puedo, 3 Mas info.",
  },
  {
    source: "product.md",
    fragment:
      "AGRO Logistics coordina transporte de hacienda por WhatsApp; backend registra ShipmentRequest, TripOffer, Assignment, Trip y EventLog.",
  },
  {
    source: "operations.md",
    fragment:
      "El operador interviene cuando faltan datos, hay ubicacion ambigua, cancelaciones, conflictos o confirmaciones criticas.",
  },
];

async function handler(request) {
  const body = await request.json().catch(() => ({}));
  const input = body.input || body || {};
  const query = String(input.query || "");
  const limit = Number.isFinite(Number(input.limit)) ? Math.max(1, Math.min(Number(input.limit), 5)) : 3;
  const terms = new Set(tokenize(query));

  if (terms.size === 0) {
    return json({ ok: true, results: [] });
  }

  const results = KNOWLEDGE_SNIPPETS.map((item) => {
    const haystack = tokenize(`${item.source} ${item.fragment}`);
    const score = haystack.reduce((total, token) => total + (terms.has(token) ? 1 : 0), 0);
    return { item, score };
  })
    .filter(({ score }) => score > 0)
    .sort((left, right) => right.score - left.score)
    .slice(0, limit)
    .map(({ item }) => item);

  return json({ ok: true, results });
}

function tokenize(value) {
  return value
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .split(/[^a-z0-9]+/i)
    .filter(Boolean);
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
