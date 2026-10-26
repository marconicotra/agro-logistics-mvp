export interface EscalationEnv {
  SLACK_WEBHOOK_URL?: string;
}

export interface EscalationPayload {
  reason: string;
  conversationId?: string;
  phoneNumber?: string;
  messageText?: string;
  severity?: "low" | "medium" | "high";
  context?: Record<string, unknown>;
}

export async function escalateToHuman(env: EscalationEnv, payload: EscalationPayload) {
  const escalation = {
    status: "human_review_requested",
    reason: payload.reason,
    severity: payload.severity || "medium",
    conversation_id: payload.conversationId,
    phone_number_masked: maskPhone(payload.phoneNumber),
    message_text: payload.messageText,
    context: payload.context || {},
  };

  if (!env.SLACK_WEBHOOK_URL) {
    return {
      ...escalation,
      delivered: false,
      todo: "Configure SLACK_WEBHOOK_URL or backend POST /api/v1/admin/handoff.",
    };
  }

  const response = await fetch(env.SLACK_WEBHOOK_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text: `AGRO human review requested: ${payload.reason}`,
      blocks: [
        {
          type: "section",
          text: {
            type: "mrkdwn",
            text: `*AGRO human review requested*\nReason: ${payload.reason}\nPhone: ${maskPhone(
              payload.phoneNumber,
            ) || "unknown"}`,
          },
        },
      ],
    }),
  });

  return {
    ...escalation,
    delivered: response.ok,
    slack_status: response.status,
  };
}

function maskPhone(phoneNumber?: string): string | undefined {
  if (!phoneNumber) {
    return undefined;
  }
  const digits = phoneNumber.replace(/\D/g, "");
  if (digits.length <= 4) {
    return "***";
  }
  return `${digits.slice(0, 3)}***${digits.slice(-3)}`;
}

export default escalateToHuman;
