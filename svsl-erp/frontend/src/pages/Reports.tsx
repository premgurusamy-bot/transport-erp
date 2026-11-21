import React, { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, qs } from "../lib/api";
import { fyStart, today } from "../lib/format";
import { Btn, Card, ErrorBox, Field, Page, RefSelect, Table, download, useLoad } from "../components/ui";

const PARAMS: Record<string, string[]> = {
  trip_sheet: ["vehicle_id", "driver_id", "customer_id"], lr_register: ["customer_id"], customer_profitability: ["customer_id"], route_profitability: ["customer_id"],
  trip_profitability: ["customer_id"], fuel_mileage: ["vehicle_id"], toll_statement: ["vehicle_id"], customer_statement: ["customer_id"], sales_register: ["customer_id"],
  ledger: ["ledger_id"], stock_register: ["warehouse_id", "customer_id"], stock_movements: ["warehouse_id", "doc_type"], payroll_register: ["month"],
};
const REF: Record<string, string> = { vehicle_id: "vehicles", driver_id: "drivers", customer_id: "customers", ledger_id: "ledgers", warehouse_id: "warehouses" };

export default function Reports() {
  const [sp, setSp] = useSearchParams();
  const list = useLoad<any[]>("/api/reports");
  const key = sp.get("r") || "";
  const [p, setP] = useState<any>({ start: fyStart(), end: today() });
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  React.useEffect(() => { setData(null); setErr(null); }, [key]);
  const runIt = async () => { setErr(null); setData(null); try { setData(await api.get(`/api/reports/${key}${qs(p)}`)); } catch (e: any) { setErr(e.message); } };
  const groups: Record<string, any[]> = {};
  (list.data || []).forEach((r) => (groups[r.group] = groups[r.group] || []).push(r));
  const title = (list.data || []).find((r) => r.key === key)?.title;
  return <Page title="Reports">
    <div className="reports">
      <nav className="report-list">{Object.entries(groups).map(([g, rs]) => <div key={g}><div className="nav-gt">{g}</div>{rs.map((r) => <a key={r.key} className={r.key === key ? "on" : ""} onClick={() => { setSp({ r: r.key }); setData(null); }}>{r.title}</a>)}</div>)}</nav>
      <div className="grow">
        {!key ? <Card title="Select a report"><p className="muted">All reports can be exported to Excel, PDF and CSV.</p></Card> : <Card title={title} actions={<>
          <Btn onClick={runIt} kind="primary">Run</Btn>
          <Btn onClick={() => download(`/api/reports/${key}${qs({ ...p, format: "xlsx" })}`)}>Excel</Btn>
          <Btn onClick={() => download(`/api/reports/${key}${qs({ ...p, format: "pdf" })}`)}>PDF</Btn>
          <Btn onClick={() => download(`/api/reports/${key}${qs({ ...p, format: "csv" })}`)}>CSV</Btn></>}>
          <div className="row gap wrap">
            <Field label="From"><input type="date" value={p.start} onChange={(e) => setP({ ...p, start: e.target.value })} /></Field>
            <Field label="To / as on"><input type="date" value={p.end} onChange={(e) => setP({ ...p, end: e.target.value })} /></Field>
            {(PARAMS[key] || []).map((k) => <Field key={k} label={k.replace("_id", "").replace("_", " ")}>{REF[k] ? <RefSelect refName={REF[k]} value={p[k]} onChange={(v) => setP({ ...p, [k]: v })} placeholder="All" /> : k === "month" ? <input type="month" value={p.month || ""} onChange={(e) => setP({ ...p, month: e.target.value })} /> : k === "doc_type" ? <select value={p.doc_type || ""} onChange={(e) => setP({ ...p, doc_type: e.target.value })}><option value="">All</option>{["Inward", "Outward", "Damage", "Shortage", "Transfer", "Adjustment"].map((x) => <option key={x}>{x}</option>)}</select> : <input value={p[k] || ""} onChange={(e) => setP({ ...p, [k]: e.target.value })} />}</Field>)}
          </div>
          <ErrorBox error={err} />
          {data && <>{data.subtitle && <p className="muted">{data.subtitle}</p>}<Table dense cols={data.columns} rows={data.rows} totals={data.totals} />{(data.notes || []).map((n: string) => <p key={n} className="muted small">{n}</p>)}</>}
        </Card>}
      </div>
    </div>
  </Page>;
}
