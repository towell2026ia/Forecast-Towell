import { NextResponse } from "next/server";

export async function POST(request: Request) {
  if (process.env.AI_ASSISTANT_API_ENABLED === "false") {
    return NextResponse.json({ error: "assistant_disabled" }, { status: 503 });
  }
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid_json" }, { status: 400 });
  }
  if (!body || typeof body !== "object" || typeof (body as { message?: unknown }).message !== "string" ||
      !(body as { message: string }).message.trim() || (body as { message: string }).message.length > 1000) {
    return NextResponse.json({ error: "invalid_message" }, { status: 400 });
  }
  const local = process.env.NODE_ENV === "development";
  // Production needs a verified server-side identity adapter; no browser header is trusted.
  if (!local) return NextResponse.json({ error: "assistant_identity_not_configured" }, { status: 503 });
  const base = process.env.PYTHON_ASSISTANT_URL ?? "http://127.0.0.1:8000";
  const actorId = "local-manager";
  const token = process.env.ASSISTANT_API_TOKEN;
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch(new URL("/api/assistant/message", base), {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-actor-id": actorId!,
          ...(token ? { "x-assistant-token": token } : {}),
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!response.ok) return NextResponse.json({ error: "assistant_backend_unavailable" }, { status: response.status === 403 ? 403 : 503 });
      return NextResponse.json(await response.json());
    } finally {
      clearTimeout(timeout);
    }
  } catch {
    return NextResponse.json({ error: "python_assistant_unavailable" }, { status: 503 });
  }
}
