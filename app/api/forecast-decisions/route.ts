import { NextResponse } from "next/server";

const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function configuration(request: Request) {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  const authorization = request.headers.get("authorization");
  if (!url || !key) return { error: NextResponse.json({ error: "supabase_not_configured" }, { status: 503 }) };
  if (!authorization?.toLowerCase().startsWith("bearer ")) return { error: NextResponse.json({ error: "authentication_required" }, { status: 401 }) };
  return { url, key, authorization };
}

export async function GET(request: Request) {
  const config = configuration(request);
  if ("error" in config) return config.error;
  const { searchParams } = new URL(request.url);
  const scope = searchParams.get("scope") ?? "current";
  const decisionId = searchParams.get("decisionId");
  if (decisionId && !uuidPattern.test(decisionId)) return NextResponse.json({ error: "invalid_decision_id" }, { status: 400 });
  const path = scope === "fva"
    ? `human_fva_metrics?select=*&order=created_at.desc${decisionId ? `&adjustment_version_id=eq.${decisionId}` : ""}`
    : scope === "history"
      ? `adjustment_versions?select=*,forecast_adjustments(*),forecast_approvals(*)&order=proposed_at.desc${decisionId ? `&forecast_decision_id=eq.${decisionId}` : ""}`
      : "current_forecast_decisions?select=*&order=forecast_cycle.desc";
  if (!["current", "history", "fva"].includes(scope)) return NextResponse.json({ error: "invalid_scope" }, { status: 400 });
  const response = await fetch(`${config.url}/rest/v1/${path}`, { headers: { apikey: config.key, Authorization: config.authorization } });
  if (!response.ok) return NextResponse.json({ error: "decision_read_failed" }, { status: 502 });
  return NextResponse.json(await response.json());
}

export async function POST(request: Request) {
  const config = configuration(request);
  if ("error" in config) return config.error;
  const body = await request.json() as {
    action?: "review" | "adjust" | "approve";
    forecastTowellId?: unknown;
    adjustmentVersionId?: unknown;
    adjustments?: unknown;
    significantThreshold?: unknown;
    correctionReason?: unknown;
    comment?: unknown;
  };
  const action = body.action;
  if (!action || !["review", "adjust", "approve"].includes(action)) return NextResponse.json({ error: "invalid_action" }, { status: 400 });
  const isApproval = action === "approve";
  const identifier = isApproval ? body.adjustmentVersionId : body.forecastTowellId;
  if (typeof identifier !== "string" || !uuidPattern.test(identifier)) return NextResponse.json({ error: "invalid_identifier" }, { status: 400 });
  const threshold = typeof body.significantThreshold === "number" ? body.significantThreshold : 20;
  if (!isApproval && (threshold <= 0 || threshold > 1000)) return NextResponse.json({ error: "invalid_significant_threshold" }, { status: 400 });
  if (!isApproval && body.adjustments !== undefined && !Array.isArray(body.adjustments)) return NextResponse.json({ error: "adjustments_must_be_array" }, { status: 400 });
  const rpc = isApproval ? "approve_forecast_decision" : "request_forecast_decision";
  const payload = isApproval
    ? { p_adjustment_version_id: identifier, p_comment: typeof body.comment === "string" ? body.comment : null }
    : {
        p_forecast_towell_id: identifier,
        p_adjustments: action === "review" ? [] : (body.adjustments ?? []),
        p_significant_threshold: threshold,
        p_correction_reason: typeof body.correctionReason === "string" ? body.correctionReason : null,
      };
  const response = await fetch(`${config.url}/rest/v1/rpc/${rpc}`, {
    method: "POST",
    headers: { apikey: config.key, Authorization: config.authorization, "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) return NextResponse.json({ error: isApproval ? "approval_failed" : "decision_failed", detail: await response.text() }, { status: response.status === 403 ? 403 : 502 });
  return NextResponse.json({ id: await response.json(), status: isApproval ? "frozen" : "versioned" }, { status: isApproval ? 200 : 201 });
}
