import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { qs } from "../lib/api";
import { dt, inr, monthStart, today } from "../lib/format";
import { t } from "../lib/i18n";
import { Bars, change, Donut, Gauge, Icon, Progress, short, StatCard } from "../components/charts";
import { Badge, Card, ErrorBox, Field, Kpi, Page, RefSelect, Table, useLoad } from "../components/ui";
import { tripProgress } from "./Trips";

const VEHICLE_STATUS_COLOR: Record<string, string> = { Available: "var(--c3)", "On Trip": "var(--c1)", Maintenance: "var(--c2)", Breakdown: "var(--bad)", Inactive: "var(--c7)", Sold: "var(--c7)" };
const ALERT_ICON: Record<string, string> = {
  "Vehicle documents": "file", "Driver licence": "user", Maintenance: "wrench", Fuel: "fuel", "Delivery delay": "clock", "POD pending": "file", Receivables: "rupee",
  "Credit limit": "rupee", Compliance: "shield", "E-way bill": "barcode", Contracts: "briefcase", Documents: "file",
};
const SEV_TONE: Record<string, "bad" | "warn" | "info"> = { critical: "bad", warning: "warn", info: "info" };

export function AlertList({ alerts, onOpen, limit = 6 }: { alerts: any[]; onOpen: (a: any) => void; limit?: number }) {
  if (!alerts.length) return <div className="empty-box"><Icon name="check" size={26} /><div>No alerts</div></div>;
  return <div>{alerts.slice(0, limit).map((a, i) => <div key={a.key || i} className="alert-row" onClick={() => onOpen(a)}>
    <span className={`stat-ic ${SEV_TONE[a.severity] || "info"}`}><Icon name={ALERT_ICON[a.category] || "alert"} size={16} /></span>
    <div><b>{a.title}</b><small>{a.category}{a.body ? ` · ${a.body}` : ""}</small></div>
    <span className={`badge solid ${SEV_TONE[a.severity] || "info"}`}>{a.severity === "critical" ? "Critical" : a.severity === "warning" ? "Warning" : "Info"}</span>
  </div>)}</div>;
}

export default function Dashboard() {
  const nav = useNavigate();
  const [f, setF] = useState({ start: monthStart(), end: today(), customer_id: null as number | null });
  const { data: d, error } = useLoad<any>(`/api/dashboard${qs(f)}`);
  const ps = d?.period_stats, pv = d?.prev;
  const openAlert = (a: any) => a.link && nav(a.link.replace(/\/(\d+)$/, ""));
  return <Page title="Dashboard" sub={d ? `${dt(d.period.start)} to ${dt(d.period.end)} · compared with ${dt(pv.start)} to ${dt(pv.end)}` : undefined}
    actions={<div className="row gap wrap filters">
      <Field label="From"><input type="date" value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} /></Field>
      <Field label="To"><input type="date" value={f.end} onChange={(e) => setF({ ...f, end: e.target.value })} /></Field>
      <Field label="Customer"><RefSelect refName="customers" value={f.customer_id} onChange={(v) => setF({ ...f, customer_id: v })} placeholder="All customers" /></Field>
    </div>}>
    <ErrorBox error={error} />
    {!d ? <div className="kpis four">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton" style={{ height: 118 }} />)}</div> : <>
      <div className="kpis four">
        <StatCard icon="truck" label="Active vehicles" value={d.fleet.total} foot={<><b className="good">{d.utilization_pct}%</b> utilisation · {d.fleet.on_trip} on road</>} onClick={() => nav("/fleet-board")} />
        <StatCard icon="route" label="Ongoing trips" value={d.open_trips} tone={d.delayed_trips ? "warn" : "info"} foot={d.delayed_trips ? <span className="bad"><b>{d.delayed_trips}</b> delayed</span> : <span className="good">None delayed</span>} onClick={() => nav("/trips")} />
        <StatCard icon="check" label="Available vehicles" value={d.fleet.available} tone="good" foot={<>{d.drivers.available} of {d.drivers.total} drivers free</>} onClick={() => nav("/fleet-board")} />
        <StatCard icon="wrench" label="Upcoming maintenance" value={d.maintenance_due} tone={d.maintenance_due ? "bad" : "good"} foot={<>{d.fleet.maintenance} vehicle(s) in workshop</>} onClick={() => nav("/maintenance")} />
      </div>
      <div className="kpis four">
        <StatCard icon="rupee" label="Revenue" value={short(ps.income)} delta={change(ps.income, pv.income)} deltaText="vs last period" foot={!pv.income ? <>{inr(ps.income)}</> : null} />
        <StatCard icon="wallet" label="Expenses" value={short(ps.expenses)} tone="warn" delta={change(ps.expenses, pv.expenses)} goodWhen="down" deltaText="vs last period" />
        <StatCard icon="chart" label="Net profit" value={short(ps.net_profit)} tone={Number(ps.net_profit) >= 0 ? "good" : "bad"} delta={change(ps.net_profit, pv.net_profit)} deltaText="vs last period" foot={!pv.net_profit ? <>Gross {short(ps.gross_profit)}</> : null} />
        <StatCard icon="clock" label="Receivables" value={short(d.receivables)} tone="info" foot={<>Cash & bank {short(d.cash_bank)}</>} onClick={() => nav("/reports?r=customer_outstanding")} />
      </div>

      <div className="grid-dash">
        <Card title="Vehicle overview" actions={<a className="small" onClick={() => nav("/fleet-board")}>View all</a>}>
          <Donut center={d.fleet.total} centerSub="vehicles" data={Object.entries(d.fleet.by_status as Record<string, number>).map(([k, v]) => ({ label: k, value: v, color: VEHICLE_STATUS_COLOR[k] }))} onSlice={() => nav("/fleet-board")} />
        </Card>
        <Card title="Ongoing trips" actions={<a className="small" onClick={() => nav("/trips")}>View all</a>}>
          <Table dense cols={[{ key: "vehicle_no", label: "Vehicle" }, { key: "driver_name", label: "Driver" }, { key: "to_place", label: "Destination" },
            { key: "stage", label: "Status", render: (r) => r.delayed ? <span className="badge solid bad">Delayed</span> : <Badge v={r.stage} /> },
            { key: "p", label: "Progress", render: (r) => <Progress pct={tripProgress(r.stage)} slim tone={r.delayed ? "bad" : "info"} /> },
            { key: "eta", label: "ETA", render: (r) => r.eta ? dt(r.eta).slice(0, 16) : "" }]} rows={d.ongoing} onRow={(r) => nav(`/trips?id=${r.id}`)} empty="No trips on the road" />
        </Card>
        <Card title="On-time deliveries">
          <Gauge value={d.on_time.pct} label={d.on_time.delivered ? `${d.on_time.on_time} of ${d.on_time.delivered} trips on time` : "No deliveries with an expected time in this period"} />
          <div className="kpis small" style={{ marginTop: 12, marginBottom: 0 }}>
            <Kpi label="Completed trips" value={`${ps.completed_trips} / ${ps.trips}`} />
            <Kpi label="Pending POD" value={d.pending_pod} tone={d.pending_pod ? "warn" : undefined} onClick={() => nav("/reports?r=pending_pod")} />
          </div>
        </Card>
      </div>

      <div className="grid2">
        <Card title="Income vs expenses" actions={<span className="muted small">last 6 months</span>}>
          <Bars labels={d.trend.map((r: any) => r.month)} series={[{ name: "Income", values: d.trend.map((r: any) => Number(r.income)) }, { name: "Expenses", values: d.trend.map((r: any) => Number(r.expenses)), color: "var(--c2)" }, { name: "Net profit", values: d.trend.map((r: any) => Number(r.profit)), color: "var(--c3)" }]} />
        </Card>
        <Card title={`${t("Alerts")} (${d.alert_count})`} actions={<a className="small" onClick={() => nav("/compliance")}>View all</a>}>
          <AlertList alerts={d.alerts} onOpen={openAlert} />
        </Card>
      </div>

      <div className="kpis">
        <Kpi label="Today's trips" value={d.today.trips} onClick={() => nav("/trips")} />
        <Kpi label="Today's LR" value={d.today.lrs} onClick={() => nav("/lr")} />
        <Kpi label="Today's billing" value={inr(d.today.billing)} onClick={() => nav("/invoices")} />
        <Kpi label="Monthly revenue" value={inr(d.monthly_revenue)} sub="taxable value billed this month" />
        <Kpi label="Pending deliveries" value={d.pending_deliveries} onClick={() => nav("/reports?r=pending_deliveries")} />
        <Kpi label="Unbilled LRs" value={d.unbilled_lrs} tone={d.unbilled_lrs ? "warn" : undefined} onClick={() => nav("/invoices")} />
        <Kpi label="Fuel expenses" value={inr(ps.fuel)} sub={change(ps.fuel, pv.fuel) !== null ? `${change(ps.fuel, pv.fuel)}% vs last period` : ""} onClick={() => nav("/fuel")} />
        <Kpi label="Maintenance expenses" value={inr(ps.maintenance)} onClick={() => nav("/maintenance")} />
        <Kpi label="Payables" value={inr(d.payables)} onClick={() => nav("/reports?r=supplier_outstanding")} />
      </div>

      <div className="grid2">
        <Card title="Top customers" actions={<span className="muted small">this period</span>}>
          <Table dense cols={[{ key: "key", label: "Customer" }, { key: "trips", label: "Trips", type: "number" }, { key: "revenue", label: "Revenue", type: "money" }, { key: "profit", label: "Profit", type: "money" }]} rows={d.top_customers} empty="No trips in this period" />
        </Card>
        <Card title="Expiring vehicle & driver documents">
          <AlertList alerts={d.expiring_documents} onOpen={openAlert} limit={8} />
        </Card>
      </div>
    </>}
  </Page>;
}

export { Badge };
