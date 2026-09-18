"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, BellRing, Bot, CalendarDays, Check, ChevronRight, CircleAlert, Filter, SlidersHorizontal, Sparkles, TrendingDown, TrendingUp } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { toast } from "sonner";

type ModuleId = "inicio" | "captura" | "historico" | "motor" | "periodos" | "calidad" | "usuarios" | "auditoria";
type Range = "6M" | "1A" | "2A" | "Todo";
type SeriesKey = "client" | "towell" | "sale" | "order" | "delivery";
type Point = { period: string; label: string; phase: "history" | "current" | "future"; client: number | null; towell: number | null; sale: number | null; order: number | null; delivery: number | null; wape: number | null; p50?: number | null; p90?: number | null; p95?: number | null };

const base: Point[] = [
  ["2025-08","Ago 25","history",46800,47950,46100,49200,45100,10.1],
  ["2025-09","Sep 25","history",47500,48300,47200,50100,46300,8.9],
  ["2025-10","Oct 25","history",48900,49200,48100,50700,47600,7.8],
  ["2025-11","Nov 25","history",50100,50800,49500,52300,48800,9.3],
  ["2025-12","Dic 25","history",57900,56100,54800,58900,53900,11.6],
  ["2026-01","Ene 26","history",43800,44600,43100,45700,42500,8.4],
  ["2026-02","Feb 26","history",45200,46100,44700,47200,44000,7.2],
  ["2026-03","Mar 26","history",46300,47200,45900,48600,45100,6.8],
  ["2026-04","Abr 26","history",47100,48000,46500,49700,45800,7.4],
  ["2026-05","May 26","history",48600,48900,47700,50500,46900,8.1],
  ["2026-06","Jun 26","history",49200,50100,48800,51600,47900,7.7],
  ["2026-07","Jul 26","history",49700,50100,48250,51600,47400,8.6],
  ["2026-08","Ago 26","current",49200,50400,null,50800,46900,null],
  ["2026-09","Sep 26","current",48500,50100,49700,52000,48900,null],
  ["2026-10","Oct 26","future",48000,49300,null,null,null,null],
  ["2026-11","Nov 26","future",51000,50600,null,null,null,null],
  ["2026-12","Dic 26","future",58000,56400,null,null,null,null],
  ["2027-01","Ene 27","future",42000,44200,null,null,null,null],
  ["2027-02","Feb 27","future",45100,46200,null,null,null,null],
  ["2027-03","Mar 27","future",46800,47500,null,null,null,null],
  ["2027-04","Abr 27","future",47700,48300,null,null,null,null],
  ["2027-05","May 27","future",48900,49700,null,null,null,null],
  ["2027-06","Jun 27","future",50100,50900,null,null,null,null],
  ["2027-07","Jul 27","future",51200,51800,null,null,null,null],
  ["2027-08","Ago 27","future",49800,50700,null,null,null,null],
  ["2027-09","Sep 27","future",50600,51400,null,null,null,null],
].map(([period,label,phase,client,towell,sale,order,delivery,wape]) => ({ period,label,phase,client,towell,sale,order,delivery,wape,p50:towell,p90:towell ? Number(towell)*1.12 : null,p95:towell ? Number(towell)*1.2 : null } as Point));

const series: { key: SeriesKey; label: string; color: string; dash?: string }[] = [
  { key:"sale", label:"Venta", color:"#175cd3" },
  { key:"order", label:"Pedido", color:"#7c3aed" },
  { key:"delivery", label:"Entrega", color:"#0891b2" },
  { key:"client", label:"Fcst Cliente", color:"#f59e0b", dash:"5 4" },
  { key:"towell", label:"Fcst Towell", color:"#0f172a", dash:"7 4" },
];

const productOptions = ["Todos","Chocolate","Morado","Azul","Aqua","Gris","Beige","Rosa","Rojo","Negro","Navidad","Oxford"];
const colors = ["Todos","Chocolate","Morado","Azul","Aqua","Gris","Beige","Rosa","Rojo","Negro","Oxford"];
const factorByProduct: Record<string, number> = { Todos:1, Chocolate:.158, Morado:.164, Azul:.092, Aqua:.097, Gris:.061, Beige:.089, Rosa:.082, Rojo:.075, Negro:.071, Navidad:.058, Oxford:.053 };
const factorByCategory: Record<string, number> = { Todas:1, "Fendi Básica":.71, "Fendi Color":.19, "Fendi Temporada":.10 };
const fmt = new Intl.NumberFormat("es-MX", { maximumFractionDigits:0 });

function DashboardTooltip({ active, payload }: { active?: boolean; payload?: { payload: Point }[] }) {
  if (!active || !payload?.[0]) return null;
  const point = payload[0].payload;
  return <div className="min-w-52 rounded-xl border border-slate-200 bg-white p-3 shadow-xl"><p className="font-semibold text-slate-950">{point.label}</p><p className="mt-0.5 text-xs uppercase tracking-wide text-slate-400">{point.phase === "history" ? "Periodo cerrado" : point.phase === "current" ? "Periodo actual" : "Pronóstico"}</p><div className="mt-3 space-y-1.5">{series.map((item) => <div key={item.key} className="flex items-center justify-between gap-5 text-xs"><span className="flex items-center gap-2 text-slate-600"><span className="size-2 rounded-full" style={{background:item.color}}/>{item.label}</span><strong>{point[item.key] == null ? "Sin dato" : `${fmt.format(point[item.key]!)} pzas`}</strong></div>)}</div></div>;
}

function ExecutiveKpi({ label, value, detail, direction }: { label:string; value:string; detail:string; direction?:"up"|"down" }) {
  return <div className="min-w-[190px] border-r border-slate-200 px-5 py-4 last:border-r-0"><p className="text-sm font-medium text-slate-500">{label}</p><p className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">{value}</p><p className={`mt-2 flex items-center gap-1 text-xs font-medium ${direction === "up" ? "text-emerald-700" : direction === "down" ? "text-amber-700" : "text-slate-500"}`}>{direction === "up" && <TrendingUp className="size-3.5"/>}{direction === "down" && <TrendingDown className="size-3.5"/>}{detail}</p></div>;
}

export default function ExecutiveDashboard({ onGo, periodState }: { onGo:(id:ModuleId)=>void; periodState:string }) {
  const [category,setCategory] = useState("Todas");
  const [product,setProduct] = useState("Todos");
  const [color,setColor] = useState("Todos");
  const [range,setRange] = useState<Range>("2A");
  const [selectedPeriod,setSelectedPeriod] = useState("2026-09");
  const [visible,setVisible] = useState<Record<SeriesKey,boolean>>({client:true,towell:true,sale:true,order:true,delivery:true});
  const [compare,setCompare] = useState(false);
  const factor = factorByCategory[category] * factorByProduct[product] * (color === "Todos" ? 1 : .97);
  const scoped = useMemo(() => base.map((point) => ({...point, ...Object.fromEntries(series.map(({key}) => [key,point[key] == null ? null : Math.round(point[key]! * factor)]))})), [factor]);
  const chartData = useMemo(() => { const lengths:Record<Range,number>={"6M":18,"1A":24,"2A":26,"Todo":26}; return scoped.slice(-lengths[range]); },[scoped,range]);
  const current = scoped.find((point)=>point.period==="2026-09")!;
  const categoryWape = [{name:"Fendi Básica",value:6.8},{name:"Fendi Color",value:11.4},{name:"Fendi Temporada",value:17.2}];
  const selectedWape = category === "Todas" ? 8.6 : categoryWape.find((row)=>row.name===category)?.value ?? 8.6;
  const wapeData = scoped.filter((point)=>point.wape != null && point.period >= "2026-02").map((point)=>({period:point.label,wape:Number(Math.max(0,(point.wape ?? 0)+(selectedWape-8.6)).toFixed(1))}));
  const future = scoped.filter((point)=>point.phase==="future").slice(0,12);
  const toggle = (key:SeriesKey) => setVisible((state)=>({...state,[key]:!state[key]}));
  const applyCategory = (name:string) => { setCategory(name); setProduct("Todos"); setColor("Todos"); };

  return <div className="space-y-5 pb-20">
    <section className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between"><div><p className="text-xs font-bold uppercase tracking-[.16em] text-blue-700">Dashboard ejecutivo</p><h1 className="mt-1 text-3xl font-semibold tracking-[-.035em] text-slate-950">FORECAST Towell</h1><p className="mt-1 text-sm text-slate-500">Piloto seleccionado: <span className="font-semibold text-slate-700">FENDI BD</span></p></div><div className="flex items-center gap-2"><Badge variant="outline" className="border-slate-200 bg-white px-3 py-1.5 text-slate-700"><CalendarDays className="mr-1.5 size-3.5"/> Sep 2026</Badge><Badge variant="outline" className="border-emerald-200 bg-emerald-50 px-3 py-1.5 text-emerald-700">{periodState}</Badge><Button variant="outline" size="icon" aria-label="Notificaciones"><BellRing className="size-4"/></Button></div></section>

    <Card className="border-slate-200 shadow-sm"><CardContent className="p-4"><div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-700 md:hidden"><Filter className="size-4"/> Filtros del dashboard</div><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><FilterSelect label="Cadena / piloto" value="FENDI BD" options={["FENDI BD"]}/><FilterSelect label="Categoría" value={category} onChange={applyCategory} options={["Todas","Fendi Básica","Fendi Color","Fendi Temporada"]}/><FilterSelect label="Producto" value={product} onChange={(value)=>{setProduct(value);if(value!=="Todos")setColor(value)}} options={productOptions}/><FilterSelect label="Color" value={color} onChange={setColor} options={colors}/></div></CardContent></Card>

    <section className="overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-sm"><div className="grid min-w-[900px] grid-cols-5"><ExecutiveKpi label="Venta" value={`${fmt.format(current.sale!)} pzas`} detail="+4.8% vs periodo anterior" direction="up"/><ExecutiveKpi label="Pedido" value={`${fmt.format(current.order!)} pzas`} detail="+4.6% vs venta" direction="up"/><ExecutiveKpi label="Fcst Towell" value={`${fmt.format(current.towell!)} pzas`} detail="Diferencia vs venta: +0.8%"/><ExecutiveKpi label="WAPE" value={`${selectedWape.toFixed(1)}%`} detail="Último periodo cerrado"/><ExecutiveKpi label="Sesgo" value="−2.1%" detail="Ligera subestimación" direction="down"/></div></section>

    <Card className="overflow-hidden border-slate-200 bg-white shadow-sm"><CardHeader className="border-b border-slate-100 pb-4"><div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between"><div><CardTitle className="text-base">Histórico · hoy · forecast</CardTitle><p className="mt-1 text-sm text-slate-500">Real hasta Jul-26 · periodo actual Sep-26 · horizonte móvil de 12 meses</p></div><div className="flex flex-wrap items-center gap-2"><div className="flex rounded-lg border border-slate-200 bg-slate-50 p-1">{(["6M","1A","2A","Todo"] as Range[]).map((item)=><button key={item} onClick={()=>setRange(item)} className={`rounded-md px-3 py-1.5 text-xs font-semibold transition ${range===item?"bg-white text-blue-700 shadow-sm":"text-slate-500 hover:text-slate-800"}`}>{item}</button>)}</div><Badge variant="outline" className="h-8 border-violet-200 bg-violet-50 text-violet-700">+12M futuro</Badge><button onClick={()=>setCompare(!compare)} className={`inline-flex h-8 items-center gap-2 rounded-lg border px-3 text-xs font-semibold transition ${compare?"border-blue-300 bg-blue-50 text-blue-700":"border-slate-200 text-slate-600"}`}><SlidersHorizontal className="size-3.5"/> Comparar motores {compare&&<Check className="size-3.5"/>}</button></div></div><div className="mt-4 flex flex-wrap gap-2">{series.map((item)=><button key={item.key} aria-pressed={visible[item.key]} onClick={()=>toggle(item.key)} className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium transition ${visible[item.key]?"border-slate-200 bg-white text-slate-700":"border-slate-100 bg-slate-50 text-slate-400 line-through"}`}><span className="size-2.5 rounded-full" style={{background:item.color}}/>{item.label}</button>)}</div></CardHeader><CardContent className="p-3 md:p-6"><div className="mb-2 grid grid-cols-[1fr_auto_1fr] items-center text-[11px] font-bold uppercase tracking-[.14em] text-slate-400"><span>Histórico real</span><span className="px-3 text-blue-700">Hoy</span><span className="text-right">Forecast</span></div><div className="h-[430px] min-h-[360px] w-full"><ResponsiveContainer width="100%" height="100%" minWidth={0}><LineChart data={chartData} margin={{top:8,right:16,left:0,bottom:10}} onClick={(state)=>state?.activeLabel&&setSelectedPeriod(String(state.activeLabel))}><CartesianGrid vertical={false} stroke="#e2e8f0"/><ReferenceArea x1="2026-10" x2="2027-09" fill="#f5f3ff" fillOpacity={.72}/><ReferenceLine x="2026-09" stroke="#2563eb" strokeWidth={1.5} label={{value:"SEP 2026",position:"insideTopRight",fill:"#1d4ed8",fontSize:11}}/><ReferenceLine x={selectedPeriod} stroke="#0f172a" strokeDasharray="3 4"/><XAxis dataKey="period" tickFormatter={(value)=>String(value).replace("-","/")} tick={{fontSize:11,fill:"#64748b"}} minTickGap={24}/><YAxis tickFormatter={(value)=>`${Math.round(Number(value)/1000)}k`} tick={{fontSize:11,fill:"#64748b"}} width={46}/><Tooltip content={<DashboardTooltip/>}/>{series.map((item)=>visible[item.key]&&<Line key={item.key} type="monotone" dataKey={item.key} name={item.label} stroke={item.color} strokeWidth={item.key==="sale"||item.key==="towell"?2.7:1.9} strokeDasharray={item.dash} dot={false} activeDot={{r:5}} connectNulls={false}/>)}</LineChart></ResponsiveContainer></div><div className="mt-2 flex items-center justify-between border-t border-slate-100 pt-3 text-xs text-slate-500"><span>Los espacios sin dato quedan interrumpidos; un cero confirmado sí se dibuja en 0.</span><button onClick={()=>onGo("historico")} className="inline-flex items-center font-semibold text-blue-700">Profundizar en histórico <ChevronRight className="size-3.5"/></button></div></CardContent></Card>

    <section className="grid gap-5 xl:grid-cols-2"><Card className="border-slate-200 shadow-sm"><CardHeader><CardTitle className="text-base">Evolución del WAPE</CardTitle><p className="text-sm text-slate-500">Calculado automáticamente contra Venta cerrada</p></CardHeader><CardContent><div className="h-64"><ResponsiveContainer width="100%" height="100%" minWidth={0}><LineChart data={wapeData} margin={{top:8,right:12,left:-10,bottom:0}}><CartesianGrid vertical={false} stroke="#e2e8f0"/><XAxis dataKey="period" tick={{fontSize:11,fill:"#64748b"}}/><YAxis domain={[0,20]} unit="%" tick={{fontSize:11,fill:"#64748b"}}/><Tooltip formatter={(value)=>`${value}%`}/><ReferenceLine y={10} stroke="#f59e0b" strokeDasharray="4 4"/><Line type="monotone" dataKey="wape" name="WAPE" stroke="#175cd3" strokeWidth={2.5} dot={{r:3,fill:"#175cd3"}}/></LineChart></ResponsiveContainer></div></CardContent></Card><Card className="border-slate-200 shadow-sm"><CardHeader><CardTitle className="text-base">WAPE por categoría</CardTitle><p className="text-sm text-slate-500">Selecciona una barra para filtrar todo el dashboard</p></CardHeader><CardContent><div className="h-64"><ResponsiveContainer width="100%" height="100%" minWidth={0}><BarChart data={categoryWape} layout="vertical" margin={{top:8,right:30,left:26,bottom:0}} onClick={(state)=>state?.activeLabel&&applyCategory(String(state.activeLabel))}><CartesianGrid horizontal={false} stroke="#e2e8f0"/><XAxis type="number" domain={[0,22]} unit="%" tick={{fontSize:11,fill:"#64748b"}}/><YAxis type="category" dataKey="name" width={105} tick={{fontSize:11,fill:"#475569"}}/><Tooltip formatter={(value)=>`${value}%`}/><Bar dataKey="value" name="WAPE" fill="#7c3aed" radius={[0,7,7,0]} cursor="pointer"/></BarChart></ResponsiveContainer></div></CardContent></Card></section>

    <Card className="border-slate-200 shadow-sm"><CardHeader className="flex flex-row items-center justify-between"><div><CardTitle className="text-base">Fluctuaciones detectadas</CardTitle><p className="mt-1 text-sm text-slate-500">Sólo excepciones que requieren análisis</p></div><Badge variant="outline" className="border-amber-200 bg-amber-50 text-amber-700">3 abiertas</Badge></CardHeader><CardContent className="grid gap-3 lg:grid-cols-3"><ExceptionItem severity="Relevante" icon={<AlertTriangle/>} title={product === "Todos" ? "Azul" : product} copy="Venta 28% arriba de su comportamiento esperado."/><ExceptionItem severity="Atención" icon={<CircleAlert/>} title={category === "Todas" ? "Fendi Temporada" : category} copy={`WAPE del filtro seleccionado se ubica en ${selectedWape.toFixed(1)}%.`}/><ExceptionItem severity="Atención" icon={<Sparkles/>} title={color === "Todos" ? "Chocolate" : color} copy="Fcst Cliente y Fcst Towell superan la diferencia histórica."/></CardContent></Card>

    <Card className="border-slate-200 shadow-sm"><CardHeader className="flex flex-row items-center justify-between"><div><CardTitle className="text-base">Pronóstico 12 meses</CardTitle><p className="mt-1 text-sm text-slate-500">La historia conserva la versión conocida en cada cierre; el futuro no se rellena con ceros.</p></div><Button variant="outline" size="sm" onClick={()=>onGo("motor")}>Ver modelo <ChevronRight/></Button></CardHeader><CardContent className="p-0"><div className="overflow-x-auto"><Table className="min-w-[900px]"><TableHeader><TableRow className="bg-slate-50"><TableHead className="sticky left-0 z-10 bg-slate-50 font-semibold">Mes</TableHead><TableHead>Fcst Cliente</TableHead><TableHead>Fcst Towell</TableHead><TableHead>Pedido</TableHead><TableHead>Venta</TableHead><TableHead>Entrega</TableHead><TableHead>WAPE</TableHead></TableRow></TableHeader><TableBody>{future.map((point)=><TableRow key={point.period}><TableCell className="sticky left-0 bg-white font-semibold">{point.label}</TableCell><ValueCell value={point.client}/><ValueCell value={point.towell} accent/><ValueCell value={point.order}/><ValueCell value={point.sale}/><ValueCell value={point.delivery}/><TableCell className="text-slate-400">—</TableCell></TableRow>)}</TableBody></Table></div></CardContent></Card>

    <section className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm md:flex-row md:items-center"><div className="flex items-center gap-3 border-b border-slate-100 pb-3 md:border-b-0 md:border-r md:pb-0 md:pr-5"><div className="grid size-10 place-items-center rounded-xl bg-blue-50 text-blue-700"><CalendarDays className="size-5"/></div><div><p className="text-sm font-semibold">Periodo Sep-26</p><p className="text-xs text-slate-500">70% completo · {periodState}</p></div></div><div className="flex-1 text-sm text-slate-600"><strong className="text-slate-950">Pendientes del periodo</strong><span className="ml-3">Pedido 2 · Venta 3 · Entrega 1 · Fcst Cliente 3</span></div><Button variant="outline" onClick={()=>onGo("periodos")}>Revisar periodo <ChevronRight/></Button></section>

    <button aria-label="Abrir Asistente IA" onClick={()=>toast("Asistente IA preparado",{description:"La interacción gerencial por voz se habilitará en una fase posterior."})} className="fixed bottom-6 right-6 z-40 flex items-center gap-2 rounded-full bg-slate-950 px-4 py-3 text-sm font-semibold text-white shadow-xl transition hover:-translate-y-0.5 hover:bg-blue-700"><Bot className="size-5"/><span className="hidden sm:inline">Asistente IA</span></button>
  </div>;
}

function FilterSelect({label,value,options,onChange}: {label:string;value:string;options:string[];onChange?:(value:string)=>void}) { return <label className="space-y-1.5"><span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</span><Select value={value} onValueChange={onChange}><SelectTrigger className="w-full bg-white"><SelectValue/></SelectTrigger><SelectContent>{options.map((option)=><SelectItem key={option} value={option}>{option}</SelectItem>)}</SelectContent></Select></label>; }
function ValueCell({value,accent=false}:{value:number|null;accent?:boolean}) { return <TableCell className={value==null?"text-slate-400":accent?"font-semibold text-violet-700":"text-slate-700"}>{value==null?"—":fmt.format(value)}</TableCell>; }
function ExceptionItem({severity,icon,title,copy}:{severity:string;icon:React.ReactNode;title:string;copy:string}) { return <button className="group flex gap-3 rounded-xl border border-slate-200 p-4 text-left transition hover:border-amber-300 hover:bg-amber-50/40"><div className="grid size-9 shrink-0 place-items-center rounded-xl bg-amber-50 text-amber-700 [&>svg]:size-4">{icon}</div><div><div className="flex items-center gap-2"><p className="font-semibold text-slate-950">{title}</p><span className="text-[11px] font-bold uppercase tracking-wide text-amber-700">{severity}</span></div><p className="mt-1 text-sm leading-5 text-slate-600">{copy}</p></div></button>; }
