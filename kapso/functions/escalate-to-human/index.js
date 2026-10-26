async function handler(request, env) {
  const body = await request.json().catch(() => ({}));
  const input = body.input || body || {};
  const reason = String(input.reason || "").trim();

  if (!reason) {
    return json({ ok: false, error: "reason is required" }, 400);
  }

  const escalation = {
    status: "human_review_requested",
    reason,
    severity: input.severity || "medium",
    conversation_id: input.conversationId || body.flow_info?.id || null,
    phone_number_masked: maskPhone(input.phoneNumber || body.execution_context?.context?.phone_number),
    message_text: input.messageText || null,
    context: input.context || {},
  };

  if (!env.SLACK_WEBHOOK_URL) {
    return json({
      ok: true,
      ...escalation,
      delivered: false,
      todo: "Configure SLACK_WEBHOOK_URL or backend POST /api/v1/admin/handoff.",
    });
  }

  const response = await fetch(env.SLACK_WEBHOOK_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text: `AGRO human review requested: ${reason}`,
      blocks: [
        {
          type: "section",
          text: {
            type: "mrkdwn",
            text: `*AGRO human review requested*\nReason: ${reason}\nPhone: ${
              escalation.phone_number_masked || "unknown"
            }`,
          },
        },
      ],
    }),
  });

  return json({
    ok: true,
    ...escalation,
    delivered: response.ok,
    slack_status: response.status,
  });
}

function maskPhone(phoneNumber) {
  if (!phoneNumber) {
    return null;
  }
  const digits = String(phoneNumber).replace(/\D/g, "");
  if (digits.length <= 4) {
    return "***";
  }
  return `${digits.slice(0, 3)}***${digits.slice(-3)}`;
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
