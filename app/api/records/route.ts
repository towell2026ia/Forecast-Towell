import { NextRequest, NextResponse } from "next/server";

const allowedTypes = new Set(["pedido", "venta", "entrega", "fcst"]);

export async function POST(request: NextRequest) {
  const url = process.env.SUPABASE_URL;
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !serviceKey) {
    return NextResponse.json({ error: "supabase_not_configured" }, { status: 503 });
  }

  const actorEmail = request.headers.get("oai-authenticated-user-email");
  if (!actorEmail) {
    return NextResponse.json({ error: "authenticated_user_required" }, { status: 401 });
  }

  const body = await request.json() as { type?: string; payload?: Record<string, unknown> };
  if (!body.type || !allowedTypes.has(body.type) || !body.payload) {
    return NextResponse.json({ error: "invalid_capture_payload" }, { status: 400 });
  }

  const response = await fetch(`${url}/rest/v1/rpc/capture_operational_record`, {
    method: "POST",
    headers: {
      apikey: serviceKey,
      authorization: `Bearer ${serviceKey}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({
      p_record_type: body.type,
      p_payload: body.payload,
      p_actor_email: actorEmail,
    }),
  });

  const result = await response.json().catch(() => ({ error: "invalid_supabase_response" }));
  return NextResponse.json(result, { status: response.status });
}

