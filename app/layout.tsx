import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "FORECAST Towell",
  description: "Operación, calidad, periodos y auditoría para el piloto FENDI BD.",
  icons: { icon: "/favicon.svg", shortcut: "/favicon.svg" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="es"><body>{children}</body></html>;
}
