const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "access-control-allow-origin": "*",
      "access-control-allow-methods": "GET,POST,OPTIONS",
      "access-control-allow-headers": "content-type,authorization",
    },
  });

async function gateway(path: string, init: RequestInit = {}) {
  const base = process.env.NEON_AI_GATEWAY_BASE_URL;
  const token = process.env.NEON_AI_GATEWAY_TOKEN;
  if (!base || !token) throw new Error("Neon AI Gateway is not configured");
  return fetch(base + path, {
    ...init,
    headers: {
      authorization: `Bearer ${token}`,
      "content-type": "application/json",
      ...(init.headers || {}),
    },
  });
}

export default {
  async fetch(request: Request): Promise<Response> {
    if (request.method === "OPTIONS") return json({}, 204);

    const url = new URL(request.url);

    if (url.pathname === "/" || url.pathname === "/health") {
      return json({
        ok: true,
        service: "ucoa-agent",
        runtime: "neon-function",
        region: "us-east-2",
        version: "neon-v1",
      });
    }

    if (url.pathname === "/v1/providers/models" && request.method === "GET") {
      try {
        const r = await gateway("/v1/models");
        return new Response(await r.text(), {
          status: r.status,
          headers: { "content-type": "application/json", "access-control-allow-origin": "*" },
        });
      } catch (e) {
        return json({ ok: false, error: String(e) }, 503);
      }
    }

    if (url.pathname === "/v1/agent/plan" && request.method === "POST") {
      try {
        const body = await request.json() as { task?: string };
        const task = String(body.task || "").trim();
        if (!task) return json({ ok: false, error: "task is required" }, 400);

        const r = await gateway("/v1/chat/completions", {
          method: "POST",
          body: JSON.stringify({
            model: "gpt-5-mini",
            temperature: 0,
            messages: [
              {
                role: "system",
                content:
                  "You are UCOA planner. Return JSON only with {steps:[{action:string,reason:string}],goal:string}. Keep steps concrete and bounded.",
              },
              { role: "user", content: task },
            ],
          }),
        });
        const raw = await r.text();
        if (!r.ok) return json({ ok: false, gateway_status: r.status, gateway: raw.slice(0, 2000) }, 502);

        let payload: any;
        try { payload = JSON.parse(raw); } catch { return json({ ok: false, error: "invalid gateway JSON" }, 502); }
        const text = payload?.choices?.[0]?.message?.content || "";
        let plan: any;
        try { plan = JSON.parse(text); } catch { plan = { steps: [], goal: text }; }
        return json({ ok: true, provider: "neon-ai-gateway", model: "gpt-5-mini", plan });
      } catch (e) {
        return json({ ok: false, error: String(e) }, 503);
      }
    }

    return json({ ok: false, error: "not_found" }, 404);
  },
};
