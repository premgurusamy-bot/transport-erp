import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { qs } from "../lib/api";
import { inr, monthStart, today } from "../lib/format";
import { t } from "../lib/i18n";
import { Badge, Card, ErrorBox, Field, Kpi, Loading, Page, RefSelect, Table, useLoad } from "../components/ui";

function Bars({ rows }: { rows: { month: string; income: string; expenses: string; profit: string }[] }) {
  const max = Math.max(1, ...rows.flatMap((r) => [Number(r.income), Number(r.expenses)]));
  const h = 150, bw = 18, gap = 22, w = rows.length * (bw * 2 + gap) + 20;
  return <svg viewBox={`0 0 ${w} ${h + 34}`} className="chart" role="img" aria-label="Income and expenses by month">
    {rows.map((r, i) => {
      const x = 10 + i * (bw * 2 + gap);
      const ih = (Number(r.income) / max) * h, eh = (Number(r.expenses) / max) * h;
      return <g key={r.month}>
        <rect x={x} y={h - ih} width={bw} height={ih} className="bar-inc"><title>Income {inr(r.income)}</title></rect>
        <rect x={x + bw + 2} y={h - eh} width={bw} height={eh} className="bar-exp"><title>Expenses {inr(r.expenses)}</title></rect>
        <text x={x + bw} y={h + 16} textAnchor="middle" className="axis">{r.month}</text>
        <text x={x + bw} y={h + 30} textAnchor="middle" className={`axis ${Number(r.profit) < 0 ? "neg" : "pos"}`}>{Math.round(Number(r.profit) / 1000)}k</text>
      </g>;
    })}
  </svg>;
}

export default function Dashboard() {
  const nav = useNavigate();
  const [f, setF] = useState({ start: monthStart(), end: today(), customer_id: null as number | null });
  const { data: d, error } = useLoad<any>(`/api/dashboard${qs(f)}`);
  return <Page title="Dashboard" actions={<div className="row gap wrap filters">
    <Field label="From"><input type="date" value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} /></Field>
    <Field label="To"><input type="date" value={f.end} onChange={(e) => setF({ ...f, end: e.target.value })} /></Field>
    <Field label="Customer"><RefSelect refName="customers" value={f.customer_id} onChange={(v) => setF({ ...f, customer_id: v })} placeholder="All customers" /></Field>
  </div>}>
    <ErrorBox error={error} />
    {!d ? <Loading /> : <>
      <div className="kpis">
        <Kpi label="Total fleet" value={d.fleet.total} sub={`${d.fleet.maintenance} under maintenance`} onClick={() => nav("/fleet-board")} />
        <Kpi label="On road" value={d.fleet.on_trip} tone="good" />
        <Kpi label="Available" value={d.fleet.available} />
        <Kpi label="Today's trips" value={d.today.trips} onClick={() => nav("/trips")} />
        <Kpi label="Today's LR" value={d.today.lrs} onClick={() => nav("/lr")} />
        <Kpi label="Today's billing" value={inr(d.today.billing)} />
        <Kpi label="Monthly revenue" value={inr(d.monthly_revenue)} sub="taxable value billed this month" />
        <Kpi label="Receivables" value={inr(d.receivables)} tone={Number(d.receivables) > 0 ? "warn" : undefined} onClick={() => nav("/reports?r=customer_outstanding")} />
        <Kpi label="Fuel expenses" value={inr(d.period_stats.fuel)} />
        <Kpi label="Maintenance expenses" value={inr(d.period_stats.maintenance)} />
        <Kpi label="Net profit" value={inr(d.period_stats.net_profit)} tone={Number(d.period_stats.net_profit) >= 0 ? "good" : "bad"} sub={`Gross ${inr(d.period_stats.gross_profit)}`} />
        <Kpi label="Pending deliveries" value={d.pending_deliveries} onClick={() => nav("/reports?r=pending_deliveries")} />
        <Kpi label="Pending POD" value={d.pending_pod} onClick={() => nav("/reports?r=pending_pod")} tone={d.pending_pod ? "warn" : undefined} />
        <Kpi label="Unbilled LRs" value={d.unbilled_lrs} onClick={() => nav("/invoices")} />
        <Kpi label="Cash & bank" value={inr(d.cash_bank)} />
        <Kpi label="Payables" value={inr(d.payables)} />
        <Kpi label="Drivers available" value={`${d.drivers.available} / ${d.drivers.total}`} />
        <Kpi label="Completed trips" value={`${d.period_stats.completed_trips} / ${d.period_stats.trips}`} sub="in period" />
      </div>
      <div className="grid2">
        <Card title="Income vs expenses (last 6 months)"><Bars rows={d.trend} /><div className="legend"><span className="sw inc" /> Income <span className="sw exp" /> Expenses · figure below = net profit</div></Card>
        <Card title="Top customers (period)">
          <Table dense cols={[{ key: "key", label: "Customer" }, { key: "trips", label: "Trips", type: "number" }, { key: "revenue", label: "Revenue", type: "money" }, { key: "profit", label: "Profit", type: "money" }]} rows={d.top_customers} />
        </Card>
      </div>
      <div className="grid2">
        <Card title={`Expiring vehicle & driver documents`}>
          <Table dense cols={[{ key: "severity", label: "", type: "badge" }, { key: "title", label: "Document" }, { key: "body", label: "" }]} rows={d.expiring_documents} empty="Nothing expiring in the alert window" />
        </Card>
        <Card title={`${t("Alerts")} (${d.alert_count})`}>
          <Table dense cols={[{ key: "severity", label: "", type: "badge" }, { key: "category", label: "Type" }, { key: "title", label: "Alert" }]} rows={d.alerts} onRow={(a) => a.link && nav(a.link.replace(/\/(\d+)$/, ""))} empty="No alerts" />
        </Card>
      </div>
    </>}
  </Page>;
}

export { Badge };
