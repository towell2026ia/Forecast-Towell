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
    apiEnabled: process.env.AI_ASSISTANT_API_ENABLED !== "false" && process.env.NODE_ENV === "development",
    voiceEnabled: false,
    mode: "local" as const,
  };
  return <ForecastTowellApp supabaseConfigured={supabaseConfigured} assistantConfig={assistantConfig} />;
}
