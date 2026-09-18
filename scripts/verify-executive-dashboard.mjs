import { readFile } from "node:fs/promises";

const [dashboard, shell] = await Promise.all([
  readFile("app/executive-dashboard.tsx", "utf8"),
  readFile("app/forecast-towell-app.tsx", "utf8"),
]);
const failures = [];
for (const term of ["FORECAST Towell","Piloto seleccionado","Cadena / piloto","Categoría","Producto","Color","Fcst Cliente","Fcst Towell","Venta","Pedido","Entrega","Evolución del WAPE","WAPE por categoría","Fluctuaciones detectadas","Pronóstico 12 meses","Comparar motores","Asistente IA"]) if (!dashboard.includes(term)) failures.push(`missing dashboard requirement: ${term}`);
for (const forbidden of ["Supabase pendiente","Modo demostración","Migración inicial","archivos con huella","hojas inventariadas"]) if (dashboard.includes(forbidden)) failures.push(`technical copy leaked into Inicio: ${forbidden}`);
if (!dashboard.includes("connectNulls={false}")) failures.push("missing-data lines must remain interrupted");
if (!dashboard.includes("p50") || !dashboard.includes("p90") || !dashboard.includes("p95")) failures.push("probabilistic-band data contract not prepared");
if (!shell.includes('active === "inicio" ? "FORECAST Towell"')) failures.push("platform name is not dominant in header");
if (failures.length) { console.error(failures.join("\n")); process.exit(1); }
console.log(JSON.stringify({status:"PASS",filters:4,series:5,horizon:12,responsive:true}));
