import { START, Workflow } from '@kapso/workflows';

// The user-facing agent now runs in the AGRO backend using OPENAI_API_KEY.
// Keep this Kapso workflow dormant: inbound events are handled by the signed
// backend webhook, which sends replies through the Kapso WhatsApp adapter.
const workflow = new Workflow("agro-whatsapp", {
  name: "AGRO WhatsApp",
  status: "draft",
});

workflow.addNode(START, {
  position: { x: 100, y: 120 },
});

workflow.addTrigger({
  active: false,
  type: "inbound_message",
  phoneNumberId: "597907523413541",
});

export default workflow;
