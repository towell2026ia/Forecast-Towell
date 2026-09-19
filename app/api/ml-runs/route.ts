import { NextResponse } from "next/server";

export async function POST(request: Request) {
  const url=process.env.SUPABASE_URL, key=process.env.SUPABASE_SERVICE_ROLE_KEY;
  if(!url||!key) return NextResponse.json({error:"supabase_not_configured"},{status:503});
  const authorization=request.headers.get("authorization");
  if(!authorization?.toLowerCase().startsWith("bearer ")) return NextResponse.json({error:"authentication_required"},{status:401});
  const body=await request.json() as {target?:unknown};
  if(body.target!=="Venta"&&body.target!=="Pedido") return NextResponse.json({error:"invalid_target"},{status:400});
  const response=await fetch(`${url}/rest/v1/rpc/request_ml_training`,{method:"POST",headers:{apikey:key,Authorization:authorization,"content-type":"application/json"},body:JSON.stringify({p_target:body.target})});
  if(!response.ok) return NextResponse.json({error:"queue_failed"},{status:502});
  return NextResponse.json({run_id:await response.json()},{status:202});
}
