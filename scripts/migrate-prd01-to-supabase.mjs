import { readFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const base = path.resolve(process.cwd(), "..");
const dataDir = path.join(base, "outputs", "prd01_fendi_bd", "data");
const url = process.env.SUPABASE_URL;
const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
if (!url || !key) throw new Error("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required");

const headers = { apikey: key, authorization: `Bearer ${key}`, "content-type": "application/json", prefer: "resolution=merge-duplicates,return=representation" };
const post = async (table, rows, onConflict) => {
  const target = new URL(`${url}/rest/v1/${table}`);
  if (onConflict) target.searchParams.set("on_conflict", onConflict);
  const response = await fetch(target, { method: "POST", headers, body: JSON.stringify(rows) });
  if (!response.ok) throw new Error(`${table}: ${response.status} ${await response.text()}`);
  return response.json();
};

function csvRows(text) {
  const rows=[]; let row=[]; let cell=""; let quoted=false;
  for(let i=0;i<text.length;i++){const c=text[i];if(c==='"'){if(quoted&&text[i+1]==='"'){cell+='"';i++;}else quoted=!quoted;}else if(c===','&&!quoted){row.push(cell);cell="";}else if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&text[i+1]==='\n')i++;row.push(cell);cell="";if(row.some(Boolean))rows.push(row);row=[];}else cell+=c;}
  if(cell||row.length){row.push(cell);rows.push(row);} const [head,...body]=rows; return body.map(r=>Object.fromEntries(head.map((h,i)=>[h,r[i]??""])));
}

const report = JSON.parse(await readFile(path.join(dataDir,"report_data.json"),"utf8"));
const facts = csvRows(await readFile(path.join(dataDir,"fendi_bd_facts.csv"),"utf8"));
const inventory = csvRows(await readFile(path.join(dataDir,"inventory_files.csv"),"utf8"));
const sheetInventory = csvRows(await readFile(path.join(dataDir,"inventory_sheets.csv"),"utf8"));
const decisions = csvRows(await readFile(path.join(dataDir,"pending_decisions.csv"),"utf8"));
const batch = await post("migration_batches", [{ batch_key:"PRD01-FENDI-BD-v1", status:"prepared", input_contract_version:"PRD01-2026-09-18", reconciliation:report.summary }], "batch_key");
const batchId = batch[0].id;

for (const file of inventory) {
  const filename = file.source_file;
  const source = await post("source_files", [{ filename, file_hash:file.sha256, source_version:file.sha256.slice(0,12), protected_evidence_path:`evidence://${filename}` }], "file_hash");
  const sourceId = source[0].id;
  const approvedSheets = new Set(facts.filter(f=>f.source_file===filename).map(f=>f.sheet));
  const sheets = sheetInventory.filter(s=>s.source_file===filename).map(s=>({ source_file_id:sourceId, sheet_name:s.sheet, approved:approvedSheets.has(s.sheet) }));
  if (sheets.length) await post("source_sheets", sheets, "source_file_id,sheet_name");
  const rows = facts.filter(f=>f.source_file===filename).map(f=>({
    batch_id:batchId, source_file_id:sourceId, source_sheet:f.sheet, source_row:f.source_row,
    record_hash:f.record_hash, item:f.item, upc:f.upc, period_start:`${f.period}-01`, metric:f.metric,
    quantity:f.value===""?null:Number(f.value), source_payload:f,
    disposition:"prepared",
  }));
  for (let i=0;i<rows.length;i+=200) await post("migration_records", rows.slice(i,i+200), "batch_id,record_hash");
}
await post("migration_issues", decisions.map(d=>({
  batch_id:batchId, issue_code:d.decision_id, severity:"blocking",
  details:{ question:d.question, evidence:d.evidence, owner:d.owner, impact:d.impact }, status:"open",
})), "batch_id,issue_code");
console.log(JSON.stringify({ batch:"PRD01-FENDI-BD-v1", facts:facts.length, files:inventory.length, status:"prepared_for_manager_approval" }));
