"use client";

import { useState } from "react";
import { BrainCircuit, GitCompareArrows, Sigma } from "lucide-react";
import { Button } from "@/components/ui/button";
import StatisticalEngineView from "./statistical-engine-view";
import MLEngineView from "./ml-engine-view";

export default function ForecastEnginesView({supabaseConfigured}:{supabaseConfigured:boolean}) {
  const [tab,setTab]=useState<"statistical"|"ml">("statistical");
  return <div><div className="mb-6 flex flex-wrap gap-2 rounded-xl border border-slate-200 bg-white p-2 shadow-sm"><Button variant={tab==="statistical"?"default":"ghost"} onClick={()=>setTab("statistical")}><Sigma/> Motor Estadístico</Button><Button variant={tab==="ml"?"default":"ghost"} onClick={()=>setTab("ml")}><BrainCircuit/> Motor Machine Learning</Button><div className="ml-auto hidden items-center gap-2 px-3 text-xs text-slate-500 md:flex"><GitCompareArrows className="size-4"/> Motores paralelos · mismo corte</div></div>{tab==="statistical"?<StatisticalEngineView supabaseConfigured={supabaseConfigured}/>:<MLEngineView supabaseConfigured={supabaseConfigured}/>}</div>;
}
