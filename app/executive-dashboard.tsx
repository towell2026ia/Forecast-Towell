"use client";

import { useState } from "react";
import { AlertTriangle, BellRing, BrainCircuit, CalendarDays, Check, ChevronRight, CircleAlert, Filter, SlidersHorizontal, TrendingDown, TrendingUp } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import statisticalPayload from "./data/forecast-demo.json";
import dashboardPayload from "./data/fendi-dashboard.json";
import ensemblePayload from "./data/ensemble-demo.json";

type ModuleId = "inicio" | "captura" | "historico" | "motor" | "periodos" | "calidad" | "usuarios" | "auditoria";
type Range = "6M" | "1A" | "2A" | "Todo";
type SeriesKey = "client" | "towell" | "sale" | "order" | "delivery";
type Point = { period: string; label: string; phase: "history" | "future"; client: number | null; towell: number | null; statistical: number | null; ml: number | null; sale: number | null; order: number | null; delivery: number | null; inventory?: number | null; wape: number | null; p50?: number | null; p90?: number | null; p95?: number | null };
const statData=statisticalPayload as {series:{series_id:string;target:string;winner?:string;wape?:number;bias?:number;forecast?:{period:string;forecast:number|null}[]}[]};
const ensembleData=ensemblePayload as {selection:{decision:string;official:{strategy:string;wape:number;bias:number};incumbent:{strategy:string;wape:number}};publication:{authorized_promotion:boolean};forecast_towell:{series_id:string;period:string;value:number;statistical:number;ml:number|null;probability:{p50:number;p90:number;p95:number}}[]};
const dashboardData=dashboardPayload as {scope:string;cutoff:string;history:{period:string;client:number;towell:number;sale:number;order:number;delivery:number;inventory:number;wape_reference:number|null}[];audit:{source_rows:number;products:number;selection:string;screenshot_control:string}};
const statVenta=statData.series.find((row)=>row.series_id==="total-fendi-bd"&&row.target==="Venta");
const statPedido=statData.series.find((row)=>row.series_id==="total-fendi-bd"&&row.target==="Pedido");
const finalForecast=ensembleData.forecast_towell.filter((row)=>row.series_id==="total-fendi-bd");
const monthNames=["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"];
const periodLabel=(period:string)=>{const [year,month]=period.split("-").map(Number);return `${monthNames[month-1]} ${String(year).slice(-2)}`};
const base: Point[] = [
  ...dashboardData.history.map((row)=>({period:row.period,label:periodLabel(row.period),phase:"history" as const,client:row.client,towell:row.towell,statistical:null,ml:null,sale:row.sale,order:row.order,delivery:row.delivery,inventory:row.inventory,wape:row.wape_reference,p50:row.towell,p90:row.towell*1.12,p95:row.towell*1.2})),
  ...finalForecast.map((row)=>({period:row.period,label:periodLabel(row.period),phase:"future" as const,client:null,towell:row.value,statistical:row.statistical,ml:row.ml,sale:null,order:statPedido?.forecast?.find((item)=>item.period===row.period)?.forecast??null,delivery:null,wape:null,p50:row.probability.p50,p90:row.probability.p90,p95:row.probability.p95})),
];

const series: { key: SeriesKey; label: string; color: string; dash?: string }[] = [
  { key:"sale", label:"Venta", color:"#175cd3" },
  { key:"order", label:"Pedido", color:"#7c3aed" },
  { key:"delivery", label:"Entrega", color:"#0891b2" },
  { key:"client", label:"Fcst Cliente", color:"#f59e0b", dash:"5 4" },
  { key:"towell", label:"Fcst Towell", color:"#0f172a", dash:"7 4" },
];

const productOptions = ["Todos"];
const colors = ["Todos"];
const fmt = new Intl.NumberFormat("es-MX", { maximumFractionDigits:0 });

function DashboardTooltip({ active, payload }: { active?: boolean; payload?: { payload: Point }[] }) {
  if (!active || !payload?.[0]) return null;
  const point = payload[0].payload;
  const futureRows = [
    ["Forecast Towell final", point.towell, "#0f172a"],
    ["Baseline estadístico", point.statistical, "#64748b"],
    ["Machine Learning", point.ml, "#c026d3"],
    ["Pedido previsto", point.order, "#7c3aed"],
  ] as const;
  return <div className="min-w-60 rounded-xl border border-slate-200 bg-white p-3 shadow-xl"><p className="font-semibold text-slate-950">{point.label}</p><p className="mt-0.5 text-xs uppercase tracking-wide text-slate-400">{point.phase === "history" ? "Periodo cerrado" : "Pronóstico del modelo"}</p><div className="mt-3 space-y-1.5">{point.phase === "history" ? series.map((item) => <div key={item.key} className="flex items-center justify-between gap-5 text-xs"><span className="flex items-center gap-2 text-slate-600"><span className="size-2 rounded-full" style={{background:item.color}}/>{item.label}</span><strong>{fmt.format(point[item.key] ?? 0)} pzas</strong></div>) : futureRows.map(([label,value,color]) => value == null ? null : <div key={label} className="flex items-center justify-between gap-5 text-xs"><span className="flex items-center gap-2 text-slate-600"><span className="size-2 rounded-full" style={{background:color}}/>{label}</span><strong>{fmt.format(value)} pzas</strong></div>)}</div></div>;
}

function ExecutiveKpi({ label, value, detail, direction }: { label:string; value:string; detail:string; direction?:"up"|"down" }) {
  return <div className="min-w-[190px] border-r border-slate-200 px-5 py-4 last:border-r-0"><p className="text-sm font-medium text-slate-500">{label}</p><p className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">{value}</p><p className={`mt-2 flex items-center gap-1 text-xs font-medium ${direction === "up" ? "text-emerald-700" : direction === "down" ? "text-amber-700" : "text-slate-500"}`}>{direction === "up" && <TrendingUp className="size-3.5"/>}{direction === "down" && <TrendingDown className="size-3.5"/>}{detail}</p></div>;
}

export default function ExecutiveDashboard({ onGo, periodState }: { onGo:(id:ModuleId)=>void; periodState:string }) {
  const [category,setCategory] = useState("Todas");
  const [product,setProduct] = useState("Todos");
  const [color,setColor] = useState("Todos");
  const [range,setRange] = useState<Range>("2A");
  const [selectedPeriod,setSelectedPeriod] = useState(dashboardData.cutoff);
  const [visible,setVisible] = useState<Record<SeriesKey,boolean>>({client:true,towell:true,sale:true,order:true,delivery:true});
  const [compare,setCompare] = useState(false);
  const scoped = base;
  const lengths:Record<Range,number>={"6M":18,"1A":24,"2A":31,"Todo":31};
  const chartData = scoped.slice(-lengths[range]);
  const current = scoped.find((point)=>point.period===dashboardData.cutoff)!;
  const selectedWape = ensembleData.selection.official.wape;
  const categoryWape = [{name:"FENDI BD",value:selectedWape}];
  const wapeData = scoped.filter((point)=>point.wape != null && point.period >= "2026-02").map((point)=>({period:point.label,wape:point.wape}));
  const future = scoped.filter((point)=>point.phase==="future").slice(0,12);
  const toggle = (key:SeriesKey) => setVisible((state)=>({...state,[key]:!state[key]}));
  const applyCategory = (name:string) => { setCategory(name==="FENDI BD"?"Todas":name); setProduct("Todos"); setColor("Todos"); };
  const orderGap=current.sale?100*(current.order!-current.sale)/current.sale:0;
  const towellGap=current.sale?100*(current.towell!-current.sale)/current.sale:0;
  const orderVsTowell=current.towell?100*(current.order!-current.towell)/current.towell:0;

  return <div className="space-y-5 pb-20">
    <section className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between"><div><p className="text-xs font-bold uppercase tracking-[.16em] text-blue-700">Dashboard ejecutivo</p><h1 className="mt-1 text-3xl font-semibold tracking-[-.035em] text-slate-950">FORECAST Towell</h1><p className="mt-1 text-sm text-slate-500">Universo auditado: <span className="font-semibold text-slate-700">Walmart · familia FENDI</span></p></div><div className="flex items-center gap-2"><Badge variant="outline" className="border-slate-200 bg-white px-3 py-1.5 text-slate-700"><CalendarDays className="mr-1.5 size-3.5"/> Corte Jul 2026</Badge><Badge variant="outline" className="border-emerald-200 bg-emerald-50 px-3 py-1.5 text-emerald-700">{periodState}</Badge><Button variant="outline" size="icon" aria-label="Notificaciones"><BellRing className="size-4"/></Button></div></section>

    <Card className="border-slate-200 shadow-sm"><CardContent className="p-4"><div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-700 md:hidden"><Filter className="size-4"/> Alcance del dashboard</div><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><FilterSelect label="Cadena / piloto" value="FENDI BD" options={["FENDI BD"]}/><FilterSelect label="Categoría" value={category} onChange={applyCategory} options={["Todas"]}/><FilterSelect label="Producto" value={product} onChange={setProduct} options={productOptions}/><FilterSelect label="Color" value={color} onChange={setColor} options={colors}/></div><p className="mt-3 text-xs text-slate-500">{dashboardData.audit.selection} · {dashboardData.audit.products} productos trazados.</p></CardContent></Card>

    <section className="overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-sm"><div className="grid min-w-[900px] grid-cols-5"><ExecutiveKpi label="Venta Jul-26" value={`${fmt.format(current.sale!)} pzas`} detail="Real cerrado"/><ExecutiveKpi label="Pedido Jul-26" value={`${fmt.format(current.order!)} pzas`} detail={`${orderGap>=0?"+":""}${orderGap.toFixed(1)}% vs venta`} direction={orderGap>=0?"up":"down"}/><ExecutiveKpi label="Fcst Towell Jul-26" value={`${fmt.format(current.towell!)} pzas`} detail={`${towellGap>=0?"+":""}${towellGap.toFixed(1)}% vs venta`}/><ExecutiveKpi label="WAPE Forecast Towell" value={`${selectedWape.toFixed(1)}%`} detail="ML validado · backtest alineado"/><ExecutiveKpi label="Mejora vs baseline" value={`${(ensembleData.selection.incumbent.wape-selectedWape).toFixed(1)} pts`} detail={`Baseline ${ensembleData.selection.incumbent.wape.toFixed(1)}%`} direction="down"/></div></section>

    <Card className="overflow-hidden border-slate-200 bg-white shadow-sm">
      <CardHeader className="border-b border-slate-100 pb-4">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between"><div><CardTitle className="text-base">Real y Forecast Towell</CardTitle><p className="mt-1 text-sm text-slate-500">Real cerrado hasta Jul-26 · forecast ML Ago-26 a Jul-27</p></div><div className="flex flex-wrap items-center gap-2"><div className="flex rounded-lg border border-slate-200 bg-slate-50 p-1">{(["6M","1A","2A","Todo"] as Range[]).map((item)=><button key={item} onClick={()=>setRange(item)} className={`rounded-md px-3 py-1.5 text-xs font-semibold transition ${range===item?"bg-white text-blue-700 shadow-sm":"text-slate-500 hover:text-slate-800"}`}>{item}</button>)}</div><Badge variant="outline" className="h-8 border-violet-200 bg-violet-50 text-violet-700">ML final · +12M</Badge><button onClick={()=>setCompare(!compare)} className={`inline-flex h-8 items-center gap-2 rounded-lg border px-3 text-xs font-semibold transition ${compare?"border-blue-300 bg-blue-50 text-blue-700":"border-slate-200 text-slate-600"}`}><SlidersHorizontal className="size-3.5"/> Comparar baseline {compare&&<Check className="size-3.5"/>}</button></div></div>
        <div className="mt-4 flex flex-wrap gap-2">{series.map((item)=><button key={item.key} aria-pressed={visible[item.key]} onClick={()=>toggle(item.key)} className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium transition ${visible[item.key]?"border-slate-200 bg-white text-slate-700":"border-slate-100 bg-slate-50 text-slate-400 line-through"}`}><span className="size-2.5 rounded-full" style={{background:item.color}}/>{item.label}</button>)}{compare&&<Badge variant="outline" className="border-slate-200 bg-slate-50 text-slate-700"><span className="mr-2 size-2 rounded-full bg-slate-500"/>Baseline estadístico</Badge>}</div>
        {compare&&<div className="mt-4 grid gap-2 rounded-xl bg-slate-50 p-3 text-xs sm:grid-cols-3"><span><strong>Baseline alineado:</strong> {ensembleData.selection.incumbent.wape.toFixed(1)}%</span><span><strong>Forecast Towell ML:</strong> {selectedWape.toFixed(1)}%</span><span><strong>Decisión:</strong> ML promovido por menor error en el total FENDI.</span></div>}
      </CardHeader>
      <CardContent className="p-3 md:p-6"><div className="mb-2 grid grid-cols-[1fr_auto_1fr] items-center text-[11px] font-bold uppercase tracking-[.14em] text-slate-400"><span>Real y forecast histórico</span><span className="px-3 text-blue-700">Corte Jul-26</span><span className="text-right">Forecast ML</span></div><div className="h-[430px] min-h-[360px] w-full"><ResponsiveContainer width="100%" height="100%" minWidth={0}><LineChart data={chartData} margin={{top:8,right:16,left:0,bottom:10}} onClick={(state)=>state?.activeLabel&&setSelectedPeriod(String(state.activeLabel))}><CartesianGrid vertical={false} stroke="#e2e8f0"/><ReferenceArea x1="2026-08" x2="2027-07" fill="#f5f3ff" fillOpacity={.72}/><ReferenceLine x={dashboardData.cutoff} stroke="#2563eb" strokeWidth={1.5} label={{value:"JUL 2026",position:"insideTopRight",fill:"#1d4ed8",fontSize:11}}/><ReferenceLine x={selectedPeriod} stroke="#0f172a" strokeDasharray="3 4"/><XAxis dataKey="period" tickFormatter={(value)=>String(value).replace("-","/")} tick={{fontSize:11,fill:"#64748b"}} minTickGap={24}/><YAxis tickFormatter={(value)=>`${Math.round(Number(value)/1000)}k`} tick={{fontSize:11,fill:"#64748b"}} width={46}/><Tooltip content={<DashboardTooltip/>}/>{series.map((item)=>visible[item.key]&&<Line key={item.key} type="monotone" dataKey={item.key} name={item.label} stroke={item.color} strokeWidth={item.key==="sale"||item.key==="towell"?2.7:1.9} strokeDasharray={item.dash} dot={false} activeDot={{r:5}} connectNulls={false}/>)}{compare&&<Line type="monotone" dataKey="statistical" name="Baseline estadístico" stroke="#64748b" strokeWidth={2.2} strokeDasharray="3 5" dot={false} connectNulls={false}/>}</LineChart></ResponsiveContainer></div><div className="mt-2 flex items-center justify-between border-t border-slate-100 pt-3 text-xs text-slate-500"><span>El futuro es el ML autorizado; el baseline sólo aparece al activar la comparación.</span><button onClick={()=>onGo("historico")} className="inline-flex items-center font-semibold text-blue-700">Profundizar en histórico <ChevronRight className="size-3.5"/></button></div></CardContent>
    </Card>

    <section className="grid gap-5 xl:grid-cols-2"><Card className="border-slate-200 shadow-sm"><CardHeader><CardTitle className="text-base">Error del Fcst Towell de referencia</CardTitle><p className="text-sm text-slate-500">Diferencia absoluta mensual contra Venta cerrada</p></CardHeader><CardContent><div className="h-64"><ResponsiveContainer width="100%" height="100%" minWidth={0}><LineChart data={wapeData} margin={{top:8,right:12,left:-10,bottom:0}}><CartesianGrid vertical={false} stroke="#e2e8f0"/><XAxis dataKey="period" tick={{fontSize:11,fill:"#64748b"}}/><YAxis unit="%" tick={{fontSize:11,fill:"#64748b"}}/><Tooltip formatter={(value)=>`${value}%`}/><ReferenceLine y={10} stroke="#f59e0b" strokeDasharray="4 4"/><Line type="monotone" dataKey="wape" name="Error absoluto" stroke="#175cd3" strokeWidth={2.5} dot={{r:3,fill:"#175cd3"}}/></LineChart></ResponsiveContainer></div></CardContent></Card><Card className="border-slate-200 shadow-sm"><CardHeader><CardTitle className="text-base">Backtesting consolidado</CardTitle><p className="text-sm text-slate-500">Motor estadístico · objetivo Venta · universo FENDI BD</p></CardHeader><CardContent><div className="h-64"><ResponsiveContainer width="100%" height="100%" minWidth={0}><BarChart data={categoryWape} layout="vertical" margin={{top:8,right:30,left:26,bottom:0}}><CartesianGrid horizontal={false} stroke="#e2e8f0"/><XAxis type="number" unit="%" tick={{fontSize:11,fill:"#64748b"}}/><YAxis type="category" dataKey="name" width={105} tick={{fontSize:11,fill:"#475569"}}/><Tooltip formatter={(value)=>`${value}%`}/><Bar dataKey="value" name="WAPE" fill="#7c3aed" radius={[0,7,7,0]}/></BarChart></ResponsiveContainer></div></CardContent></Card></section>

    <Card className="border-slate-200 shadow-sm"><CardHeader className="flex flex-row items-center justify-between"><div><CardTitle className="text-base">Alertas e interpretación de modelos</CardTitle><p className="mt-1 text-sm text-slate-500">Señales calculadas por los motores; no se muestran controles de captura como alertas.</p></div><Badge variant="outline" className="border-violet-200 bg-violet-50 text-violet-700">3 señales</Badge></CardHeader><CardContent className="grid gap-3 lg:grid-cols-3"><ExceptionItem severity="ML validado" icon={<BrainCircuit/>} title="Forecast final dinámico" copy={`El ML fue promovido en el total FENDI: WAPE ${selectedWape.toFixed(1)}% contra ${ensembleData.selection.incumbent.wape.toFixed(1)}% del baseline alineado.`}/><ExceptionItem severity="Atención" icon={<AlertTriangle/>} title="Pedido sobre Forecast Towell" copy={`${fmt.format(current.order!)} pzas: ${orderVsTowell.toFixed(1)}% sobre el Forecast Towell. Pedido mide abastecimiento solicitado, no demanda esperada; revisar cobertura, anticipación o rezago.`}/><ExceptionItem severity="Estadístico" icon={<CircleAlert/>} title={`Baseline ${statVenta?.winner??"—"}`} copy="El baseline dejó de ser Naive al separar los meses previos al arranque. Conserva movimiento mensual y sirve como control contra ML."/></CardContent></Card>

    <Card className="border-slate-200 shadow-sm"><CardHeader className="flex flex-row items-center justify-between"><div><CardTitle className="text-base">Forecast Towell final · 12 meses</CardTitle><p className="mt-1 text-sm text-slate-500">El forecast final usa ML validado; el baseline estadístico y Pedido permanecen como comparadores separados.</p></div><Button variant="outline" size="sm" onClick={()=>onGo("motor")}>Ver modelos <ChevronRight/></Button></CardHeader><CardContent className="p-0"><div className="overflow-x-auto"><Table className="min-w-[760px]"><TableHeader><TableRow className="bg-slate-50"><TableHead className="sticky left-0 z-10 bg-slate-50 font-semibold">Mes</TableHead><TableHead>Forecast Towell final</TableHead><TableHead>Baseline estadístico</TableHead><TableHead>Pedido previsto</TableHead><TableHead>Pedido vs Towell</TableHead></TableRow></TableHeader><TableBody>{future.map((point)=><TableRow key={point.period}><TableCell className="sticky left-0 bg-white font-semibold">{point.label}</TableCell><ValueCell value={point.towell} accent/><ValueCell value={point.statistical}/><ValueCell value={point.order}/><TableCell className="font-semibold text-amber-700">{point.towell&&point.order?`${((point.order-point.towell)/point.towell*100)>=0?"+":""}${((point.order-point.towell)/point.towell*100).toFixed(1)}%`:"—"}</TableCell></TableRow>)}</TableBody></Table></div></CardContent></Card>

    <section className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm md:flex-row md:items-center"><div className="flex items-center gap-3 border-b border-slate-100 pb-3 md:border-b-0 md:border-r md:pb-0 md:pr-5"><div className="grid size-10 place-items-center rounded-xl bg-blue-50 text-blue-700"><CalendarDays className="size-5"/></div><div><p className="text-sm font-semibold">Corte Jul-26</p><p className="text-xs text-slate-500">11 productos modelados · {periodState}</p></div></div><div className="flex-1 text-sm text-slate-600"><strong className="text-slate-950">Siguiente horizonte</strong><span className="ml-3">Ago-26 · Forecast Towell ML {fmt.format(future[0]?.towell??0)} · Pedido previsto {fmt.format(future[0]?.order??0)}</span></div><Button variant="outline" onClick={()=>onGo("periodos")}>Revisar periodo <ChevronRight/></Button></section>

  </div>;
}

function FilterSelect({label,value,options,onChange}: {label:string;value:string;options:string[];onChange?:(value:string)=>void}) { return <label className="space-y-1.5"><span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</span><Select value={value} onValueChange={onChange}><SelectTrigger className="w-full bg-white"><SelectValue/></SelectTrigger><SelectContent>{options.map((option)=><SelectItem key={option} value={option}>{option}</SelectItem>)}</SelectContent></Select></label>; }
function ValueCell({value,accent=false}:{value:number|null;accent?:boolean}) { return <TableCell className={value==null?"text-slate-400":accent?"font-semibold text-violet-700":"text-slate-700"}>{value==null?"—":fmt.format(value)}</TableCell>; }
function ExceptionItem({severity,icon,title,copy}:{severity:string;icon:React.ReactNode;title:string;copy:string}) { return <button className="group flex gap-3 rounded-xl border border-slate-200 p-4 text-left transition hover:border-amber-300 hover:bg-amber-50/40"><div className="grid size-9 shrink-0 place-items-center rounded-xl bg-amber-50 text-amber-700 [&>svg]:size-4">{icon}</div><div><div className="flex items-center gap-2"><p className="font-semibold text-slate-950">{title}</p><span className="text-[11px] font-bold uppercase tracking-wide text-amber-700">{severity}</span></div><p className="mt-1 text-sm leading-5 text-slate-600">{copy}</p></div></button>; }
