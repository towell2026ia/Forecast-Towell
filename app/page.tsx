import ForecastTowellApp from "./forecast-towell-app";

export const dynamic = "force-dynamic";

export default function Home() {
  const supabaseConfigured = Boolean(
    process.env.SUPABASE_URL && process.env.SUPABASE_SERVICE_ROLE_KEY,
  );
  const currentRole = process.env.CURRENT_USER_ROLE ?? "manager";
  const assistantConfig = {
    authorized: currentRole === "manager",
    uiEnabled: process.env.AI_ASSISTANT_UI_ENABLED !== "false",
    apiEnabled: false,
    voiceEnabled: false,
    mode: "mock" as const,
  };
  return <ForecastTowellApp supabaseConfigured={supabaseConfigured} assistantConfig={assistantConfig} />;
}
