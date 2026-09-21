import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

const read = (path) => readFileSync(path, "utf8");
const sha256 = (path) => createHash("sha256").update(readFileSync(path)).digest("hex").toUpperCase();
const assistant = read("app/forecast-assistant.tsx");
const lottieComponent = read("app/forecast-assistant-lottie.tsx");
const service = read("app/assistant/assistant-service.ts");
const shell = read("app/forecast-towell-app.tsx");
const page = read("app/page.tsx");
const route = read("app/api/assistant/message/route.ts");
const env = read(".env.example");
const animation = JSON.parse(read("public/lottie/forecast-assistant.json"));

const checks = [];
const check = (id, description, condition) => checks.push({ id, description, condition: Boolean(condition) });

check("CP01", "usa el Lottie original como recurso local", animation.v && animation.layers?.length > 0);
check("CP02", "lanzador flotante inferior derecho", assistant.includes("fixed bottom-5 right-5"));
check("CP03", "tamaños adaptables 48/56/64 px", ["size-12", "sm:size-14", "lg:size-16"].every((value) => assistant.includes(value)));
check("CP04", "toda el área es un botón accesible", assistant.includes("aria-label=\"Abrir Asistente FORECAST Towell\""));
check("CP05", "incluye tooltip descriptivo", assistant.includes("TooltipContent") && assistant.includes("Abrir Asistente FORECAST Towell"));
check("CP06", "abre sin navegación ni recarga", assistant.includes("handleOpenChange(true)") && !assistant.includes("location.href"));
check("CP07", "panel lateral derecho", assistant.includes("<SheetContent side=\"right\""));
check("CP08", "cierre y Escape delegados al diálogo accesible", assistant.includes("<Sheet open={open} onOpenChange={handleOpenChange}>"));
check("CP09", "encabezado de producto correcto", assistant.includes("Asistente FORECAST Towell") && !assistant.includes("ChatGPT"));
check("CP10", "estado inicial controlado", assistant.includes("Asistente en preparación para la siguiente fase"));
check("CP11", "modo mock sin análisis ficticio", service.includes("MockProvider") && service.includes("no se envían datos ni se generan análisis automáticos"));
check("CP12", "entrada, envío y multilinea", assistant.includes("Escribe tu pregunta…") && assistant.includes("event.shiftKey") && assistant.includes("Enviar mensaje"));
check("CP13", "contrato sendAssistantMessage", service.includes("export async function sendAssistantMessage"));
check("CP14", "proveedores desacoplados", service.includes("AssistantProvider") && service.includes("FutureAIProvider"));
check("CP15", "contexto gerencial completo", ["user", "role", "screen", "activeFilters", "chain", "category", "product", "color", "period"].every((value) => service.includes(`${value}:`)));
check("CP16", "ningún envío externo desde el asistente", !service.includes("fetch(") && !assistant.includes("fetch("));
check("CP17", "voz preparada pero oculta y deshabilitada", assistant.includes("FutureVoiceControls") && assistant.includes("disabled") && assistant.includes("className={enabled ? \"shrink-0\" : \"hidden\"}"));
check("CP18", "sin permisos de micrófono", !assistant.includes("getUserMedia") && !assistant.includes("mediaDevices"));
check("CP19", "fallback si falla el Lottie", assistant.includes("lottieFailed ? <AssistantMark") && lottieComponent.includes("data_failed"));
check("CP20", "historial sólo en estado React", assistant.includes("useState<ConversationMessage[]>") && !assistant.includes("localStorage"));
check("CP21", "banderas de fase explícitas", ["AI_ASSISTANT_MODE=mock", "AI_ASSISTANT_UI_ENABLED=true", "AI_ASSISTANT_API_ENABLED=false", "VOICE_ASSISTANT_ENABLED=false"].every((value) => env.includes(value)));
check("CP22", "visible sólo para gerencia autorizada", assistant.includes("!props.authorized || !props.uiEnabled") && page.includes("currentRole === \"manager\""));
check("CP23", "endpoint futuro reservado", route.includes("export async function POST") && route.includes("/assistant/message") === false);
check("CP24", "respuesta futura estandarizada", ["message", "status", "source", "actions", "metadata"].every((value) => route.includes(`${value}:`)));
check("CP25", "acciones preparadas pero no ejecutadas", service.includes("AssistantAction") && service.includes("actions: []"));
check("CP26", "logging técnico sin contenido del mensaje", assistant.includes("[ForecastAssistant]") && !assistant.includes("console.info(message"));
check("CP27", "carga diferida del reproductor", assistant.includes("dynamic(() => import") && lottieComponent.includes("lottie_light"));
check("CP28", "aislamiento con error boundary", shell.includes("ForecastAssistantErrorBoundary"));
check("CP29", "panel móvil completo y escritorio de 400 px", assistant.includes("w-full max-w-none") && assistant.includes("sm:max-w-[400px]"));
check("CP30", "dashboard y motores protegidos contra rediseño", [
  ["app/executive-dashboard.tsx", "AD141B67E0B306EFA347E116A5C6A54B9BC6AFB00C108BA7A0591A1586113D23"],
  ["app/forecast-engines-view.tsx", "441204099A5881D18770268A4D5887E3AF3E8BABF5A24105DAE8ED73921DA4EC"],
  ["app/statistical-engine-view.tsx", "F6761C62DB4F1405F6CBE643518233EF314FA95A074F9B6C0FA46FC0B7EA938F"],
  ["app/ml-engine-view.tsx", "791D9FF7E538295EDCBA93CF6740E03FD4C5B26B7AE58BE2C689445BD7AE25AA"],
  ["app/globals.css", "9886356242D4947780CC7E72551436FCED5E1BE2CC236C75D714E912A157D289"],
].every(([path, hash]) => sha256(path) === hash));

const failed = checks.filter((item) => !item.condition);
for (const item of checks) console.log(`${item.condition ? "PASS" : "FAIL"} ${item.id} ${item.description}`);
if (failed.length) {
  console.error(`\n${failed.length} comprobaciones fallaron.`);
  process.exit(1);
}
console.log(`\nPRD 08A verificado: ${checks.length}/${checks.length} comprobaciones aprobadas.`);
