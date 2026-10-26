import { createHmac, randomUUID } from "node:crypto";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page, type APIRequestContext } from "@playwright/test";

const apiBase = "http://127.0.0.1:8004";
const phone = "+5491100000001";
const webhookSecret = "playwright-local-only-hmac-secret-2026-10-26";
const operatorHeaders = {
  "x-operator-user-id": "playwright_operator",
  "x-operator-role": "admin"
};

async function screenshot(page: Page, name: string) {
  const folder = path.resolve("test-results/screenshots");
  mkdirSync(folder, { recursive: true });
  await page.evaluate(() => {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const replacements: Array<[Text, string]> = [];
    while (walker.nextNode()) {
      const node = walker.currentNode as Text;
      if (node.nodeValue?.match(/\+549\d{6,}/)) {
        replacements.push([node, node.nodeValue]);
        node.nodeValue = node.nodeValue.replace(/\+549\d{6,}/g, "[número de prueba]");
      }
    }
    (window as typeof window & { __qaScreenshotText?: Array<[Text, string]> }).__qaScreenshotText = replacements;
  });
  try {
    await page.screenshot({ path: path.join(folder, `${test.info().project.name}-${name}.png`), fullPage: true });
  } finally {
    await page.evaluate(() => {
      const target = window as typeof window & { __qaScreenshotText?: Array<[Text, string]> };
      for (const [node, original] of target.__qaScreenshotText ?? []) node.nodeValue = original;
      delete target.__qaScreenshotText;
    });
  }
}

async function sendWhatsApp(request: APIRequestContext, conversationId: string, text: string) {
  const previousAccepted = (await apiGet(request, "/api/v1/backoffice/notification-outbox?status=ACCEPTED&limit=100")).total;
  const key = randomUUID();
  const payload = {
    event_type: "message.received",
    idempotency_key: key,
    provider_contact_id: "pw_contact_seed",
    provider_message_id: `wamid_${key}`,
    conversation_id: conversationId,
    occurred_at: new Date().toISOString(),
    phone_number: phone,
    payload: { text }
  };
  const body = JSON.stringify(payload);
  const digest = createHmac("sha256", webhookSecret).update(body).digest("hex");
  const response = await request.post(`${apiBase}/api/v1/webhooks/kapso`, {
    data: body,
    headers: { "content-type": "application/json", "x-webhook-signature": `sha256=${digest}` }
  });
  expect(response.status(), `webhook response for ${text}`).toBe(200);
  const result = await response.json();
  expect(result.accepted).toBe(true);
  await expect.poll(async () => {
    return (await apiGet(request, "/api/v1/backoffice/notification-outbox?status=ACCEPTED&limit=100")).total;
  }, { timeout: 10_000, message: `mock WhatsApp reply should be accepted after: ${text}` }).toBeGreaterThan(previousAccepted);
  return result;
}

async function apiGet(request: APIRequestContext, url: string) {
  const response = await request.get(`${apiBase}${url}`, { headers: operatorHeaders });
  expect(response.ok(), `${url} returned ${response.status()}`).toBe(true);
  return response.json();
}

test("recorre pantallas del backoffice y captura estados en el viewport actual", async ({ page }) => {
  const screens = [
    ["/dashboard", "Inicio"],
    ["/conversations", "Conversaciones abiertas"],
    ["/notifications", "Avisos"],
    ["/shipments", "Cargas sin transportista"],
    ["/trips", "Viajes"],
    ["/route-availabilities", "Recorridos disponibles"],
    ["/producers", "Productores"],
    ["/carriers", "Transportistas"],
    ["/whatsapp-allowlist", "Números autorizados"],
    ["/catalogs", "Listas del sistema"]
  ] as const;
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  const overflows: string[] = [];
  page.on("pageerror", (error) => consoleErrors.push(error.message));
  page.on("requestfailed", (request) => failedRequests.push(`${request.method()} ${request.url()}: ${request.failure()?.errorText}`));

  for (const [route, heading] of screens) {
    await page.goto(route);
    await expect(page.getByRole("heading", { name: heading }).first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    await screenshot(page, route.replaceAll("/", "_").replace(/^_/, ""));
    const dimensions = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth }));
    if (dimensions.document > dimensions.viewport + 2) overflows.push(`${route}: ${dimensions.document}px document in ${dimensions.viewport}px viewport`);
  }

  await page.goto("/producer-status");
  await expect(page.getByRole("heading", { name: "Estado de tus cargas y viajes" })).toBeVisible();
  await screenshot(page, "producer-status");
  await page.goto("/carrier-status");
  await expect(page.getByRole("heading", { name: "Estado de viajes y oportunidades" })).toBeVisible();
  await screenshot(page, "carrier-status");

  await page.goto("/dashboard");
  await page.keyboard.press("Tab");
  expect(await page.evaluate(() => document.activeElement?.tagName)).toBeTruthy();
  expect(consoleErrors, "browser page errors").toEqual([]);
  expect(failedRequests, "failed local requests").toEqual([]);
  expect(overflows, "horizontal page overflow").toEqual([]);
});

test("crea un transportista desde el backoffice", async ({ page }) => {
  page.setDefaultTimeout(10_000);
  const suffix = randomUUID().slice(0, 8);
  await page.goto("/carriers/new");
  await page.getByLabel("Nombre").fill(`Transportista prueba ${suffix}`);
  await page.getByLabel("Teléfono").fill("+5491100000002");
  await page.getByLabel("Empresa").fill("Empresa de prueba");
  await page.getByLabel("Cantidad de camiones").fill("1");
  await page.getByLabel("Tipos de camión").fill("jaula");
  await page.getByRole("button", { name: "Guardar transportista" }).click();
  await expect(page).toHaveURL(/\/carriers\/car_/);
  await expect(page.getByRole("heading", { name: "Transportista", exact: true })).toBeVisible();
  await expect(page.getByText(`Transportista prueba ${suffix}`, { exact: true })).toBeVisible();
  await expect(page.getByText("Esperando datos", { exact: true })).toBeVisible();
  await screenshot(page, "carrier-created");

  await page.goto("/carriers");
  await page.getByPlaceholder("Nombre, empresa, CUIT o patente").fill(`Transportista prueba ${suffix}`);
  await page.getByRole("button", { name: "Buscar" }).click();
  await expect(page.getByText(`Transportista prueba ${suffix}`)).toBeVisible();
});

test("registra un recorrido disponible sin crear un viaje", async ({ page, request }) => {
  page.setDefaultTimeout(10_000);
  const suffix = randomUUID().slice(0, 8);
  const tripsBefore = await apiGet(request, "/api/v1/backoffice/trips/page?limit=50&offset=0");
  await page.goto("/route-availabilities");
  const form = page.locator("details").first();
  await form.getByText("Nueva disponibilidad").click();
  await form.getByLabel("Transportista").selectOption("carrier_pw_seed");
  await form.getByLabel("Origen").fill("Pergamino, Buenos Aires");
  await form.getByLabel("Destino").fill("Rosario, Santa Fe");
  await form.getByLabel("Paradas intermedias (separadas por coma)").fill("San Nicolás, Buenos Aires");
  await form.getByLabel("Desde").fill("2026-11-15T08:00");
  await form.getByLabel("Hasta").fill("2026-11-15T23:59");
  await form.getByLabel("Capacidad declarada").fill("30");
  await form.getByLabel("Unidad de capacidad").selectOption("HEAD");
  await form.getByLabel("Tipos de carga admitidos").fill("novillos");
  await form.getByLabel("Equipos admitidos").fill("jaula");
  await form.getByLabel("Escenario QA").fill(`pw-${suffix}`);
  await form.getByRole("button", { name: "Guardar borrador" }).click();
  await expect(page.getByText("Pergamino, Buenos Aires → San Nicolás → Buenos Aires → Rosario, Santa Fe")).toBeVisible();
  await expect(page.getByText("Borrador").first()).toBeVisible();
  const availabilityPage = await apiGet(request, "/api/v1/backoffice/route-availabilities/page?limit=50&offset=0");
  const availability = availabilityPage.items.find((item: { test_run_id?: string }) => item.test_run_id === `pw-${suffix}`);
  expect(availability?.status).toBe("DRAFT");
  expect(availability?.committed_shipment_id).toBeFalsy();
  const trips = await apiGet(request, "/api/v1/backoffice/trips/page?limit=50&offset=0");
  expect(trips.total, "a route declaration should not create a trip").toBe(tripsBefore.total);
  await screenshot(page, "route-availability-draft");
});

test("WhatsApp publica una carga y habilita el interés y la aceptación", async ({ page, request }) => {
  page.setDefaultTimeout(10_000);
  const conversationId = `pw-${randomUUID()}`;
  const messages = [
    "/test iniciar",
    "/soy transportista",
    "informar disponibilidad",
    "Pergamino, Buenos Aires",
    "Rosario, Santa Fe",
    "15/11/2026",
    "sin paradas",
    "30 cabezas",
    "novillos",
    "jaula",
    "confirmar",
    "/soy productor",
    "Necesito transportar 8 novillos desde Pergamino, Buenos Aires hasta Rosario, Santa Fe para el 15/11/2026",
    "confirmar"
  ];
  let active = false;
  try {
    for (const message of messages) {
      await sendWhatsApp(request, conversationId, message);
      if (message === "/test iniciar") active = true;
    }

    const testStatus = await apiGet(request, `/api/v1/admin/test/session-status?phone_number=${encodeURIComponent(phone)}`);
    expect(testStatus.active_test_run_id).toBeTruthy();
    const unassigned = await apiGet(request, "/api/v1/backoffice/shipments/unassigned/page?limit=50&offset=0");
    const shipmentDetails = await Promise.all(unassigned.items.map((item: { id: string }) =>
      apiGet(request, `/api/v1/backoffice/shipments/${item.id}`)
    ));
    const qaShipment = shipmentDetails.find((detail: { shipment: { test_run_id?: string | null } }) =>
      detail.shipment.test_run_id === testStatus.active_test_run_id
    );
    expect(qaShipment, "the confirmed QA load should be visible in the backoffice").toBeTruthy();
    const shipmentId = qaShipment.shipment.id as string;
    expect(qaShipment.shipment.status).toBe("PUBLISHED");
    await page.goto(`/shipments/${shipmentId}`);
    await expect(page.getByRole("heading", { name: "Detalle de carga" })).toBeVisible();
    await screenshot(page, "shipment-published");
    const dispatch = await apiGet(request, `/api/v1/backoffice/shipments/${shipmentId}/dispatch?test_run_id=${encodeURIComponent(testStatus.active_test_run_id)}`);
    expect(dispatch.decisions).toEqual(expect.arrayContaining([
      expect.objectContaining({
        data: expect.objectContaining({
          carrier_id: "carrier_pw_seed",
          reason: "compatible_declared_segment",
          availability_id: expect.any(String)
        })
      })
    ]));
    expect(["QUEUED", "ACCEPTED"]).toContain(dispatch.decisions[0]?.status);
    expect(qaShipment.offers, "dispatch notifies the carrier; the offer is recorded after an explicit interest response").toHaveLength(0);

    await sendWhatsApp(request, conversationId, "/soy transportista");
    await sendWhatsApp(request, conversationId, "1");
    const offers = await apiGet(request, `/api/v1/shipment-requests/${shipmentId}/offers`);
    expect(offers.some((offer: { response_type: string; status: string }) => offer.response_type === "INTERESTED" && offer.status === "RECEIVED")).toBe(true);
    await sendWhatsApp(request, conversationId, "/soy productor");
    await sendWhatsApp(request, conversationId, "ver interesados");
    await sendWhatsApp(request, conversationId, "elegir 1");
    await sendWhatsApp(request, conversationId, "confirmar");

    const trips = await apiGet(request, "/api/v1/backoffice/trips/page?limit=50&offset=0");
    const trip = trips.items.find((item: { shipment_request_id: string }) => item.shipment_request_id === shipmentId);
    expect(trip?.status).toBe("PLANNED");

    await page.goto(`/shipments/${shipmentId}`);
    await expect(page.getByRole("heading", { name: "Detalle de carga" })).toBeVisible();
    await expect(page.getByText("Transportista elegido")).toBeVisible();
    await screenshot(page, "shipment-confirmed");
    await page.goto("/trips");
    await expect(page.getByText(shipmentId)).toBeVisible();
    await screenshot(page, "trip-planned");
    await page.goto(`/trips/${trip.id}/tracking`);
    await expect(page.getByRole("heading", { name: "Seguimiento del viaje" })).toBeVisible();
    await screenshot(page, "trip-tracking-no-crew");
  } finally {
    if (active) {
      try { await sendWhatsApp(request, conversationId, "/test cerrar"); } catch { /* preserve the original assertion if the local server stopped */ }
    }
  }
});
