import ForecastTowellApp from "./forecast-towell-app";

export const dynamic = "force-dynamic";

export default function Home() {
  const supabaseConfigured = Boolean(
    process.env.SUPABASE_URL && process.env.SUPABASE_SERVICE_ROLE_KEY,
  );
  return <ForecastTowellApp supabaseConfigured={supabaseConfigured} />;
}
