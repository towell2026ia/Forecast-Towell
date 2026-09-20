import { NextResponse } from "next/server";

export async function POST() {
  const enabled = process.env.AI_ASSISTANT_API_ENABLED === "true";
  return NextResponse.json({
    message: enabled
      ? "El proveedor futuro aún no está implementado."
      : "La API del asistente está deshabilitada en PRD 08A.",
    status: enabled ? "ready" : "disabled",
    source: "mock",
    actions: [],
    metadata: { apiEnabled: enabled, phase: "PRD 08A" },
  }, { status: enabled ? 501 : 503 });
}
