import { NextResponse } from "next/server";

type ClosureRequest = {
  action?: "close" | "reopen";
  periodId?: unknown;
  reason?: unknown;
  clientForecastNotReceived?: unknown;
};

export async function POST(request: Request) {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) return NextResponse.json({ error: "supabase_not_configured" }, { status: 503 });

  const authorization = request.headers.get("authorization");
  if (!authorization?.toLowerCase().startsWith("bearer ")) {
    return NextResponse.json({ error: "authentication_required" }, { status: 401 });
  }

  const body = (await request.json()) as ClosureRequest;
  if (typeof body.periodId !== "string" || !/^[0-9a-f-]{36}$/i.test(body.periodId)) {
    return NextResponse.json({ error: "invalid_period_id" }, { status: 400 });
  }
  const action = body.action ?? "close";
  const reason = typeof body.reason === "string" && body.reason.trim() ? body.reason.trim() : null;
  if (action === "reopen" && !reason) {
    return NextResponse.json({ error: "reopen_reason_required" }, { status: 400 });
  }

  const rpc = action === "reopen" ? "request_period_reopening" : "request_period_closure";
  const payload = action === "reopen"
    ? { p_period_id: body.periodId, p_reason: reason }
    : {
        p_period_id: body.periodId,
        p_correction_reason: reason,
        p_client_forecast_not_received: body.clientForecastNotReceived === true,
      };
  const response = await fetch(`${url}/rest/v1/rpc/${rpc}`, {
    method: "POST",
    headers: { apikey: key, Authorization: authorization, "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const detail = await response.text();
    return NextResponse.json({ error: action === "reopen" ? "reopen_failed" : "closure_queue_failed", detail }, { status: response.status === 403 ? 403 : 502 });
  }
  return NextResponse.json({ id: await response.json(), status: action === "reopen" ? "reopened" : "queued" }, { status: action === "reopen" ? 200 : 202 });
}
