export interface KnowledgeSearchResult {
  source: string;
  fragment: string;
}

const KNOWLEDGE_SNIPPETS: KnowledgeSearchResult[] = [
  {
    source: "faq.md",
    fragment:
      "Para pedir un camión, enviar cantidad, tipo de hacienda, origen, destino, fecha o ventana y contacto operativo.",
  },
  {
    source: "faq.md",
    fragment: "Transportista responde 1 Me interesa, 2 No puedo, 3 Más info.",
  },
  {
    source: "product.md",
    fragment:
      "AGRO Logistics coordina transporte de hacienda por WhatsApp; backend registra ShipmentRequest, TripOffer, Assignment, Trip y EventLog.",
  },
  {
    source: "operations.md",
    fragment:
      "El operador interviene cuando faltan datos, hay ubicación ambigua, cancelaciones, conflictos o confirmaciones críticas.",
  },
];

function tokenize(value: string): string[] {
  return value
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .split(/[^a-z0-9]+/i)
    .filter(Boolean);
}

export function searchKnowledge(query: string, limit = 3): KnowledgeSearchResult[] {
  const terms = new Set(tokenize(query));
  if (terms.size === 0) {
    return [];
  }

  return KNOWLEDGE_SNIPPETS.map((item) => {
    const haystack = tokenize(`${item.source} ${item.fragment}`);
    const score = haystack.reduce((total, token) => total + (terms.has(token) ? 1 : 0), 0);
    return { item, score };
  })
    .filter(({ score }) => score > 0)
    .sort((left, right) => right.score - left.score)
    .slice(0, limit)
    .map(({ item }) => item);
}

export default searchKnowledge;
